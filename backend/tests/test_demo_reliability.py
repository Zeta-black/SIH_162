"""Demo-day reliability: the app must always show something, honestly labelled.

These tests encode the failure modes a venue network actually produces — a
rejected key, a dead network, a rate limit, an empty window — and assert both
halves of the contract: that data still reaches the screen, and that it is never
dressed up as something it is not.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.schemas import HotspotEvent
from app.services import livecache, pipeline
from app.services.firms import FirmsClient, FirmsError


def make_hotspot(idx: int = 0) -> HotspotEvent:
    now = datetime.now(timezone.utc)
    return HotspotEvent(
        event_id=f"EVT-CACHE{idx:06d}",
        latitude=21.5 + idx * 0.01,
        longitude=86.7,
        acquisition_date=now.date(),
        acquisition_time="07:15",
        acquired_at=now,
        brightness_k=350.0,
        frp_mw=12.0,
        source_product="VIIRS_NOAA21_NRT",
        source_mode="live",
        raw_source_reference="test",
        ingested_at=now,
    )


# --------------------------------------------------------------- disk cache
class TestLiveDiskCache:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        """Never touch the real cache file from a test."""
        monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "last_live_fetch.json")
        monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)

    def test_round_trips_a_fetch(self):
        events = [make_hotspot(i) for i in range(3)]
        livecache.save(events, "68,6.5,97.5,36", 1, ["VIIRS_NOAA21_NRT"])

        loaded = livecache.load()
        assert loaded is not None
        assert len(loaded.events) == 3
        assert loaded.products == ["VIIRS_NOAA21_NRT"]
        assert loaded.events[0].event_id == events[0].event_id

    def test_an_empty_result_is_not_saved(self):
        """'Nothing is burning' is a valid live answer and a useless fallback.

        Saving it would overwrite a good cache with a blank one.
        """
        livecache.save([make_hotspot()], "bbox", 1, ["P"])
        livecache.save([], "bbox", 1, ["P"])

        loaded = livecache.load()
        assert loaded is not None
        assert len(loaded.events) == 1

    def test_a_stale_cache_is_ignored(self, monkeypatch):
        """A two-week-old 'live' feed is worse than an honestly-labelled archive."""
        livecache.save([make_hotspot()], "bbox", 1, ["P"])

        stale = json.loads(livecache.CACHE_FILE.read_text(encoding="utf-8"))
        stale["cached_at"] = (
            datetime.now(timezone.utc)
            - timedelta(hours=settings.live_disk_cache_max_age_hours + 1)
        ).isoformat()
        livecache.CACHE_FILE.write_text(json.dumps(stale), encoding="utf-8")

        assert livecache.load() is None

    def test_a_corrupt_cache_does_not_raise(self):
        livecache.CACHE_FILE.write_text("{ not json", encoding="utf-8")
        assert livecache.load() is None

    def test_missing_cache_is_simply_absent(self):
        assert livecache.load() is None
        assert livecache.status()["present"] is False

    def test_status_reports_the_real_age_not_freshness(self):
        livecache.save([make_hotspot()], "bbox", 1, ["P"])
        status = livecache.status()
        assert status["present"] is True
        assert "age_minutes" in status
        assert "never as a live feed" in status["note"]


# ------------------------------------------------------------------ retries
class TestFirmsRetry:
    def test_a_connection_error_is_not_retried(self, monkeypatch):
        """No route to NASA will not change in 600 ms. Fail fast so the
        fallback engages immediately; retrying every product turned a dead
        network into a ~20 s wait."""
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx.Client, "get", boom)
        with pytest.raises(httpx.ConnectError):
            FirmsClient()._get("https://example.invalid/x")
        assert calls["n"] == 1

    def test_a_timeout_is_retried_then_raised(self, monkeypatch):
        calls = {"n": 0}

        def slow(*args, **kwargs):
            calls["n"] += 1
            raise httpx.ReadTimeout("too slow")

        monkeypatch.setattr(httpx.Client, "get", slow)
        monkeypatch.setattr(settings, "firms_retry_backoff_seconds", 0.0)
        with pytest.raises(httpx.ReadTimeout):
            FirmsClient()._get("https://example.invalid/x")
        assert calls["n"] == settings.firms_retries + 1

    def test_the_timeout_is_short_enough_for_a_demo(self):
        """45 s per product meant over two minutes before any fallback."""
        assert settings.firms_timeout_seconds <= 10.0


# ------------------------------------------------------------- degradation
def _client(monkeypatch, firms_behaviour):
    from app.main import app

    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 60)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 6)
    monkeypatch.setattr("app.services.firms.FirmsClient.fetch_area", firms_behaviour)
    monkeypatch.setattr("app.services.osm.fetch_facilities", lambda *a, **k: ([], "unavailable"))
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))
    return TestClient(app)


class TestGracefulDegradation:
    """Each failure must still put real data on screen, correctly labelled."""

    @pytest.fixture(autouse=True)
    def _no_real_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
        monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
        yield
        pipeline.clear_cache()

    def test_rejected_key_falls_back_and_never_claims_live(self, monkeypatch):
        """Regression for docs/BASELINE.md D2.

        A bad key used to return HTTP 200 with zero events, mode "live" and the
        label "Live NASA FIRMS" — an empty map under a green badge.
        """
        def rejected(*args, **kwargs):
            raise FirmsError("key rejected", kind="not_configured")

        with _client(monkeypatch, rejected) as c:
            body = c.get("/api/map", params={"mode": "live", "days": 1}).json()

        prov = body["provenance"]
        assert prov["is_live"] is False
        assert prov["state"] in ("offline", "unavailable")
        assert body["counts"]["sites"] > 0, "a rejected key must not empty the map"

    def test_dead_network_falls_back_to_the_archive(self, monkeypatch):
        def dead(*args, **kwargs):
            raise FirmsError("Could not reach NASA FIRMS", kind="unavailable")

        with _client(monkeypatch, dead) as c:
            body = c.get("/api/map", params={"mode": "auto", "days": 1}).json()

        assert body["provenance"]["is_live"] is False
        assert body["counts"]["sites"] > 0

    def test_rate_limit_degrades_without_crashing(self, monkeypatch):
        def limited(*args, **kwargs):
            raise FirmsError("rate limited by FIRMS (HTTP 429)", kind="unavailable")

        with _client(monkeypatch, limited) as c:
            response = c.get("/api/map", params={"mode": "auto", "days": 1})

        assert response.status_code == 200
        assert response.json()["provenance"]["is_live"] is False

    def test_the_cached_fetch_is_preferred_over_the_archive(self, monkeypatch):
        """Recent real live data beats a 2025 archive — but is still not live."""
        livecache.save([make_hotspot(i) for i in range(4)], "68,6.5,97.5,36", 1, ["VIIRS_NOAA21_NRT"])

        def dead(*args, **kwargs):
            raise FirmsError("no route", kind="unavailable")

        with _client(monkeypatch, dead) as c:
            body = c.get("/api/map", params={"mode": "auto", "days": 1}).json()

        prov = body["provenance"]
        assert prov["state"] == "offline"
        assert prov["is_live"] is False
        assert "saved" in prov["label"].lower()

    def test_health_stays_serviceable_when_the_feed_is_down(self, monkeypatch):
        def dead(*args, **kwargs):
            raise FirmsError("no route", kind="unavailable")

        with _client(monkeypatch, dead) as c:
            body = c.get("/health").json()

        # The service can still do its job from the model plus the archive.
        assert body["status"] == "ok"
        assert body["snapshot_available"] is True


class TestProvenanceIsNeverFlattering:
    """The one invariant worth more than any feature on the screen."""

    @pytest.fixture(autouse=True)
    def _no_real_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
        monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
        yield
        pipeline.clear_cache()

    @pytest.mark.parametrize(
        "kind,message",
        [
            ("not_configured", "key rejected"),
            ("unavailable", "no route"),
            ("unavailable", "rate limited"),
        ],
    )
    def test_no_failure_mode_produces_a_live_badge(self, monkeypatch, kind, message):
        def fail(*args, **kwargs):
            raise FirmsError(message, kind=kind)

        for mode in ("auto", "live", "demo"):
            with _client(monkeypatch, fail) as c:
                prov = c.get("/api/map", params={"mode": mode, "days": 1}).json()["provenance"]
            assert prov["is_live"] is False, f"{mode}/{kind} reported a live feed"
            assert prov["state"] != "live"

    def test_demo_mode_never_contacts_the_network(self, monkeypatch):
        """The guaranteed path. If this calls out, the offline demo is a lie."""
        calls = {"n": 0}

        def counted(*args, **kwargs):
            calls["n"] += 1
            raise FirmsError("should not have been called", kind="unavailable")

        with _client(monkeypatch, counted) as c:
            body = c.get("/api/map", params={"mode": "demo", "days": 1}).json()

        assert calls["n"] == 0
        assert body["provenance"]["state"] == "replay"
        assert body["counts"]["sites"] > 0

"""The notification system, against docs/NOTIFICATION_POLICY.md.

Two classes of test here. The first checks the mechanism — trigger, dedupe,
cooldown, escalation, state machine, webhook retry. The second checks the
*claims*: that a replay sends nothing, that non-qualifying statuses stay silent,
and that no message can tell an operator a fire is confirmed.

The second class is the one that matters. A notification is a claim someone
should act on, and the cost of a wrong one is that the next one gets ignored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import settings
from app.services import notifications as notify

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Every test gets its own queue and a clean seed flag."""
    store = notify.reset_store_for_tests(str(tmp_path / "notify.sqlite3"))
    notify.reset_seed_for_tests()
    monkeypatch.setattr(settings, "notify_enabled", True)
    monkeypatch.setattr(settings, "webhook_url", "")
    yield store
    store.clear()


def site(**overrides) -> dict:
    """A site shaped exactly as /api/map emits one."""
    base = {
        "id": "FE-2026-TEST1",
        "lat": 21.1,
        "lon": 72.64,
        "title": "Test Steel Works",
        "status": "needs_attention",
        "status_label": "Needs attention",
        "verdict": "Heat on the Test Steel Works site with an episodic signature.",
        "predicted_class": "INDUSTRIAL_FIRE",
        "model_score": 0.91,
        "operational_priority": "HIGH",
        "priority_score": 0.78,
        "abnormality_score": None,
        "abnormality_status": "insufficient_history",
        "persistent": False,
        "distinct_days": 0,
        "history_available": True,
        "nearest_facility_name": "Test Steel Works",
        "nearest_facility_km": 0.25,
        "observed_at": "2026-10-26T07:15:00+00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- triggers
class TestWhatTriggers:
    def test_needs_attention_creates_a_high_severity_item(self):
        result = notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        assert len(result["created"]) >= 1
        item = next(c for c in result["created"] if c["reason_code"] == notify.NEEDS_ATTENTION)
        assert item["severity"] == "high"
        assert "Test Steel Works" in item["title"]

    @pytest.mark.parametrize("status", ["normal", "watch", "not_sure"])
    def test_non_qualifying_statuses_never_notify(self, status):
        """Normal, Watch and Not sure live on the map. Pushing them is how an
        operator learns to ignore the bell."""
        result = notify.evaluate(
            [site(status=status, persistent=False, nearest_facility_km=5.0)],
            suppress=False,
            now=NOW,
            seed_only=False,
        )
        assert result["created"] == []

    def test_abnormal_persistent_requires_an_assessed_baseline(self):
        """The notification form of the Pass 1 abnormality defect.

        A site whose baseline could not be assessed must never produce an
        "above its normal range" claim, because there is no normal range.
        """
        unassessed = site(
            status="watch",
            persistent=True,
            abnormality_score=None,
            abnormality_status="insufficient_history",
            nearest_facility_km=5.0,
        )
        result = notify.evaluate([unassessed], suppress=False, now=NOW, seed_only=False)
        assert not any(
            c["reason_code"] == notify.ABNORMAL_PERSISTENT for c in result["created"]
        )

    def test_abnormal_persistent_fires_with_a_real_baseline(self):
        assessed = site(
            status="watch",
            persistent=True,
            abnormality_score=88,
            abnormality_status="assessed",
            distinct_days=9,
            nearest_facility_km=5.0,
        )
        result = notify.evaluate([assessed], suppress=False, now=NOW, seed_only=False)
        item = next(
            c for c in result["created"] if c["reason_code"] == notify.ABNORMAL_PERSISTENT
        )
        assert "88" in item["body"]
        assert "9 days" in item["body"]

    def test_new_heat_at_a_facility_with_no_history(self):
        result = notify.evaluate(
            [site(status="watch", distinct_days=0, nearest_facility_km=0.2)],
            suppress=False,
            now=NOW,
            seed_only=False,
        )
        item = next(
            c for c in result["created"] if c["reason_code"] == notify.NEW_HEAT_AT_FACILITY
        )
        assert item["severity"] == "medium"
        assert "New heat detected" in item["title"]

    def test_one_site_produces_one_notification_per_evaluation(self):
        """The default site qualifies for both NEEDS_ATTENTION and
        NEW_HEAT_AT_FACILITY. Two bells for one event is alert fatigue, so only
        the most severe reason speaks."""
        example = site(status="needs_attention", distinct_days=0, nearest_facility_km=0.2)
        assert len(notify._reasons_for(example)) == 2

        result = notify.evaluate([example], suppress=False, now=NOW, seed_only=False)
        assert len(result["created"]) == 1
        assert result["created"][0]["reason_code"] == notify.NEEDS_ATTENTION

    def test_feed_delay_creates_a_system_notice(self):
        result = notify.evaluate(
            [],
            suppress=False,
            feed={"observed_age_minutes": 60 * 20},
            now=NOW,
            seed_only=False,
        )
        assert any(
            c["reason_code"] == notify.SYSTEM_FEED_DELAYED for c in result["created"]
        )

    def test_a_fresh_feed_creates_no_system_notice(self):
        result = notify.evaluate(
            [], suppress=False, feed={"observed_age_minutes": 30}, now=NOW, seed_only=False
        )
        assert result["created"] == []


# ------------------------------------------------------------- replay safety
class TestReplaySendsNothing:
    """The single most important guarantee in this module."""

    def test_suppressed_evaluation_writes_nothing(self, isolated_store):
        result = notify.evaluate([site()], suppress=True, now=NOW)
        assert result["created"] == []
        assert result["suppressed"] is True
        assert isolated_store.recent(include_resolved=True) == []

    def test_suppressed_evaluation_still_previews(self):
        result = notify.evaluate([site()], suppress=True, now=NOW)
        assert len(result["preview"]) >= 1
        assert result["reason"] == "replay"

    def test_suppression_also_blocks_system_notices(self, isolated_store):
        notify.evaluate(
            [], suppress=True, feed={"observed_age_minutes": 60 * 48}, now=NOW
        )
        assert isolated_store.recent(include_resolved=True) == []

    def test_a_replay_cannot_reach_the_webhook(self, monkeypatch, isolated_store):
        """Enforced at creation, so a channel cannot forget to check."""
        monkeypatch.setattr(settings, "webhook_url", "https://example.invalid/hook")
        sent = {"n": 0}

        def should_not_post(*args, **kwargs):
            sent["n"] += 1
            raise AssertionError("a replay must never reach the webhook")

        monkeypatch.setattr(httpx.Client, "post", should_not_post)
        notify.evaluate([site()], suppress=True, now=NOW)
        assert sent["n"] == 0


# ------------------------------------------------------------------ hygiene
class TestHygiene:
    def test_the_first_evaluation_seeds_without_surfacing(self, isolated_store):
        """Otherwise every pre-existing Needs-attention site alerts at once on a
        cold start, which is exactly the flood this policy exists to prevent."""
        result = notify.evaluate([site()], suppress=False, now=NOW)
        assert result["seeded"] is True
        assert result["created"] == []
        # Recorded, so the cooldown clock has started.
        assert isolated_store.recent(include_resolved=True)

    def test_a_repeat_inside_the_cooldown_is_dropped(self):
        notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        again = notify.evaluate(
            [site()], suppress=False, now=NOW + timedelta(hours=1), seed_only=False
        )
        assert not any(
            c["reason_code"] == notify.NEEDS_ATTENTION for c in again["created"]
        )

    def test_the_cooldown_expires(self):
        notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        later = notify.evaluate(
            [site(priority_score=0.9)],
            suppress=False,
            now=NOW + timedelta(hours=settings.notify_cooldown_hours + 1),
            seed_only=False,
        )
        assert any(c["reason_code"] == notify.NEEDS_ATTENTION for c in later["created"])

    def test_escalation_overrides_the_cooldown(self):
        """A worsening situation is not held back by a timer."""
        notify.evaluate(
            [site(status="watch", distinct_days=0, nearest_facility_km=0.2)],
            suppress=False,
            now=NOW,
            seed_only=False,
        )
        escalated = notify.evaluate(
            [site(status="needs_attention", priority_score=0.95)],
            suppress=False,
            now=NOW + timedelta(minutes=10),
            seed_only=False,
        )
        assert any(c["severity"] == "high" for c in escalated["created"])

    def test_hysteresis_stops_a_value_flapping(self):
        """A site sitting on the threshold must move before it speaks again."""
        notify.evaluate([site(priority_score=0.70)], suppress=False, now=NOW, seed_only=False)
        barely = notify.evaluate(
            [site(priority_score=0.701)],
            suppress=False,
            now=NOW + timedelta(hours=settings.notify_cooldown_hours + 1),
            seed_only=False,
        )
        assert not any(
            c["reason_code"] == notify.NEEDS_ATTENTION for c in barely["created"]
        )

    def test_system_notices_are_capped_per_day(self, monkeypatch):
        monkeypatch.setattr(settings, "notify_system_daily_cap", 2)
        for hour in range(6):
            notify.evaluate(
                [],
                suppress=False,
                feed={"observed_age_minutes": 60 * 30},
                now=NOW + timedelta(hours=hour),
                seed_only=False,
            )
        assert notify.get_store().system_count_today() <= 2

    def test_disabling_notifications_silences_everything(self, monkeypatch):
        monkeypatch.setattr(settings, "notify_enabled", False)
        result = notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        assert result["created"] == []
        assert result["reason"] == "disabled"


# ----------------------------------------------------------- state machine
class TestStateMachine:
    def test_acknowledge_and_snooze_and_resolve(self, isolated_store):
        notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        item = isolated_store.recent()[0]

        assert isolated_store.set_state(item["id"], "seen", seen_at=NOW.isoformat())
        assert isolated_store.set_state(
            item["id"], "acknowledged", acknowledged_at=NOW.isoformat()
        )
        assert isolated_store.recent()[0]["state"] == "acknowledged"

        until = (NOW + timedelta(hours=6)).isoformat()
        assert isolated_store.set_state(item["id"], "snoozed", snoozed_until=until)
        assert isolated_store.recent()[0]["snoozed_until"] == until

        assert isolated_store.set_state(item["id"], "resolved", resolved_at=NOW.isoformat())
        assert isolated_store.recent(include_resolved=False) == []
        assert isolated_store.recent(include_resolved=True)

    def test_an_unknown_id_is_rejected(self, isolated_store):
        assert isolated_store.set_state("does-not-exist", "acknowledged") is False

    def test_unread_count_tracks_created_items(self, isolated_store):
        notify.evaluate([site()], suppress=False, now=NOW, seed_only=False)
        assert isolated_store.counts()["unread"] >= 1


# ---------------------------------------------------------------- language
class TestLanguage:
    @pytest.mark.parametrize(
        "reason,example",
        [
            (notify.NEEDS_ATTENTION, site()),
            (
                notify.ABNORMAL_PERSISTENT,
                site(persistent=True, abnormality_score=90, abnormality_status="assessed"),
            ),
            (notify.NEW_HEAT_AT_FACILITY, site(status="watch")),
        ],
    )
    def test_no_message_overstates_the_evidence(self, reason, example):
        severity, title, body = notify._build(reason, example)
        combined = f"{title} {body}".lower()
        for word in notify.FORBIDDEN_WORDS:
            assert word not in combined, f"{reason} says {word!r}"

    def test_new_heat_is_never_a_confirmed_fire(self):
        _, title, body = notify._build(notify.NEW_HEAT_AT_FACILITY, site())
        assert "new heat detected" in title.lower()
        assert "fire" not in title.lower()
        assert "not proof of cause" in body.lower()

    def test_the_language_guard_actually_raises(self):
        with pytest.raises(ValueError, match="may not contain"):
            notify._check_language("Fire confirmed at the refinery")

    def test_the_policy_states_what_it_will_not_do(self):
        policy = notify.policy_summary()
        assert set(policy["never_notifies_for"]) == {"normal", "watch", "not_sure"}
        assert "confirmed" in policy["language_rule"]
        assert policy["policy_version"] == notify.POLICY_VERSION


# ----------------------------------------------------------------- webhook
class TestWebhook:
    def test_disabled_when_unset(self):
        result = notify.deliver_webhook({"id": "x", "title": "t", "reason_code": "r", "severity": "high"})
        assert result["sent"] is False
        assert "no webhook" in result["reason"]

    def test_payload_is_slack_compatible_and_carries_provenance(self):
        payload = notify.webhook_payload(
            {
                "id": "n1",
                "title": "Needs attention at X",
                "body": "because",
                "reason_code": notify.NEEDS_ATTENTION,
                "severity": "high",
                "site_id": "FE-1",
                "site_name": "X",
                "status": "needs_attention",
                "observed_at": "2026-10-26T07:00:00+00:00",
                "policy_version": notify.POLICY_VERSION,
                "is_test": False,
            },
            link_base="http://localhost:5173",
        )
        assert payload["text"].startswith("FIRETRACE · ")
        assert payload["firetrace"]["reason_code"] == notify.NEEDS_ATTENTION
        assert payload["firetrace"]["link"].endswith("?site=FE-1")
        assert payload["firetrace"]["replay"] is False

    def test_a_test_alert_is_labelled_in_the_text(self):
        payload = notify.webhook_payload(
            {"id": "t", "title": "drill", "reason_code": "x", "severity": "high", "is_test": True}
        )
        assert payload["text"].startswith("[TEST]")
        assert payload["firetrace"]["is_test"] is True

    def test_retries_then_records_failure(self, monkeypatch, isolated_store):
        monkeypatch.setattr(settings, "webhook_url", "https://example.invalid/hook")
        monkeypatch.setattr(settings, "webhook_backoff_seconds", 0.0)
        attempts = {"n": 0}

        def always_fail(*args, **kwargs):
            attempts["n"] += 1
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx.Client, "post", always_fail)
        result = notify.deliver_webhook(
            {"id": "n-fail", "title": "t", "reason_code": "r", "severity": "high"}
        )

        assert result["sent"] is False
        assert attempts["n"] == settings.webhook_retries + 1
        rows = isolated_store.deliveries("n-fail")
        assert len(rows) == settings.webhook_retries + 1
        assert all(row["ok"] == 0 for row in rows)

    def test_a_successful_delivery_is_audited(self, monkeypatch, isolated_store):
        monkeypatch.setattr(settings, "webhook_url", "https://example.invalid/hook")

        class Fine:
            status_code = 200
            text = "ok"

        monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: Fine())
        result = notify.deliver_webhook(
            {"id": "n-ok", "title": "t", "reason_code": "r", "severity": "high"}
        )
        assert result["sent"] is True
        rows = isolated_store.deliveries("n-ok")
        assert len(rows) == 1 and rows[0]["ok"] == 1


# --------------------------------------------------------------------- API
class TestNotificationApi:
    def test_policy_endpoint_describes_the_policy(self, client):
        body = client.get("/api/notifications/policy").json()
        assert body["policy_version"] == notify.POLICY_VERSION
        assert len(body["reasons"]) == 5
        assert body["hygiene"]["escalation_overrides_cooldown"] is True

    def test_centre_lists_items_and_counts(self, client):
        body = client.get("/api/notifications").json()
        assert "items" in body and "counts" in body and "policy" in body

    def test_test_alert_is_labelled_TEST(self, client):
        body = client.post("/api/notifications/test").json()
        assert body["notification"]["is_test"] is True
        assert "TEST" in body["notification"]["title"]

    def test_changes_endpoint_is_cheap_and_timestamped(self, client):
        body = client.get("/api/changes").json()
        assert "server_time" in body and "counts" in body and "new_count" in body

    def test_action_on_a_missing_id_is_404(self, client):
        response = client.post(
            "/api/notifications/nope/action", json={"action": "acknowledge"}
        )
        assert response.status_code == 404

    def test_past_mode_over_the_api_creates_nothing(self, client):
        before = client.get("/api/notifications").json()["counts"]["open"]
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        after = client.get("/api/notifications").json()["counts"]["open"]
        assert body["notifications"]["suppressed"] is True
        assert body["provenance"]["alerts_suppressed"] is True
        assert after == before


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.main import app
    from app.services import livecache, pipeline
    from app.services.firms import FirmsError
    from fastapi.testclient import TestClient

    monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 60)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 6)
    monkeypatch.setattr(
        "app.services.firms.FirmsClient.fetch_area",
        lambda *a, **k: (_ for _ in ()).throw(FirmsError("offline", kind="unavailable")),
    )
    monkeypatch.setattr("app.services.osm.fetch_facilities", lambda *a, **k: ([], "unavailable"))
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))

    with TestClient(app) as c:
        yield c

    pipeline.clear_cache()

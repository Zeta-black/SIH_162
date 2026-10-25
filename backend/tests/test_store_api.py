"""Event store, classifier fallback behaviour and the HTTP API.

The API tests run against the real FastAPI app with the network mocked out, so
they exercise the same code path a browser hits — including the resilience
requirement that a dead NASA endpoint must still produce a usable dashboard.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import Facility
from app.services import pipeline
from app.services.classifier import ClassifierService, confidence_level
from app.services.firms import FirmsError
from app.store.db import EventStore
from app.taxonomy import ALL_CLASSES, UNKNOWN


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "test.sqlite3")


class TestEventStore:
    def test_initialises(self, store):
        assert store.ready is True
        assert store.event_count() == 0

    def test_round_trips_an_event(self, store, event):
        assert store.upsert_events([event]) == 1
        loaded = store.load_events()
        assert len(loaded) == 1
        assert loaded[0].event_id == event.event_id
        assert loaded[0].latitude == pytest.approx(event.latitude)
        assert loaded[0].frp_mw == pytest.approx(event.frp_mw)

    def test_ingest_is_idempotent(self, store, event):
        store.upsert_events([event])
        assert store.upsert_events([event]) == 0
        assert store.event_count() == 1

    def test_preserves_null_optional_fields(self, store, event_factory):
        event = event_factory(frp=None, brightness=None, day_night=None)
        store.upsert_events([event])
        loaded = store.load_events()[0]
        assert loaded.frp_mw is None
        assert loaded.brightness_k is None

    def test_bbox_filter(self, store, event_factory):
        store.upsert_events(
            [
                event_factory(event_id="EVT-IN", lat=22.3, lon=69.8),
                event_factory(event_id="EVT-OUT", lat=30.5, lon=76.2),
            ]
        )
        inside = store.load_events(bbox=(69.0, 22.0, 70.0, 23.0))
        assert [e.event_id for e in inside] == ["EVT-IN"]

    def test_date_filter(self, store, event_factory):
        store.upsert_events(
            [
                event_factory(event_id="EVT-OLD", acq_date=date(2026, 1, 1)),
                event_factory(event_id="EVT-NEW", acq_date=date(2026, 3, 15)),
            ]
        )
        recent = store.load_events(since=date(2026, 3, 1))
        assert [e.event_id for e in recent] == ["EVT-NEW"]

    def test_facilities_round_trip(self, store, facility):
        assert store.upsert_facilities([facility]) == 1
        loaded = store.load_facilities()
        assert loaded[0].name == "Test Refinery"
        assert loaded[0].tags["industrial"] == "oil"

    def test_facility_upsert_replaces(self, store, facility):
        store.upsert_facilities([facility])
        store.upsert_facilities([facility])
        assert store.facility_count() == 1

    def test_ingest_run_is_recorded(self, store):
        store.record_ingest("live", "68,6,97,36", ["VIIRS_NOAA21_NRT"], 42, "ok")
        last = store.last_ingest()
        assert last["events_ingested"] == 42
        assert last["mode"] == "live"

    def test_date_span(self, store, event_factory):
        store.upsert_events(
            [
                event_factory(event_id="EVT-A", acq_date=date(2026, 3, 10)),
                event_factory(event_id="EVT-B", acq_date=date(2026, 3, 15)),
            ]
        )
        assert store.date_span() == ("2026-03-10", "2026-03-15")

    def test_prune(self, store, event_factory):
        store.upsert_events([event_factory(event_id="EVT-OLD", acq_date=date(2020, 1, 1))])
        assert store.prune_older_than(30) == 1
        assert store.event_count() == 0


# ---------------------------------------------------------------------------
# Classifier without an artifact
# ---------------------------------------------------------------------------
class TestClassifierFallback:
    def test_missing_artifact_degrades_instead_of_crashing(
        self, tmp_path, event, nearest_facility, land_cover_industrial
    ):
        service = ClassifierService(tmp_path / "does_not_exist.joblib")
        assert service.loaded is False
        assert "train" in service.status_note.lower()

        from app.services.recurrence import HistoryIndex

        rec = HistoryIndex([]).compute(event)
        classification, probabilities, factors = service.predict(
            event, nearest_facility, land_cover_industrial, rec
        )
        # It must still answer, and it must answer honestly.
        assert classification.label == UNKNOWN
        assert classification.abstained is True
        assert factors

    def test_info_reports_not_loaded(self, tmp_path):
        info = ClassifierService(tmp_path / "nope.joblib").info()
        assert info.loaded is False
        assert info.model_version == "unavailable"

    def test_batch_predict_without_model(
        self, tmp_path, event, nearest_facility, land_cover_industrial
    ):
        from app.services.recurrence import HistoryIndex

        service = ClassifierService(tmp_path / "nope.joblib")
        rec = HistoryIndex([]).compute(event)
        results = service.predict_batch([(event, nearest_facility, land_cover_industrial, rec)])
        assert len(results) == 1
        assert results[0][0].label == UNKNOWN


class TestConfidenceLevels:
    @pytest.mark.parametrize(
        "probability,expected",
        [(0.95, "HIGH"), (0.75, "HIGH"), (0.74, "MEDIUM"), (0.50, "MEDIUM"), (0.49, "LOW"), (0.0, "LOW")],
    )
    def test_bands(self, probability, expected):
        assert confidence_level(probability) == expected


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient whose data sources are all stubbed out.

    FIRMS is forced to fail so every test also proves the fallback path works.

    The on-disk live cache is redirected into tmp_path. Without that, these
    tests read whatever the developer's last real fetch left behind, and
    "survives a total NASA outage" started passing or failing depending on
    whether a cache file happened to exist on the machine.
    """
    from app.main import app
    from app.services import livecache

    monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "last_live_fetch.json")
    monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)

    pipeline.clear_cache()

    # Each test starts with a cold analysis cache for isolation, so the full
    # snapshot would be re-analysed ~25 times. The per-event explanation walks
    # every tree in the forest, which made the suite take minutes. Bounding the
    # work keeps the identical code path while staying fast.
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 60)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 8)

    def fail_firms(*args, **kwargs):
        raise FirmsError("Simulated NASA outage", kind="unavailable")

    def no_overpass(*args, **kwargs):
        return [], "unavailable"

    monkeypatch.setattr("app.services.firms.FirmsClient.fetch_area", fail_firms)
    monkeypatch.setattr("app.services.osm.fetch_facilities", no_overpass)
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))

    with TestClient(app) as c:
        yield c

    pipeline.clear_cache()


class TestHealth:
    def test_responds(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["app"] == "FIRETRACE"

    def test_never_leaks_the_key(self, client):
        body = client.get("/health").text
        assert "a537f4e4" not in body
        assert "MAP_KEY" not in body or "map_key" not in body.lower().replace("firms_key_configured", "")

    def test_reports_capability_flags(self, client):
        body = client.get("/health").json()
        assert isinstance(body["model_loaded"], bool)
        assert isinstance(body["firms_key_configured"], bool)
        assert isinstance(body["store_ready"], bool)


class TestMeta:
    def test_returns_full_taxonomy(self, client):
        body = client.get("/api/meta").json()
        ids = {c["id"] for c in body["classes"]}
        assert ids == set(ALL_CLASSES)

    def test_every_class_has_colour_and_code(self, client):
        for cls in client.get("/api/meta").json()["classes"]:
            assert cls["color"].startswith("#")
            assert cls["code"]

    def test_unknown_is_marked_untrained(self, client):
        classes = {c["id"]: c for c in client.get("/api/meta").json()["classes"]}
        assert classes[UNKNOWN]["trained"] is False

    def test_priority_formula_is_published(self, client):
        priority = client.get("/api/meta").json()["priority"]
        assert "weights" in priority and "components" in priority

    def test_disclaimer_present(self, client):
        assert "not a confirmed" in client.get("/api/meta").json()["disclaimer"].lower()


class TestModelInfo:
    def test_declares_label_provenance(self, client):
        body = client.get("/api/model/info").json()
        assert body["label_policy"]["ground_truth"] is False

    def test_explains_abstention(self, client):
        body = client.get("/api/model/info").json()
        assert "not a trained class" in body["abstention"]["note"].lower()


class TestHotspotsEndpoint:
    def test_survives_total_nasa_outage(self, client):
        """The core resilience requirement.

        With no usable on-disk cache (the fixture isolates it), a total outage
        lands on the frozen archive. When a recent cache *is* present the
        pipeline prefers it and reports mode "cached" instead — covered in
        tests/test_demo_reliability.py.
        """
        response = client.get("/api/hotspots?days=3&mode=auto")
        assert response.status_code == 200
        body = response.json()
        assert body["status"]["mode"] == "snapshot"
        assert "summary" in body and "events" in body

    def test_outage_message_is_user_facing_not_a_stack_trace(self, client):
        message = client.get("/api/hotspots?days=3").json()["status"]["firms_message"]
        assert "Traceback" not in message
        assert len(message) > 10

    def test_rejects_malformed_bbox(self, client):
        response = client.get("/api/hotspots?bbox=not,a,valid,bbox")
        assert response.status_code in {400, 422}

    def test_rejects_out_of_range_days(self, client):
        assert client.get("/api/hotspots?days=99").status_code == 422
        assert client.get("/api/hotspots?days=0").status_code == 422

    def test_rejects_bad_mode(self, client):
        assert client.get("/api/hotspots?mode=nonsense").status_code == 422

    def test_confidence_filter_is_validated(self, client):
        assert client.get("/api/hotspots?min_confidence=5").status_code == 422

    def test_summary_counts_are_consistent(self, client):
        body = client.get("/api/hotspots?days=3").json()
        summary = body["summary"]
        assert summary["total_events"] == len(body["events"]) or body["total_matching"] >= len(
            body["events"]
        )
        assert sum(summary["by_class"].values()) == summary["total_events"]

    def test_unknown_event_id_is_404(self, client):
        assert client.get("/api/hotspots/EVT-DOESNOTEXIST").status_code == 404


class TestDashboardAndExport:
    def test_summary_endpoint(self, client):
        body = client.get("/api/dashboard/summary?days=3").json()
        assert "summary" in body and "timeline" in body

    def test_geojson_is_valid_shape(self, client):
        body = client.get("/api/export/geojson?days=3").json()
        assert body["type"] == "FeatureCollection"
        assert isinstance(body["features"], list)
        assert "disclaimer" in body["metadata"]

    def test_geojson_features_are_well_formed(self, client):
        for feature in client.get("/api/export/geojson?days=3").json()["features"][:5]:
            assert feature["geometry"]["type"] == "Point"
            assert len(feature["geometry"]["coordinates"]) == 2

    def test_json_export_preserves_canonical_evidence(self, client):
        body = client.get("/api/export/json?days=3").json()
        assert body["schema_version"] == "1.0"
        assert body["record_count"] == len(body["events"])
        assert body["provenance"]["source"]
        if body["events"]:
            assert "evidence" in body["events"][0]
            assert "model" in body["events"][0]

    def test_csv_export_has_a_header(self, client):
        response = client.get("/api/export/csv?days=3")
        assert response.status_code == 200
        assert response.text.splitlines()[0].startswith("event_id,")


class TestClassifyEndpoint:
    def test_classifies_an_arbitrary_point(self, client):
        response = client.post(
            "/api/classify",
            json={"latitude": 22.3, "longitude": 69.8, "frp_mw": 25.0, "brightness_k": 340.0},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["classification"]["label"] in ALL_CLASSES
        assert 0.0 <= body["classification"]["confidence"] <= 1.0
        assert "disclaimer" in body

    @pytest.mark.parametrize(
        "payload",
        [
            {"latitude": 999, "longitude": 69.8},
            {"latitude": 22.3, "longitude": 999},
            {"latitude": 22.3},
            {"latitude": 22.3, "longitude": 69.8, "frp_mw": -5},
        ],
    )
    def test_rejects_invalid_input(self, client, payload):
        assert client.post("/api/classify", json=payload).status_code == 422

    def test_probabilities_are_a_distribution(self, client):
        body = client.post(
            "/api/classify", json={"latitude": 22.3, "longitude": 69.8, "frp_mw": 25.0}
        ).json()
        total = sum(body["probabilities"].values())
        # Either a real distribution, or all-zero when no model is loaded.
        assert total == pytest.approx(1.0, abs=0.02) or total == 0.0


class TestFacilitiesEndpoint:
    def test_nearby_validates_coordinates(self, client):
        assert client.get("/api/facilities/nearby?lat=999&lon=69.8").status_code == 422

    def test_nearby_returns_a_shape_even_with_no_data(self, client):
        body = client.get("/api/facilities/nearby?lat=22.3&lon=69.8&radius_km=10").json()
        assert "facilities" in body and "count" in body


class TestRootAndDocs:
    def test_root(self, client):
        assert client.get("/").json()["name"] == "FIRETRACE"

    def test_openapi_schema_builds(self, client):
        assert client.get("/openapi.json").status_code == 200

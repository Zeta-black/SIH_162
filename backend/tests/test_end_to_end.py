"""End-to-end: a real historical detection through the whole backend workflow.

This is deliberately NOT a UI test. It drives the actual pipeline —
ingestion, schema validation, deduplication, geospatial enrichment, feature
extraction, ML inference, risk scoring, clustering, the alert rule, persistence
and the HTTP API — and asserts on what each stage genuinely produced.

The point is to be able to say "the pipeline works" and have something behind
the claim other than having read the code.

Every case here comes from the frozen snapshot of real NASA FIRMS observations.
No fixture invents a detection, a date, a coordinate or a fire.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import incidents as inc
from app.services import replay as replay_service
from app.services.snapshot import snapshot_available


pytestmark = pytest.mark.skipif(
    not snapshot_available(),
    reason="no historical snapshot in this checkout",
)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    """Every test gets its own database.

    Two reasons this is not optional. First, the project's conftest states that
    tests must never touch the real store, and these tests persist incidents.
    Second, incident state is a state machine: without isolation a test that
    resolves an incident silently changes what the next test starts from, and
    the failure shows up somewhere else entirely.
    """
    import app.store.db as db

    previous = db._store
    db._store = db.EventStore(tmp_path / "e2e.sqlite3")
    try:
        yield db._store
    finally:
        db._store = previous


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def catalogue():
    return replay_service.build_catalogue()


@pytest.fixture(scope="module")
def any_case(catalogue):
    assert catalogue["cases"], "catalogue is empty"
    return catalogue["cases"][0]


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
class TestCatalogue:
    def test_catalogue_is_built_from_real_data(self, catalogue):
        assert catalogue["available"] is True
        assert catalogue["case_count"] >= 20, "the brief asks for 20-30 replayable cases"
        assert catalogue["source"]["detections_available"] > 0

    def test_every_case_carries_full_provenance(self, catalogue):
        required = [
            "event_id", "date", "time_utc", "latitude", "longitude",
            "source", "satellite", "confidence", "frp_mw", "detection_count",
            "ground_truth", "raw_source_reference",
        ]
        for case in catalogue["cases"]:
            for field in required:
                assert field in case, f"{case['case_id']} is missing {field}"

    def test_no_case_claims_a_confirmed_fire(self, catalogue):
        """Ground truth is unknown for every FIRMS pixel in this dataset."""
        for case in catalogue["cases"]:
            assert case["ground_truth"] == "UNKNOWN"

    def test_coordinates_and_dates_are_real_not_placeholder(self, catalogue):
        for case in catalogue["cases"]:
            assert -90 <= case["latitude"] <= 90
            assert -180 <= case["longitude"] <= 180
            # A placeholder would be 0,0 or an obviously round number.
            assert (case["latitude"], case["longitude"]) != (0.0, 0.0)
            assert len(case["date"]) == 10 and case["date"][4] == "-"

    def test_scenarios_only_exist_where_data_supports_them(self, catalogue):
        """Every listed scenario must have at least one genuine case behind it."""
        present = {c["scenario"] for c in catalogue["cases"]}
        assert present, "no scenarios at all"
        # Whatever is present must be a defined scenario, not an invented label.
        defined = {s["id"] for s in catalogue["scenarios"]}
        assert present <= defined


# ---------------------------------------------------------------------------
# The replay itself
# ---------------------------------------------------------------------------
class TestReplayPipeline:
    def test_replay_executes_every_stage(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        names = [s["stage"] for s in result["stages"]]
        assert names == replay_service.STAGES, f"stages ran out of order: {names}"
        assert all(s["ok"] for s in result["stages"])

    def test_each_stage_reports_real_work(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        for stage in result["stages"]:
            # A stage that did nothing would have no detail to report.
            assert stage["detail"], f"{stage['stage']} reported no detail"
            assert stage["duration_ms"] >= 0.0

    def test_timestamps_are_generated_not_hardcoded(self, any_case):
        """Two runs must produce different timestamps."""
        first = replay_service.replay(any_case["case_id"], persist=False)
        second = replay_service.replay(any_case["case_id"], persist=False)
        assert first["run"]["started_at"] != second["run"]["started_at"]
        assert first["stages"][0]["started_at"] != second["stages"][0]["started_at"]

    def test_validation_stage_actually_validates(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        counts = result["counts"]
        assert counts["validated"] > 0
        assert counts["validated"] + counts["rejected"] == counts["ingested"]

    def test_deduplication_leaves_unique_detections(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        counts = result["counts"]
        assert counts["classified"] == counts["validated"] - counts["duplicates_removed"]

    def test_clustering_produces_at_least_one_event(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        assert result["counts"]["fire_events"] >= 1
        assert result["result"]["formed_event"] is True

    def test_ml_inference_ran_or_said_why_not(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        ml = next(s for s in result["stages"] if s["stage"] == "ML_INFERENCE")
        # Either it scored detections, or it said plainly that no model is loaded.
        assert "scored" in ml["detail"] or "NO MODEL LOADED" in ml["detail"]

    def test_alert_level_is_computed_not_asserted(self, catalogue):
        """Different cases must produce different alert outcomes.

        If the alert were hardcoded, every replay would return the same thing.
        """
        levels = set()
        for case in catalogue["cases"][:12]:
            result = replay_service.replay(case["case_id"], persist=False)
            levels.add(result["result"].get("alert_level"))
        assert len(levels) > 1, f"every case produced the same alert level: {levels}"

    def test_priority_is_explained_by_its_components(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        explanation = result["result"].get("priority_explanation")
        assert explanation, "priority was reported with no explanation"
        assert explanation["components"], "no contributing factors given"
        for name, value in explanation["components"].items():
            assert 0.0 <= value <= 1.0, f"component {name} is out of bounds: {value}"

    def test_result_never_claims_ground_truth(self, any_case):
        result = replay_service.replay(any_case["case_id"], persist=False)
        assert result["result"]["ground_truth"] == "UNKNOWN"
        assert "not a verified incident report" in result["disclaimer"]

    def test_unknown_case_is_rejected(self):
        with pytest.raises(KeyError):
            replay_service.replay("NO_SUCH_SCENARIO::EVT-DOESNOTEXIST", persist=False)


# ---------------------------------------------------------------------------
# Latency instrumentation
# ---------------------------------------------------------------------------
class TestLatency:
    def test_platform_stages_are_measured_individually(self, any_case):
        latency = replay_service.replay(any_case["case_id"], persist=False)["latency"]
        platform = latency["platform"]
        for key in (
            "ingestion_ms", "validation_ms", "enrichment_ms", "feature_extraction_ms",
            "ml_inference_ms", "risk_priority_ms", "clustering_ms", "alert_generation_ms",
        ):
            assert key in platform
            assert platform[key] >= 0.0

    def test_end_to_end_is_at_least_the_sum_of_its_stages(self, any_case):
        latency = replay_service.replay(any_case["case_id"], persist=False)["latency"]
        total = latency["end_to_end_platform_ms"]
        parts = sum(latency["platform"].values())
        assert total >= parts * 0.95, "end-to-end is smaller than its own stages"

    def test_source_latency_is_kept_separate_and_caveated(self, any_case):
        """NASA's latency must never be blended into ours."""
        latency = replay_service.replay(any_case["case_id"], persist=False)["latency"]
        assert "source" in latency and "platform" in latency
        caveat = latency["source"]["caveat"].lower()
        # The caveat must disclaim the figure one way or another: an upper bound
        # on a live record, or "not meaningful" on an archival snapshot record
        # whose capture time is months after the observation.
        assert any(
            phrase in caveat
            for phrase in ("upper bound", "not meaningful", "cannot be computed")
        ), f"source latency is not disclaimed: {caveat}"
        assert "not our platform latency" in caveat

    def test_measured_durations_vary_between_runs(self, any_case):
        """Hardcoded timings would be identical every time."""
        a = replay_service.replay(any_case["case_id"], persist=False)["latency"]
        b = replay_service.replay(any_case["case_id"], persist=False)["latency"]
        assert a["end_to_end_platform_ms"] != b["end_to_end_platform_ms"]


# ---------------------------------------------------------------------------
# Persistence and duplicate-alert protection
# ---------------------------------------------------------------------------
class TestPersistenceAndDuplicates:
    @pytest.fixture
    def alerting_case(self, catalogue):
        """A case that genuinely raises an alert, found by running the rule."""
        for case in catalogue["cases"]:
            result = replay_service.replay(case["case_id"], persist=False)
            if result["result"].get("alert_raised"):
                return case, result["result"]["event_id"]
        pytest.skip("no case in the catalogue raises an alert")

    def test_replay_persists_the_incident(self, alerting_case):
        case, event_id = alerting_case
        replay_service.replay(case["case_id"], persist=True)
        incident = inc.get_incident(event_id)
        assert incident is not None, "an alerting replay did not persist an incident"
        assert incident["status"] == inc.NEW

    def test_the_same_event_replayed_twice_raises_one_alert(self, alerting_case):
        """The duplicate-alert test the brief asks for."""
        case, event_id = alerting_case
        first = replay_service.replay(case["case_id"], persist=True)["persistence"]
        second = replay_service.replay(case["case_id"], persist=True)["persistence"]

        # The second run must not create a new incident for the same event.
        assert second["created"] == 0, (
            "replaying the same event created a second incident — an operator "
            "would be paged twice for one fire"
        )
        assert second["updated"] >= 1

    def test_a_second_replay_does_not_reset_the_workflow(self, alerting_case):
        case, event_id = alerting_case
        replay_service.replay(case["case_id"], persist=True)
        inc.act(event_id, "acknowledge", actor="e2e-test")
        replay_service.replay(case["case_id"], persist=True)
        assert inc.get_incident(event_id)["status"] == inc.ACKNOWLEDGED

    def test_re_alert_after_closure_is_logged_not_silent(self, alerting_case):
        """A resolved incident that alerts again must leave a trace."""
        case, event_id = alerting_case
        replay_service.replay(case["case_id"], persist=True)
        inc.act(event_id, "acknowledge", actor="e2e-test")
        inc.act(event_id, "resolve", actor="e2e-test")

        before = len(inc.get_incident(event_id)["actions"])
        result = replay_service.replay(case["case_id"], persist=True)["persistence"]
        after = inc.get_incident(event_id)

        assert result["re_alerted"] >= 1
        assert len(after["actions"]) > before, "the re-alert was not written to the log"
        assert after["status"] == inc.RESOLVED, "a re-alert must not silently reopen"
        assert any(a["action"] == "re-alert" for a in after["actions"])


# ---------------------------------------------------------------------------
# The full operator workflow, persisted
# ---------------------------------------------------------------------------
class TestAlertWorkflow:
    def test_new_to_resolved_persists_at_every_step(self, catalogue, client):
        """NEW -> ACKNOWLEDGED -> ASSIGNED -> MONITORING -> RESOLVED.

        Each step is re-read from the API, so a state that only existed in
        memory would fail here.
        """
        event_id = None
        for case in catalogue["cases"]:
            result = replay_service.replay(case["case_id"], persist=True)
            if result["result"].get("alert_raised"):
                event_id = result["result"]["event_id"]
                break
        if event_id is None:
            pytest.skip("no alerting case available")

        def post(action: str, **kw) -> dict:
            r = client.post(f"/api/incidents/{event_id}/action", json={"action": action, **kw})
            assert r.status_code == 200, r.text
            # Re-read rather than trusting the response.
            return client.get(f"/api/incidents/{event_id}").json()

        assert client.get(f"/api/incidents/{event_id}").json()["status"] == inc.NEW
        assert post("acknowledge", actor="controller")["status"] == inc.ACKNOWLEDGED

        assigned = post("assign", actor="controller", note="Range Team 3")
        assert assigned["assigned_to"] == "Range Team 3"

        assert post("monitor", actor="controller")["status"] == inc.MONITORING
        assert post("resolve", actor="controller")["status"] == inc.RESOLVED

        final = client.get(f"/api/incidents/{event_id}").json()
        actions = [a["action"] for a in final["actions"]]
        assert "assign" in actions and "resolve" in actions
        assert final["actions"][0]["actor"] == "system", "the raise should be system-logged"

    def test_illegal_transition_is_rejected_by_the_api(self, catalogue, client):
        event_id = None
        for case in catalogue["cases"]:
            result = replay_service.replay(case["case_id"], persist=True)
            if result["result"].get("alert_raised"):
                event_id = result["result"]["event_id"]
                break
        if event_id is None:
            pytest.skip("no alerting case available")

        # A fresh incident is NEW, and resolving without acknowledging is illegal.
        assert client.get(f"/api/incidents/{event_id}").json()["status"] == inc.NEW
        r = client.post(f"/api/incidents/{event_id}/action", json={"action": "resolve"})
        assert r.status_code == 409, "the API allowed a resolve that skipped acknowledgement"


# ---------------------------------------------------------------------------
# API exposure
# ---------------------------------------------------------------------------
class TestApiExposure:
    def test_catalogue_endpoint(self, client):
        r = client.get("/api/replay/catalogue")
        assert r.status_code == 200
        assert r.json()["case_count"] >= 20

    def test_case_endpoint_returns_source_record(self, client, any_case):
        r = client.get(f"/api/replay/case/{any_case['case_id']}")
        assert r.status_code == 200
        assert r.json()["event_id"] == any_case["event_id"]

    def test_run_endpoint_executes_the_pipeline(self, client, any_case):
        r = client.post(f"/api/replay/run/{any_case['case_id']}?persist=false")
        assert r.status_code == 200
        body = r.json()
        assert len(body["stages"]) == len(replay_service.STAGES)
        assert body["result"]["ground_truth"] == "UNKNOWN"

    def test_unknown_case_returns_404(self, client):
        r = client.post("/api/replay/run/NOPE::EVT-NOTHING?persist=false")
        assert r.status_code == 404

    def test_alert_rule_publishes_its_dedup_contract(self, client):
        rule = client.get("/api/incidents").json()["alert_rule"]
        assert "deduplication" in rule
        assert "cooldown" in rule
        assert "escalation" in rule

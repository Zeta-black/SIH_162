"""The main screen's contract: status vocabulary, verdicts and provenance.

Everything a user reads on the map comes from this layer, so these tests guard
the claims themselves, not just the plumbing. Several of them encode specific
defects found during the round-2 rebuild and are named after what went wrong.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.events import FireEvent
from app.services.verdict import (
    display_status,
    evidence_completeness,
    missing_evidence,
    verdict_sentence,
    why_bullets,
)
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    DISPLAY_STATUSES,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    NATURAL_FIRE,
    STATUS_COLORS,
    STATUS_LABELS,
    STATUS_MEANINGS,
    STATUS_NEEDS_ATTENTION,
    STATUS_NORMAL,
    STATUS_NOT_SURE,
    STATUS_WATCH,
    UNKNOWN,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(monkeypatch):
    """A TestClient with the live feed forced to fail.

    Same shape as the fixture in test_store_api.py: FIRMS is stubbed to raise,
    so the snapshot path is exercised and no test ever touches the network. The
    per-event work is bounded for the same reason it is there — explaining every
    event in the full snapshot walks the whole forest and makes the suite crawl.
    """
    from app.main import app
    from app.services import pipeline
    from app.services.firms import FirmsError
    from fastapi.testclient import TestClient

    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 80)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 8)

    def fail_firms(*args, **kwargs):
        raise FirmsError("Simulated NASA outage", kind="unavailable")

    monkeypatch.setattr("app.services.firms.FirmsClient.fetch_area", fail_firms)
    monkeypatch.setattr("app.services.osm.fetch_facilities", lambda *a, **k: ([], "unavailable"))
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))

    with TestClient(app) as c:
        yield c

    pipeline.clear_cache()


def make_event(**overrides) -> FireEvent:
    """A deliberately ordinary event; each test perturbs only what it is about."""
    base = dict(
        event_id="FE-TEST-0001",
        latitude=21.5,
        longitude=86.7,
        detection_count=3,
        first_detected=NOW - timedelta(minutes=20),
        last_detected=NOW,
        duration_hours=0.33,
        label=INDUSTRIAL_FIRE,
        label_display="Potential Industrial Fire",
        label_confidence=0.91,
        label_agreement=1.0,
        class_distribution={INDUSTRIAL_FIRE: 3},
        priority_score=0.81,
        priority_level="HIGH",
        frp_total_mw=65.4,
        frp_max_mw=15.4,
        brightness_max_k=367.0,
        satellites=["N20"],
        products=["VIIRS_NOAA20_SP"],
        spread_km=0.85,
        distinct_passes=2,
        nearest_facility_name="Test Refinery",
        nearest_facility_km=0.25,
        land_cover="Industrial / built-up",
        persistent=False,
        distinct_days=0,
        history_available=True,
        risk_factors=[
            "3 satellite detections over 20 min",
            "Confirmed across 2 separate satellite passes",
            "On the footprint of Test Refinery (250 m)",
            "Peak radiative power 15 MW",
            "Land cover: Industrial / built-up",
        ],
        detection_ids=["EVT-1", "EVT-2", "EVT-3"],
        lead_detection_id="EVT-1",
    )
    base.update(overrides)
    return FireEvent(**base)


# ---------------------------------------------------------------- vocabulary
class TestStatusVocabulary:
    def test_exactly_four_display_statuses(self):
        """The main screen shows four words. Adding a fifth is a design change."""
        assert len(DISPLAY_STATUSES) == 4
        assert set(DISPLAY_STATUSES) == {
            STATUS_NEEDS_ATTENTION,
            STATUS_WATCH,
            STATUS_NORMAL,
            STATUS_NOT_SURE,
        }

    def test_every_status_has_label_meaning_and_colour(self):
        for key in DISPLAY_STATUSES:
            assert STATUS_LABELS[key]
            assert STATUS_MEANINGS[key]
            assert STATUS_COLORS[key].startswith("#")

    def test_display_status_always_returns_a_known_status(self):
        for label in (INDUSTRIAL_FIRE, GAS_FLARE_OR_INDUSTRIAL_HEAT, AGRICULTURAL_BURNING,
                      NATURAL_FIRE, UNKNOWN):
            for level in ("HIGH", "MEDIUM", "LOW"):
                event = make_event(label=label, priority_level=level)
                assert display_status(event) in DISPLAY_STATUSES


class TestStatusMapping:
    def test_high_priority_industrial_needs_attention(self):
        assert display_status(make_event()) == STATUS_NEEDS_ATTENTION

    def test_abstention_wins_over_priority(self):
        """An abstained model must not be reported as a confident alarm.

        If FIRETRACE declined to name a class, it does not then assert the event
        needs attention. "Not sure" is the honest output; the priority score
        still orders it in the queue.
        """
        event = make_event(label=UNKNOWN, priority_level="HIGH")
        assert display_status(event) == STATUS_NOT_SURE

    def test_persistent_flare_is_normal_not_an_incident(self):
        """The core discrimination: a flare that burns daily is this site's normal."""
        event = make_event(
            label=GAS_FLARE_OR_INDUSTRIAL_HEAT,
            priority_level="MEDIUM",
            persistent=True,
            distinct_days=22,
        )
        assert display_status(event) == STATUS_NORMAL

    def test_episodic_industrial_at_medium_priority_is_watch(self):
        event = make_event(priority_level="MEDIUM", persistent=False)
        assert display_status(event) == STATUS_WATCH

    def test_vegetation_fire_clear_of_industry_is_normal(self):
        event = make_event(
            label=NATURAL_FIRE,
            priority_level="LOW",
            nearest_facility_name=None,
            nearest_facility_km=None,
        )
        assert display_status(event) == STATUS_NORMAL


# ------------------------------------------------------------------ verdicts
class TestVerdictSentence:
    def test_verdict_is_a_plain_sentence(self):
        text = verdict_sentence(make_event())
        assert text.endswith(".")
        assert len(text.split()) <= 40

    def test_verdict_names_the_facility_when_on_site(self):
        assert "Test Refinery" in verdict_sentence(make_event())

    def test_does_not_claim_episodic_when_the_source_repeats(self):
        """Regression: the Reliance Refinery contradiction.

        Four sites in the demo archive were labelled INDUSTRIAL_FIRE with 2-3
        distinct prior days. The verdict asserted "episodic signature, rather
        than routine operation" directly above an evidence line reading
        "detected on 3 separate days". A judge reads both at once.
        """
        event = make_event(distinct_days=3, persistent=False)
        text = verdict_sentence(event)
        assert "episodic" not in text.lower()
        assert "3 separate days" in text

    def test_abstained_verdict_says_it_is_not_committing(self):
        text = verdict_sentence(make_event(label=UNKNOWN, priority_level="MEDIUM"))
        assert "not committing" in text.lower()

    def test_persistent_flare_verdict_calls_it_routine(self):
        text = verdict_sentence(
            make_event(
                label=GAS_FLARE_OR_INDUSTRIAL_HEAT, persistent=True, distinct_days=22
            )
        )
        assert "routine" in text.lower()
        assert "22" in text

    def test_no_facility_means_no_facility_claim(self):
        text = verdict_sentence(
            make_event(
                label=AGRICULTURAL_BURNING,
                priority_level="LOW",
                nearest_facility_name=None,
                nearest_facility_km=None,
            )
        )
        assert "clear of mapped industry" in text


# -------------------------------------------------------------- why bullets
class TestWhyBullets:
    def test_at_most_three(self):
        assert len(why_bullets(make_event())) <= 3

    def test_every_bullet_came_from_the_event(self):
        """No bullet may be invented by the display layer."""
        event = make_event()
        for line in why_bullets(event):
            assert line in event.risk_factors

    def test_the_most_decisive_line_is_kept(self):
        """Being on a facility footprint outranks a generic detection count."""
        bullets = why_bullets(make_event())
        assert any("On the footprint of" in b for b in bullets)

    def test_no_bullets_when_the_event_has_no_measured_reasons(self):
        assert why_bullets(make_event(risk_factors=[])) == []


# ---------------------------------------------------------- missing evidence
class TestMissingEvidence:
    def test_optical_confirmation_is_always_declared_unavailable(self):
        """It is not wired up. Silence would let a reader assume it was checked."""
        assert any("Optical confirmation" in m for m in missing_evidence(make_event()))

    def test_unmapped_land_cover_is_missing_not_supporting(self):
        gaps = missing_evidence(make_event(land_cover="Not mapped in OpenStreetMap"))
        assert any("Land cover" in g for g in gaps)

    def test_no_history_loaded_differs_from_no_prior_detection(self):
        """Regression guard for the abnormality defect in docs/BASELINE.md D1.

        "We watched and saw nothing" and "we have no data for this place" are
        different statements, and collapsing them is what let 70% of events be
        scored maximally abnormal.
        """
        no_history = missing_evidence(make_event(history_available=False, distinct_days=0))
        watched = missing_evidence(make_event(history_available=True, distinct_days=0))

        assert any("No detection history is loaded" in g for g in no_history)
        assert not any("No detection history is loaded" in g for g in watched)
        assert any("No earlier detection" in g for g in watched)

    def test_single_pass_is_reported_as_uncorroborated(self):
        gaps = missing_evidence(make_event(distinct_passes=1))
        assert any("not yet corroborated" in g for g in gaps)


class TestEvidenceCompleteness:
    def test_is_a_count_not_a_score(self):
        result = evidence_completeness(make_event())
        assert result["available"] <= result["total"]
        assert result["total"] == 4
        assert "not a confidence" in result["note"]

    def test_counts_only_checks_that_succeeded(self):
        bare = evidence_completeness(
            make_event(
                nearest_facility_km=None,
                land_cover="Not mapped in OpenStreetMap",
                distinct_passes=1,
                distinct_days=0,
            )
        )
        assert bare["available"] == 0


# ------------------------------------------------------------------- the API
class TestMapEndpoint:
    def test_returns_the_whole_screen_in_one_request(self, client):
        r = client.get("/api/map", params={"mode": "demo", "days": 1})
        assert r.status_code == 200
        body = r.json()
        for key in ("provenance", "counts", "status_vocabulary", "window", "model",
                    "disclaimer", "sites"):
            assert key in body

    def test_counts_cover_every_site(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        counts = body["counts"]
        total = sum(counts[k] for k in DISPLAY_STATUSES)
        assert total == counts["sites"]

    def test_demo_mode_is_labelled_replay_never_live(self, client):
        """A replay must never be able to present itself as live data."""
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        prov = body["provenance"]
        assert prov["state"] == "replay"
        assert prov["is_live"] is False
        assert "live" not in prov["label"].lower()

    def test_observation_and_retrieval_times_are_separate(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        assert body["provenance"]["retrieved_at"]
        site = body["sites"][0]
        assert site["observed_at"] != body["provenance"]["retrieved_at"]

    def test_model_score_is_never_called_a_probability(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        note = body["model"]["score_note"].lower()
        assert "uncalibrated" in note
        assert "not a probability" in note
        for site in body["sites"][:20]:
            assert "model_score" in site
            assert "probability" not in site

    def test_sites_are_ordered_for_triage(self, client):
        """Needs attention first, then unresolved. A queue, not a data dump."""
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        statuses = [s["status"] for s in body["sites"]]
        if STATUS_NEEDS_ATTENTION in statuses and STATUS_NORMAL in statuses:
            assert statuses.index(STATUS_NEEDS_ATTENTION) < statuses.index(STATUS_NORMAL)

    def test_every_site_carries_its_own_verdict_and_reasons(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        for site in body["sites"][:25]:
            assert site["verdict"].endswith(".")
            assert isinstance(site["why"], list)
            assert len(site["why"]) <= 3
            assert site["missing"]

    def test_unnamed_sites_get_a_distinct_identity(self, client):
        """150 rows all reading "Unclassified" told an operator nothing."""
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        unnamed = [s for s in body["sites"] if not s["nearest_facility_name"]]
        if len(unnamed) > 5:
            titles = {s["title"] for s in unnamed}
            assert len(titles) > len(unnamed) * 0.5

    def test_abstained_sites_are_reported_as_not_sure(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        for site in body["sites"]:
            if site["abstained"]:
                assert site["status"] == STATUS_NOT_SURE

    def test_search_is_scoped_and_says_so(self, client):
        r = client.get("/api/map/search", params={"q": "refinery", "mode": "demo"})
        assert r.status_code == 200
        body = r.json()
        assert "results" in body
        for hit in body["results"]:
            assert hit["kind"] in ("site", "facility")
            assert hit["lat"] is not None

    def test_search_rejects_a_single_character(self, client):
        assert client.get("/api/map/search", params={"q": "r", "mode": "demo"}).status_code == 422

"""Abnormality must never be invented from missing history.

Regression suite for docs/BASELINE.md D1 and docs/MODEL_AUDIT.md section 4.

The defect: `abnormality()` returned `1.0 - persistence_ratio` whenever *any*
history was loaded globally, so a location with zero prior detections scored
1.0 — "maximally unusual". 351 of 500 detections (70%) carried exactly that,
every one of them with no prior detection at its location.

"We watched this place and it never lit up" and "we have no coverage of this
place" are different statements. These tests keep them apart.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.schemas import Classification, HotspotEvent, NearestFacility, RecurrenceResult
from app.services.priority import (
    MIN_DAYS_FOR_BASELINE,
    abnormality,
    compute_priority,
    formula_description,
)
from app.taxonomy import INDUSTRIAL_FIRE

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def recurrence(
    *,
    distinct_days: int,
    history_available: bool = True,
    persistence_ratio: float = 0.0,
    is_persistent: bool = False,
) -> RecurrenceResult:
    return RecurrenceResult(
        recurrence_count=distinct_days,
        distinct_days=distinct_days,
        recent_count_7d=0,
        first_seen=date(2026, 7, 1) if distinct_days else None,
        last_seen_before_event=date(2026, 9, 1) if distinct_days else None,
        persistence_ratio=persistence_ratio,
        nearby_density=0,
        is_persistent=is_persistent,
        window_days=60,
        radius_km=1.0,
        history_available=history_available,
    )


def hotspot() -> HotspotEvent:
    return HotspotEvent(
        event_id="EVT-TESTABNORM",
        latitude=21.1,
        longitude=72.64,
        acquisition_date=NOW.date(),
        acquisition_time="07:15",
        acquired_at=NOW,
        brightness_k=355.0,
        frp_mw=15.0,
        source_product="VIIRS_NOAA21_NRT",
        source_mode="snapshot",
        raw_source_reference="test",
        ingested_at=NOW,
    )


def classification() -> Classification:
    return Classification(
        label=INDUSTRIAL_FIRE,
        label_display="Potential Industrial Fire",
        description="test",
        confidence=0.9,
        confidence_level="HIGH",
        abstained=False,
        top_trained_label=INDUSTRIAL_FIRE,
    )


def facility() -> NearestFacility:
    return NearestFacility(
        facility_id="W1",
        name="Test Works",
        category="steel_metal",
        category_label="Steel / metal works",
        latitude=21.1,
        longitude=72.64,
        distance_km=0.25,
    )


# ------------------------------------------------------------- the function
class TestAbnormalityFunction:
    def test_no_prior_detection_is_not_assessed_rather_than_maximal(self):
        """The exact defect. 0 prior days must not mean 'maximally unusual'."""
        value, status = abnormality(recurrence(distinct_days=0))
        assert value is None
        assert status == "insufficient_history"

    def test_one_prior_day_is_still_too_little(self):
        value, status = abnormality(recurrence(distinct_days=1))
        assert value is None
        assert status == "insufficient_history"

    def test_no_history_loaded_is_its_own_status(self):
        value, status = abnormality(recurrence(distinct_days=0, history_available=False))
        assert value is None
        assert status == "no_history_loaded"

    def test_enough_history_is_assessed(self):
        value, status = abnormality(
            recurrence(distinct_days=MIN_DAYS_FOR_BASELINE, persistence_ratio=0.1)
        )
        assert status == "assessed"
        assert value == pytest.approx(0.9)

    def test_a_source_that_burns_constantly_is_not_abnormal(self):
        """The core discrimination: persistence means routine."""
        value, status = abnormality(
            recurrence(distinct_days=30, persistence_ratio=1.0, is_persistent=True)
        )
        assert status == "assessed"
        assert value == pytest.approx(0.0)

    @pytest.mark.parametrize("days", [0, 1, 2, 5, 30])
    def test_never_returns_a_value_without_saying_how_it_knows(self, days):
        value, status = abnormality(recurrence(distinct_days=days))
        assert status in ("assessed", "insufficient_history", "no_history_loaded")
        assert (value is None) == (status != "assessed")


# -------------------------------------------------------------- the scoring
class TestPriorityRenormalisation:
    def test_an_unassessable_component_is_excluded_not_guessed(self):
        result = compute_priority(
            hotspot(), classification(), facility(), recurrence(distinct_days=0), now=NOW
        )
        assert "abnormality" not in result.components
        assert "abnormality" in result.unassessed
        assert result.abnormality_score is None
        assert result.abnormality_status == "insufficient_history"

    def test_the_remaining_weights_are_renormalised_to_one(self):
        """A component we cannot measure must not quietly drag the score down."""
        result = compute_priority(
            hotspot(), classification(), facility(), recurrence(distinct_days=0), now=NOW
        )
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=0.001)
        assert set(result.weights) == set(result.components)

    def test_excluding_abnormality_does_not_act_as_a_zero(self):
        """Dropping the component must score higher than scoring it zero would.

        This is the whole point of renormalising: 'unknown' is not 'not unusual'.
        """
        unassessed = compute_priority(
            hotspot(), classification(), facility(), recurrence(distinct_days=0), now=NOW
        )
        scored_zero = compute_priority(
            hotspot(),
            classification(),
            facility(),
            recurrence(distinct_days=10, persistence_ratio=1.0),
            now=NOW,
        )
        assert unassessed.score > scored_zero.score

    def test_an_assessed_event_keeps_every_component(self):
        result = compute_priority(
            hotspot(),
            classification(),
            facility(),
            recurrence(distinct_days=8, persistence_ratio=0.2),
            now=NOW,
        )
        assert "abnormality" in result.components
        assert result.unassessed == []
        assert result.abnormality_score == 80
        assert result.abnormality_status == "assessed"

    def test_abnormality_score_is_zero_to_one_hundred_and_separate(self):
        """Never folded into the priority score; always its own field."""
        result = compute_priority(
            hotspot(),
            classification(),
            facility(),
            recurrence(distinct_days=10, persistence_ratio=0.75),
            now=NOW,
        )
        assert result.abnormality_score == 25
        assert 0 <= result.abnormality_score <= 100
        assert result.abnormality_score != result.score

    def test_the_score_stays_in_range_whatever_is_missing(self):
        for days in (0, 1, 2, 10):
            for loaded in (True, False):
                result = compute_priority(
                    hotspot(),
                    classification(),
                    facility(),
                    recurrence(distinct_days=days, history_available=loaded),
                    now=NOW,
                )
                assert 0.0 <= result.score <= 1.0


class TestPublishedFormulaMatchesBehaviour:
    def test_the_formula_description_admits_the_baseline_requirement(self):
        """A published formula that omits this would be misleading."""
        text = formula_description()["components"]["abnormality"]
        assert "not assessed" in text
        assert str(MIN_DAYS_FOR_BASELINE) in text

    def test_the_caveat_is_still_published(self):
        caveat = formula_description()["caveat"]
        assert "not validated" in caveat.lower()


# ------------------------------------------------------------------ the API
class TestAbnormalityOverTheApi:
    def test_most_sites_honestly_report_no_baseline(self, client):
        """83% of archive sites have no per-location history. Say so."""
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        statuses = {s["abnormality_status"] for s in body["sites"]}
        assert statuses <= {"assessed", "insufficient_history", "no_history_loaded"}

        unassessed = [s for s in body["sites"] if s["abnormality_score"] is None]
        assert unassessed, "expected sites with too little history to be honest about it"
        for site in unassessed:
            assert site["abnormality_status"] != "assessed"

    def test_an_assessed_score_is_backed_by_real_history(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        for site in body["sites"]:
            if site["abnormality_score"] is not None:
                assert site["distinct_days"] >= MIN_DAYS_FOR_BASELINE
                assert site["history_available"] is True

    def test_abnormality_is_separate_from_priority_everywhere(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        for site in body["sites"][:30]:
            assert "abnormality_score" in site
            assert "priority_score" in site
            assert "model_score" in site


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.main import app
    from app.services import livecache, pipeline
    from app.services.firms import FirmsError
    from fastapi.testclient import TestClient

    monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 80)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 6)

    def dead(*args, **kwargs):
        raise FirmsError("offline for tests", kind="unavailable")

    monkeypatch.setattr("app.services.firms.FirmsClient.fetch_area", dead)
    monkeypatch.setattr("app.services.osm.fetch_facilities", lambda *a, **k: ([], "unavailable"))
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))

    with TestClient(app) as c:
        yield c

    pipeline.clear_cache()

"""Labelling policy, priority score and land-cover provider behaviour."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import settings
from app.schemas import Classification
from app.services import landcover
from app.services.labeling import assign_label, policy_summary
from app.services.classifier import evidence_sufficiency
from app.services.landcover import (
    OsmLanduseProvider,
    SnapshotLanduseProvider,
    UnavailableProvider,
    build_provider,
)
from app.services.priority import (
    abnormality,
    compute_priority,
    formula_description,
    industrial_proximity,
    recency,
    thermal_severity,
)
from app.services.recurrence import HistoryIndex
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    LC_UNKNOWN,
    NATURAL_FIRE,
    UNKNOWN,
)


def make_classification(label: str, confidence: float) -> Classification:
    return Classification(
        label=label,
        label_display=label,
        description="",
        confidence=confidence,
        confidence_level="HIGH" if confidence >= 0.75 else "MEDIUM" if confidence >= 0.5 else "LOW",
        abstained=label == UNKNOWN,
        top_trained_label=label if label != UNKNOWN else INDUSTRIAL_FIRE,
    )


class TestLabellingPolicy:
    def test_persistent_high_heat_facility_is_a_flare(
        self, event, nearest_facility, land_cover_industrial, history_events
    ):
        rec = HistoryIndex(history_events).compute(event)
        decision = assign_label(event, nearest_facility, land_cover_industrial, rec)
        assert decision.label == GAS_FLARE_OR_INDUSTRIAL_HEAT
        assert decision.rule.startswith("R1")

    def test_episodic_onsite_strong_signal_is_an_industrial_fire(
        self, event_factory, nearest_facility, land_cover_industrial
    ):
        event = event_factory(frp=45.0)
        # One prior day only: an episode, not a routine repeat.
        prior = [event_factory(event_id="EVT-P1", acq_date=event.acquisition_date - timedelta(days=1))]
        rec = HistoryIndex(prior).compute(event)
        decision = assign_label(event, nearest_facility, land_cover_industrial, rec)
        assert decision.label == INDUSTRIAL_FIRE

    def test_cropland_clear_of_industry_in_season_is_agricultural(
        self, event_factory, land_cover_cropland
    ):
        event = event_factory(acq_date=date(2025, 11, 5), frp=6.0)
        rec = HistoryIndex([]).compute(event)
        decision = assign_label(event, None, land_cover_cropland, rec)
        assert decision.label == AGRICULTURAL_BURNING

    def test_forest_clear_of_industry_is_natural(self, event, land_cover_unknown):
        from app.schemas import LandCoverResult

        forest = LandCoverResult(
            category="forest_vegetation",
            label="Forest / vegetation",
            provider="osm_landuse",
            source_note="test",
        )
        rec = HistoryIndex([]).compute(event)
        decision = assign_label(event, None, forest, rec)
        assert decision.label == NATURAL_FIRE

    def test_ambiguous_evidence_is_left_unlabelled(self, event, land_cover_unknown):
        """The policy must refuse rather than guess. This is the whole point."""
        rec = HistoryIndex([]).compute(event)
        decision = assign_label(event, None, land_cover_unknown, rec)
        assert decision.label is None
        assert decision.rule == "R0_ambiguous"

    def test_every_decision_carries_a_rule_and_rationale(
        self, event, nearest_facility, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        decision = assign_label(event, nearest_facility, land_cover_industrial, rec)
        assert decision.rule
        assert decision.rationale

    def test_policy_summary_declares_it_is_not_ground_truth(self):
        summary = policy_summary()
        assert summary["ground_truth"] is False
        assert "not verified" in summary["note"].lower()


class TestThermalSeverity:
    def test_monotonic_in_frp(self, event_factory):
        low = thermal_severity(event_factory(frp=1.0))
        mid = thermal_severity(event_factory(frp=20.0))
        high = thermal_severity(event_factory(frp=200.0))
        assert low < mid < high

    def test_bounded(self, event_factory):
        assert 0.0 <= thermal_severity(event_factory(frp=0.0)) <= 1.0
        assert 0.0 <= thermal_severity(event_factory(frp=1e6)) <= 1.0

    def test_missing_frp_falls_back_to_brightness(self, event_factory):
        value = thermal_severity(event_factory(frp=None, brightness=380.0))
        assert 0.0 < value <= 1.0

    def test_missing_everything_is_neutral_not_zero(self, event_factory):
        """No data is not evidence of low severity."""
        assert thermal_severity(event_factory(frp=None, brightness=None)) > 0.0


class TestProximityAndAbnormality:
    def test_onsite_scores_near_one(self, nearest_facility):
        assert industrial_proximity(nearest_facility) > 0.95

    def test_no_facility_scores_zero(self):
        assert industrial_proximity(None) == 0.0

    def test_persistent_source_is_less_abnormal(self, event, history_events):
        persistent = HistoryIndex(history_events).compute(event)
        novel = HistoryIndex([]).compute(event)
        # A flare that burns daily should NOT outrank a brand-new hot spot.
        assert abnormality(persistent) < abnormality(novel)

    def test_no_history_is_neutral(self, event):
        assert abnormality(HistoryIndex([]).compute(event)) == 0.5


class TestRecency:
    def test_recent_detection_scores_high(self, event_factory):
        now = datetime.now(timezone.utc)
        fresh = event_factory(acq_date=now.date())
        assert recency(fresh, now) > 0.6

    def test_old_detection_decays(self, event_factory):
        now = datetime.now(timezone.utc)
        old = event_factory(acq_date=(now - timedelta(days=30)).date())
        assert recency(old, now) < 0.05


class TestPriorityScore:
    def test_bounded_zero_to_one(self, event, nearest_facility, history_events):
        rec = HistoryIndex(history_events).compute(event)
        for label in [INDUSTRIAL_FIRE, AGRICULTURAL_BURNING, UNKNOWN]:
            result = compute_priority(event, make_classification(label, 0.8), nearest_facility, rec)
            assert 0.0 <= result.score <= 1.0

    def test_industrial_fire_outranks_agricultural(self, event, nearest_facility, history_events):
        rec = HistoryIndex(history_events).compute(event)
        industrial = compute_priority(
            event, make_classification(INDUSTRIAL_FIRE, 0.8), nearest_facility, rec
        )
        agricultural = compute_priority(
            event, make_classification(AGRICULTURAL_BURNING, 0.8), nearest_facility, rec
        )
        assert industrial.score > agricultural.score

    def test_components_and_weights_are_returned(self, event, nearest_facility, history_events):
        rec = HistoryIndex(history_events).compute(event)
        result = compute_priority(event, make_classification(INDUSTRIAL_FIRE, 0.8), nearest_facility, rec)
        assert set(result.components) == set(result.weights)
        assert all(0.0 <= v <= 1.0 for v in result.components.values())

    def test_weights_normalise_to_one(self, event, nearest_facility, history_events):
        rec = HistoryIndex(history_events).compute(event)
        result = compute_priority(event, make_classification(INDUSTRIAL_FIRE, 0.8), nearest_facility, rec)
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-3)

    def test_score_matches_its_own_stated_formula(self, event, nearest_facility, history_events):
        """The published breakdown must actually reproduce the score."""
        rec = HistoryIndex(history_events).compute(event)
        result = compute_priority(event, make_classification(INDUSTRIAL_FIRE, 0.8), nearest_facility, rec)
        recomputed = sum(result.components[k] * result.weights[k] for k in result.components)
        assert recomputed == pytest.approx(result.score, abs=0.01)

    def test_level_matches_thresholds(self, event, nearest_facility, history_events):
        rec = HistoryIndex(history_events).compute(event)
        result = compute_priority(event, make_classification(INDUSTRIAL_FIRE, 0.9), nearest_facility, rec)
        if result.score >= settings.priority_high_threshold:
            assert result.level == "HIGH"
        elif result.score >= settings.priority_medium_threshold:
            assert result.level == "MEDIUM"
        else:
            assert result.level == "LOW"

    def test_formula_is_documented_with_a_caveat(self):
        doc = formula_description()
        assert "caveat" in doc
        assert "not" in doc["caveat"].lower()


class TestLandCoverProviders:
    def test_polygon_hit(self, square_polygon):
        result = OsmLanduseProvider([square_polygon]).lookup(22.05, 69.05)
        assert result.category == "industrial_builtup"
        assert result.matched_osm_tag == "landuse=industrial"

    def test_polygon_miss_returns_unknown_not_a_guess(self, square_polygon):
        result = OsmLanduseProvider([square_polygon]).lookup(30.0, 76.0)
        assert result.category == LC_UNKNOWN
        assert result.provider == "unavailable"

    def test_smallest_polygon_wins(self, square_polygon):
        from app.services.osm import LandusePolygon

        big = LandusePolygon(
            category="forest_vegetation",
            tag="natural=wood",
            ring=[(21.0, 68.0), (21.0, 70.0), (23.0, 70.0), (23.0, 68.0), (21.0, 68.0)],
            min_lat=21.0, min_lon=68.0, max_lat=23.0, max_lon=70.0, area_deg2=4.0,
        )
        # The small industrial polygon sits inside the big wood; specific wins.
        result = OsmLanduseProvider([big, square_polygon]).lookup(22.05, 69.05)
        assert result.category == "industrial_builtup"

    def test_snapshot_provider_labels_its_source(self, square_polygon):
        result = SnapshotLanduseProvider([square_polygon]).lookup(22.05, 69.05)
        assert result.provider == "snapshot"
        assert "snapshot" in result.source_note.lower()

    def test_unavailable_provider_never_raises(self):
        result = UnavailableProvider().lookup(22.05, 69.05)
        assert result.category == LC_UNKNOWN

    def test_build_provider_falls_back_to_snapshot_without_network(self, square_polygon):
        provider, name = build_provider(None, snapshot_polygons=[square_polygon], allow_network=False)
        assert name == "snapshot"
        assert provider.lookup(22.05, 69.05).category == "industrial_builtup"

    def test_build_provider_degrades_to_unavailable(self):
        provider, name = build_provider(None, snapshot_polygons=None, allow_network=False)
        assert name == "unavailable"
        assert provider.lookup(22.05, 69.05).category == LC_UNKNOWN

    def test_overpass_failure_does_not_propagate(self, monkeypatch, square_polygon):
        def boom(*args, **kwargs):
            raise RuntimeError("Overpass is down")

        monkeypatch.setattr(landcover.osm, "fetch_landuse", boom)
        provider, name = build_provider(
            (69.0, 22.0, 70.0, 23.0), snapshot_polygons=[square_polygon], allow_network=True
        )
        assert name == "snapshot"


class TestEvidenceSufficiency:
    """The gate that stops the model asserting a class it has no basis for.

    Two of the model's four strongest features are facility proximity and land
    cover. With neither available it still returns a confident-looking number —
    measured on live September data it called 810 of 900 detections
    agricultural burning at a median 0.66, in a month that is not a burning
    season. These tests pin the gate that catches that.
    """

    def test_facility_alone_is_sufficient(self, nearest_facility, land_cover_unknown, event):
        rec = HistoryIndex([]).compute(event)
        sufficient, reason = evidence_sufficiency(nearest_facility, land_cover_unknown, rec)
        assert sufficient is True
        assert reason == ""

    def test_land_cover_alone_is_sufficient(self, land_cover_cropland, event):
        rec = HistoryIndex([]).compute(event)
        sufficient, _ = evidence_sufficiency(None, land_cover_cropland, rec)
        assert sufficient is True

    def test_neither_is_insufficient(self, land_cover_unknown, event):
        rec = HistoryIndex([]).compute(event)
        sufficient, reason = evidence_sufficiency(None, land_cover_unknown, rec)
        assert sufficient is False
        assert "no land-use polygon" in reason.lower()

    def test_recurrence_does_not_substitute_for_spatial_context(
        self, land_cover_unknown, event, history_events
    ):
        """Recurrence separates persistent from one-off, not crop from forest.

        An earlier version of the gate accepted history as sufficient, which
        let through almost every detection the gate exists to catch.
        """
        rec = HistoryIndex(history_events).compute(event)
        assert rec.history_available is True
        assert rec.distinct_days > 0
        sufficient, _ = evidence_sufficiency(None, land_cover_unknown, rec)
        assert sufficient is False

    def test_thin_evidence_raises_the_abstention_bar(self):
        assert (
            settings.low_evidence_abstention_threshold
            > settings.unknown_abstention_threshold
        )

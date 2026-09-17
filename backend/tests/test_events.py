"""Fire-event clustering.

The behaviour that matters here is not "does it group things" but "does it group
the RIGHT things". A clustering rule that is too loose merges two separate fires
in the same district into one incident and hides one of them; too tight and a
single fire front becomes a dozen incidents and buries the operator.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas import Classification, ClassifiedEvent, Evidence, PriorityResult
from app.services.events import (
    EVENT_RADIUS_KM,
    EVENT_WINDOW_HOURS,
    cluster,
    config_summary,
)
from app.services.recurrence import HistoryIndex
from app.taxonomy import INDUSTRIAL_FIRE, NATURAL_FIRE


def make_classified(
    event,
    label=INDUSTRIAL_FIRE,
    confidence=0.8,
    priority=0.5,
    level="MEDIUM",
    facility=None,
    land_cover=None,
):
    """Wrap a raw detection in the classified envelope the clusterer consumes."""
    from app.schemas import LandCoverResult

    rec = HistoryIndex([]).compute(event)
    lc = land_cover or LandCoverResult(
        category="unknown", label="Unknown", provider="unavailable", source_note="test"
    )
    return ClassifiedEvent(
        event=event,
        classification=Classification(
            label=label,
            label_display=label.replace("_", " ").title(),
            description="",
            confidence=confidence,
            confidence_level="HIGH" if confidence >= 0.75 else "MEDIUM",
            abstained=False,
            top_trained_label=label,
        ),
        probabilities={label: confidence},
        evidence=Evidence(
            distance_to_nearest_facility_km=facility.distance_km if facility else None,
            nearest_facility=facility,
            land_cover=lc,
            recurrence=rec,
            thermal_intensity_k=event.brightness_k,
            frp_mw=event.frp_mw,
            firms_confidence=event.firms_confidence_level,
            day_night=event.day_night,
        ),
        factors=[],
        priority=PriorityResult(
            score=priority, level=level, components={"a": 0.5}, weights={"a": 1.0}
        ),
        model=__import__("app.services.classifier", fromlist=["get_classifier"])
        .get_classifier()
        .info(),
        disclaimer="test",
    )


class TestGrouping:
    def test_empty_input(self):
        assert cluster([]) == []

    def test_single_detection_is_one_event(self, event):
        events = cluster([make_classified(event)])
        assert len(events) == 1
        assert events[0].detection_count == 1

    def test_nearby_and_recent_detections_merge(self, event_factory):
        """Two pixels 300 m and 1 h apart are one fire, not two."""
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        a = event_factory(event_id="EVT-A", lat=22.300, lon=69.800)
        b = event_factory(event_id="EVT-B", lat=22.3027, lon=69.800, acq_time="09:00")
        a.acquired_at, b.acquired_at = base, base + timedelta(hours=1)
        events = cluster([make_classified(a), make_classified(b)])
        assert len(events) == 1
        assert events[0].detection_count == 2

    def test_far_apart_detections_stay_separate(self, event_factory):
        a = event_factory(event_id="EVT-A", lat=22.30, lon=69.80)
        b = event_factory(event_id="EVT-B", lat=22.60, lon=69.80)  # ~33 km
        events = cluster([make_classified(a), make_classified(b)])
        assert len(events) == 2

    def test_same_place_but_days_apart_stays_separate(self, event_factory):
        """Critical: a flare that burns on Monday and again on Friday is two
        events, not one. Merging them would erase the persistence signal that
        separates routine flaring from an incident."""
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        a = event_factory(event_id="EVT-A", lat=22.30, lon=69.80)
        b = event_factory(event_id="EVT-B", lat=22.30, lon=69.80)
        a.acquired_at = base
        b.acquired_at = base + timedelta(hours=EVENT_WINDOW_HOURS + 2)
        events = cluster([make_classified(a), make_classified(b)])
        assert len(events) == 2

    def test_membership_is_transitive(self, event_factory):
        """A creeping front: each step is close to the next, the ends are not."""
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        detections = []
        for i in range(5):
            e = event_factory(event_id=f"EVT-{i}", lat=22.30 + i * 0.010, lon=69.80)
            e.acquired_at = base + timedelta(hours=i)
            detections.append(make_classified(e))
        # End-to-end is ~4.4 km, well beyond the join radius.
        events = cluster(detections)
        assert len(events) == 1
        assert events[0].detection_count == 5
        assert events[0].spread_km > EVENT_RADIUS_KM

    def test_event_ids_are_stable(self, event_factory):
        a = event_factory(event_id="EVT-A", lat=22.30, lon=69.80)
        first = cluster([make_classified(a)])[0].event_id
        second = cluster([make_classified(a)])[0].event_id
        assert first == second
        assert first.startswith("FE-")


class TestSummarisation:
    def test_duration_and_counts(self, event_factory):
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        items = []
        for i in range(3):
            e = event_factory(event_id=f"EVT-{i}", lat=22.30, lon=69.80)
            e.acquired_at = base + timedelta(hours=i * 2)
            items.append(make_classified(e))
        ev = cluster(items)[0]
        assert ev.detection_count == 3
        assert ev.duration_hours == pytest.approx(4.0, abs=0.01)
        assert ev.first_detected == base
        assert ev.last_detected == base + timedelta(hours=4)

    def test_frp_is_summed_and_peaked(self, event_factory):
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        items = []
        for i, frp in enumerate([10.0, 25.0, 5.0]):
            e = event_factory(event_id=f"EVT-{i}", lat=22.30, lon=69.80, frp=frp)
            e.acquired_at = base + timedelta(minutes=i * 20)
            items.append(make_classified(e))
        ev = cluster(items)[0]
        assert ev.frp_total_mw == pytest.approx(40.0)
        assert ev.frp_max_mw == pytest.approx(25.0)

    def test_missing_frp_is_not_counted_as_zero(self, event_factory):
        e = event_factory(event_id="EVT-A", frp=None)
        ev = cluster([make_classified(e)])[0]
        assert ev.frp_total_mw is None
        assert ev.frp_max_mw is None

    def test_event_priority_is_the_worst_member(self, event_factory):
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        a = event_factory(event_id="EVT-A", lat=22.30, lon=69.80)
        b = event_factory(event_id="EVT-B", lat=22.3005, lon=69.80)
        a.acquired_at = base
        b.acquired_at = base + timedelta(minutes=30)
        items = [
            make_classified(a, priority=0.2, level="LOW"),
            make_classified(b, priority=0.9, level="HIGH"),
        ]
        ev = cluster(items)[0]
        assert ev.priority_score == pytest.approx(0.9)
        assert ev.priority_level == "HIGH"

    def test_class_is_weighted_by_confidence_not_headcount(self, event_factory):
        """Three hesitant votes should not outrank two confident ones."""
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        items = []
        for i in range(3):
            e = event_factory(event_id=f"EVT-N{i}", lat=22.30, lon=69.80)
            e.acquired_at = base + timedelta(minutes=i * 10)
            items.append(make_classified(e, label=NATURAL_FIRE, confidence=0.30))
        for i in range(2):
            e = event_factory(event_id=f"EVT-I{i}", lat=22.3005, lon=69.80)
            e.acquired_at = base + timedelta(minutes=i * 10 + 5)
            items.append(make_classified(e, label=INDUSTRIAL_FIRE, confidence=0.95))
        ev = cluster(items)[0]
        # 3 x 0.30 = 0.90 < 2 x 0.95 = 1.90
        assert ev.label == INDUSTRIAL_FIRE
        assert ev.label_agreement == pytest.approx(0.4)

    def test_distinct_passes_counted(self, event_factory):
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        items = []
        for i in range(4):
            # Two detections share each acquisition time: two passes, four pixels.
            e = event_factory(
                event_id=f"EVT-{i}", lat=22.30 + i * 0.0005, lon=69.80,
                acq_time="08:00" if i < 2 else "09:30",
            )
            e.acquired_at = base + timedelta(hours=0 if i < 2 else 1.5)
            items.append(make_classified(e))
        ev = cluster(items)[0]
        assert ev.detection_count == 4
        assert ev.distinct_passes == 2


class TestRiskFactors:
    def test_every_event_explains_itself(self, event_factory):
        ev = cluster([make_classified(event_factory())])[0]
        assert ev.risk_factors

    def test_single_detection_is_flagged_as_uncorroborated(self, event_factory):
        ev = cluster([make_classified(event_factory())])[0]
        assert any("single detection" in r.lower() for r in ev.risk_factors)

    def test_multi_platform_confirmation_is_reported(self, event_factory):
        base = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        a = event_factory(event_id="EVT-A", lat=22.30, lon=69.80)
        b = event_factory(event_id="EVT-B", lat=22.3005, lon=69.80)
        a.satellite, b.satellite = "N21", "N20"
        a.acquired_at = base
        b.acquired_at = base + timedelta(hours=1)
        ev = cluster([make_classified(a), make_classified(b)])[0]
        assert any("platform" in r.lower() for r in ev.risk_factors)

    def test_no_template_reasons_when_conditions_absent(self, event_factory):
        """A low-power single detection must not claim high radiative power."""
        ev = cluster([make_classified(event_factory(frp=0.4))])[0]
        assert not any("radiative power" in r.lower() for r in ev.risk_factors)


class TestConfigIsPublished:
    def test_thresholds_are_exposed(self):
        cfg = config_summary()
        assert cfg["radius_km"] == EVENT_RADIUS_KM
        assert cfg["window_hours"] == EVENT_WINDOW_HOURS
        assert "transitive" in cfg["rule"].lower()

    def test_the_dbscan_decision_is_documented(self):
        assert "dbscan" in config_summary()["why_not_dbscan"].lower()

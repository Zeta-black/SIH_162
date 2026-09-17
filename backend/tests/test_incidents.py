"""Alert rule and incident lifecycle.

Two things matter here and both are about restraint rather than capability:

1. The alert rule must be *selective*. A system that alerts on everything trains
   its operators to ignore it, and the single easiest way to do that is to page
   someone about a flare stack that burns every day.
2. The state machine must reject impossible transitions, so the audit log cannot
   record a resolve that nobody acknowledged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import incidents as inc
from app.services.events import FireEvent
from app.store.db import EventStore, reset_store
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    NATURAL_FIRE,
)


def make_event(
    event_id="FE-2026-TEST",
    label=INDUSTRIAL_FIRE,
    priority_score=0.8,
    priority_level="HIGH",
    detections=4,
    facility_km=0.3,
    persistent=False,
    frp_max=20.0,
) -> FireEvent:
    now = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
    return FireEvent(
        event_id=event_id,
        latitude=22.3,
        longitude=69.8,
        detection_count=detections,
        first_detected=now,
        last_detected=now + timedelta(hours=2),
        duration_hours=2.0,
        label=label,
        label_display=label.replace("_", " ").title(),
        label_confidence=0.85,
        label_agreement=1.0,
        class_distribution={label: detections},
        priority_score=priority_score,
        priority_level=priority_level,
        frp_total_mw=frp_max * detections if frp_max else None,
        frp_max_mw=frp_max,
        brightness_max_k=340.0,
        satellites=["N21"],
        products=["VIIRS_NOAA21_NRT"],
        spread_km=0.5,
        distinct_passes=2,
        nearest_facility_name="Test Refinery",
        nearest_facility_km=facility_km,
        land_cover="Industrial / built-up",
        persistent=persistent,
        risk_factors=["test"],
        detection_ids=[f"EVT-{i}" for i in range(detections)],
        lead_detection_id="EVT-0",
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway incident store, so tests never touch the real database."""
    reset_store()
    s = EventStore(tmp_path / "incidents.sqlite3")
    monkeypatch.setattr("app.services.incidents.get_store", lambda: s)
    inc.ensure_schema()
    yield s
    reset_store()


# ---------------------------------------------------------------------------
# The alert rule
# ---------------------------------------------------------------------------
class TestAlertRule:
    def test_corroborated_onsite_industrial_fire_is_critical(self):
        level, reasons = inc.alert_for(make_event())
        assert level == "CRITICAL"
        assert reasons

    def test_persistent_flare_is_never_critical(self):
        """The whole point. A stack that burns every day must not page anyone."""
        level, _ = inc.alert_for(
            make_event(label=GAS_FLARE_OR_INDUSTRIAL_HEAT, persistent=True)
        )
        assert level != "CRITICAL"

    def test_persistent_industrial_fire_is_not_critical_either(self):
        """Even classified an industrial fire, a recurring source is routine."""
        level, _ = inc.alert_for(make_event(persistent=True))
        assert level != "CRITICAL"

    def test_uncorroborated_single_detection_is_not_critical(self):
        level, _ = inc.alert_for(make_event(detections=1))
        assert level != "CRITICAL"

    def test_low_priority_vegetation_fire_raises_nothing(self):
        level, reasons = inc.alert_for(
            make_event(
                label=NATURAL_FIRE,
                priority_score=0.2,
                priority_level="LOW",
                facility_km=None,
                frp_max=3.0,
            )
        )
        assert level is None
        assert reasons == []

    def test_high_radiative_power_alerts_even_far_from_industry(self):
        level, reasons = inc.alert_for(
            make_event(
                label=AGRICULTURAL_BURNING,
                priority_score=0.3,
                priority_level="LOW",
                facility_km=None,
                frp_max=120.0,
            )
        )
        assert level is not None
        assert any("radiative power" in r.lower() for r in reasons)

    def test_every_alert_states_its_reasons(self):
        level, reasons = inc.alert_for(make_event())
        assert level and reasons

    def test_rule_is_published(self):
        rule = inc.alert_rule_summary()
        assert "CRITICAL" in rule["levels"]
        assert "flaring" in rule["critical_rule"].lower()
        # The delivery limitation must be stated, not implied.
        assert "no email" in rule["delivery"].lower()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
class TestSync:
    def test_only_alerting_events_become_incidents(self, store):
        quiet = make_event(
            event_id="FE-QUIET",
            label=NATURAL_FIRE,
            priority_score=0.2,
            priority_level="LOW",
            facility_km=None,
            frp_max=2.0,
        )
        result = inc.sync([make_event(event_id="FE-LOUD"), quiet])
        assert result["created"] == 1
        assert result["skipped"] == 1

    def test_sync_is_idempotent(self, store):
        event = make_event()
        first = inc.sync([event])
        second = inc.sync([event])
        assert first["created"] == 1
        assert second["created"] == 0
        assert second["updated"] == 1

    def test_resync_does_not_reset_workflow_state(self, store):
        """Re-running the analysis must never un-acknowledge an incident."""
        event = make_event()
        inc.sync([event])
        inc.act(event.event_id, "acknowledge", actor="R. Kumar")
        inc.sync([event])
        assert inc.get_incident(event.event_id)["status"] == inc.ACKNOWLEDGED

    def test_resync_refreshes_detection_count(self, store):
        event = make_event(detections=4)
        inc.sync([event])
        inc.sync([make_event(detections=9)])
        assert inc.get_incident(event.event_id)["detection_count"] == 9

    def test_raise_is_logged_by_the_system(self, store):
        event = make_event()
        inc.sync([event])
        actions = inc.get_incident(event.event_id)["actions"]
        assert actions[0]["actor"] == "system"
        assert actions[0]["to_status"] == inc.NEW


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
class TestLifecycle:
    def test_full_happy_path(self, store):
        event = make_event()
        inc.sync([event])
        for action, expected in [
            ("acknowledge", inc.ACKNOWLEDGED),
            ("dispatch", inc.DISPATCHED),
            ("monitor", inc.MONITORING),
            ("resolve", inc.RESOLVED),
        ]:
            record = inc.act(event.event_id, action, actor="operator")
            assert record["status"] == expected

    def test_cannot_resolve_without_acknowledging(self, store):
        event = make_event()
        inc.sync([event])
        with pytest.raises(inc.IncidentError, match="Cannot 'resolve'"):
            inc.act(event.event_id, "resolve")

    def test_cannot_dispatch_a_resolved_incident(self, store):
        event = make_event()
        inc.sync([event])
        inc.act(event.event_id, "acknowledge")
        inc.act(event.event_id, "resolve")
        with pytest.raises(inc.IncidentError, match="Cannot 'dispatch'"):
            inc.act(event.event_id, "dispatch")

    def test_resolved_can_be_reopened(self, store):
        event = make_event()
        inc.sync([event])
        inc.act(event.event_id, "acknowledge")
        inc.act(event.event_id, "resolve")
        assert inc.act(event.event_id, "reopen")["status"] == inc.ACKNOWLEDGED

    def test_dismiss_from_new(self, store):
        event = make_event()
        inc.sync([event])
        assert inc.act(event.event_id, "dismiss")["status"] == inc.DISMISSED

    def test_assign_records_without_changing_status(self, store):
        event = make_event()
        inc.sync([event])
        inc.act(event.event_id, "acknowledge")
        record = inc.act(event.event_id, "assign", actor="R. Kumar", note="Range Team 3")
        assert record["assigned_to"] == "Range Team 3"
        assert record["status"] == inc.ACKNOWLEDGED

    def test_unknown_incident_is_rejected(self, store):
        with pytest.raises(inc.IncidentError, match="No incident"):
            inc.act("FE-DOES-NOT-EXIST", "acknowledge")

    def test_every_action_is_logged_with_actor_and_transition(self, store):
        event = make_event()
        inc.sync([event])
        inc.act(event.event_id, "acknowledge", actor="R. Kumar", note="verified")
        log = inc.get_incident(event.event_id)["actions"]
        last = log[-1]
        assert last["actor"] == "R. Kumar"
        assert last["from_status"] == inc.NEW
        assert last["to_status"] == inc.ACKNOWLEDGED
        assert last["note"] == "verified"

    def test_log_is_append_only_across_a_full_cycle(self, store):
        event = make_event()
        inc.sync([event])
        for a in ["acknowledge", "dispatch", "resolve"]:
            inc.act(event.event_id, a)
        # 1 system raise + 3 operator actions
        assert len(inc.get_incident(event.event_id)["actions"]) == 4

    def test_available_actions_reflect_current_state(self, store):
        event = make_event()
        inc.sync([event])
        available = inc.get_incident(event.event_id)["available_actions"]
        assert "acknowledge" in available
        assert "resolve" not in available


class TestCounts:
    def test_open_excludes_closed(self, store):
        inc.sync([make_event(event_id="FE-A"), make_event(event_id="FE-B")])
        inc.act("FE-A", "acknowledge")
        inc.act("FE-A", "resolve")
        counts = inc.counts()
        assert counts["open"] == 1
        assert counts[inc.RESOLVED] == 1

    def test_lifecycle_is_published(self):
        summary = inc.lifecycle_summary()
        assert inc.NEW in summary["statuses"]
        assert "rejected" in summary["note"].lower()

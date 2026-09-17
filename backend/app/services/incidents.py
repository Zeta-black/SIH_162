"""Incident lifecycle and alerting.

WHAT THIS ADDS

Until now the system could say "this thermal anomaly is probably an industrial
fire, here is why, and it ranks third today". It could not say what anyone had
*done* about it. A control room needs the second half: a queue that remembers
which incidents have been looked at, who is handling them, and what happened.

So a fire event that crosses the alert rule becomes an **incident** with a
status, an assignee and an append-only action log.

DELIBERATE SCOPE LIMITS, STATED UP FRONT

* Alerts are raised **in the dashboard only**. There is no email, SMS, Telegram
  or webhook delivery, and none is simulated. Claiming a notification channel
  that does not send anything would be exactly the kind of thing that collapses
  under one follow-up question.
* There is **no authentication**. The `actor` on an action is a name typed by
  whoever is at the console. It is recorded for traceability, not as proof of
  identity, and the API says so.
* Incident state is keyed on the fire-event id, which is a deterministic hash of
  the earliest detection and the cluster centroid. That means an incident
  survives re-analysis: the same fire produces the same id tomorrow, so an
  acknowledgement made today is still attached to it.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from app.services.events import FireEvent
from app.store.db import get_store
from app.taxonomy import GAS_FLARE_OR_INDUSTRIAL_HEAT, INDUSTRIAL_FIRE

log = logging.getLogger("firetrace.incidents")

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
NEW = "NEW"
ACKNOWLEDGED = "ACKNOWLEDGED"
DISPATCHED = "DISPATCHED"
MONITORING = "MONITORING"
RESOLVED = "RESOLVED"
DISMISSED = "DISMISSED"

OPEN_STATUSES = {NEW, ACKNOWLEDGED, DISPATCHED, MONITORING}
CLOSED_STATUSES = {RESOLVED, DISMISSED}

# Which action may be taken from which state. A transition not listed here is
# rejected, so the log cannot record an impossible sequence such as resolving an
# incident nobody ever acknowledged.
TRANSITIONS: dict[str, dict[str, str]] = {
    NEW: {"acknowledge": ACKNOWLEDGED, "dismiss": DISMISSED},
    ACKNOWLEDGED: {"dispatch": DISPATCHED, "monitor": MONITORING, "resolve": RESOLVED, "dismiss": DISMISSED},
    DISPATCHED: {"monitor": MONITORING, "resolve": RESOLVED},
    MONITORING: {"dispatch": DISPATCHED, "resolve": RESOLVED},
    RESOLVED: {"reopen": ACKNOWLEDGED},
    DISMISSED: {"reopen": ACKNOWLEDGED},
}

ACTION_LABELS = {
    "acknowledge": "Acknowledged",
    "dispatch": "Response team dispatched",
    "monitor": "Placed under monitoring",
    "resolve": "Resolved",
    "dismiss": "Dismissed as non-actionable",
    "reopen": "Reopened",
    "assign": "Assignee changed",
    "note": "Note added",
    "re-alert": "Re-alerted after closure",
    "escalated": "Alert level escalated",
}

# Actions that record information without moving the incident on.
NON_TRANSITION_ACTIONS = {"assign", "note"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    event_id        TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    priority_level  TEXT NOT NULL,
    priority_score  REAL NOT NULL,
    label           TEXT NOT NULL,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    detection_count INTEGER NOT NULL,
    first_detected  TEXT NOT NULL,
    last_detected   TEXT NOT NULL,
    assigned_to     TEXT,
    alert_level     TEXT,
    alert_reasons   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_priority ON incidents(priority_score DESC);

CREATE TABLE IF NOT EXISTS incident_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    action      TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    actor       TEXT NOT NULL,
    note        TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_event ON incident_actions(event_id, id);
"""


class IncidentError(Exception):
    """Raised for an illegal transition. Carries a user-safe message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    store = get_store()
    if not store.ready:
        return
    try:
        with store.connect() as conn:
            conn.executescript(SCHEMA)
    except sqlite3.Error as exc:
        log.error("[INCIDENTS] could not create schema: %s", exc)


# ---------------------------------------------------------------------------
# Alert rule
# ---------------------------------------------------------------------------
def alert_for(event: FireEvent) -> tuple[str | None, list[str]]:
    """Should this fire event raise an alert, and at what level?

    Deliberately a small set of stated conditions rather than a threshold on the
    priority score alone. An operator can read this and predict what the system
    will do, which is the difference between a tool they trust and one they
    learn to ignore.

    Returns (level, reasons). `None` means no alert — most events do not warrant
    one, and an alert on everything is an alert on nothing.
    """
    reasons: list[str] = []
    industrial = event.label in {INDUSTRIAL_FIRE, GAS_FLARE_OR_INDUSTRIAL_HEAT}
    corroborated = event.detection_count >= 2
    on_site = event.nearest_facility_km is not None and event.nearest_facility_km <= 1.0

    if event.priority_level == "HIGH":
        reasons.append(f"Priority score {event.priority_score:.2f} in the HIGH band")

    if event.label == INDUSTRIAL_FIRE and corroborated:
        reasons.append(
            f"Classified an industrial fire and corroborated by {event.detection_count} detections"
        )

    if event.label == INDUSTRIAL_FIRE and on_site and not event.persistent:
        reasons.append(
            f"On an industrial footprint ({event.nearest_facility_name}) with no history of "
            "burning at this location"
        )

    if event.frp_max_mw is not None and event.frp_max_mw >= 50:
        reasons.append(f"Peak radiative power {event.frp_max_mw:.0f} MW")

    if not reasons:
        return None, []

    # CRITICAL is reserved for an abnormal industrial event, not routine flaring.
    # A flare stack that burns every day is the single most common way an
    # operational alerting system trains its users to ignore it.
    critical = (
        event.label == INDUSTRIAL_FIRE
        and corroborated
        and on_site
        and not event.persistent
    )
    if critical:
        return "CRITICAL", reasons
    if event.priority_level == "HIGH" or industrial:
        return "HIGH", reasons
    return "ADVISORY", reasons


# Alert levels ordered by seriousness, so an escalation can be detected rather
# than assumed. Anything unrecognised ranks lowest and therefore never
# manufactures a false escalation.
_LEVEL_RANK = {"ADVISORY": 1, "HIGH": 2, "CRITICAL": 3}


def _rank(level: str | None) -> int:
    return _LEVEL_RANK.get(level or "", 0)


def alert_rule_summary() -> dict[str, object]:
    """Published so the rule is inspectable rather than implied."""
    return {
        "levels": ["CRITICAL", "HIGH", "ADVISORY"],
        "conditions": [
            "Priority score in the HIGH band",
            "Classified INDUSTRIAL_FIRE and corroborated by 2+ detections",
            "On an industrial footprint (<=1 km) with no prior burn history",
            "Peak radiative power >= 50 MW",
        ],
        "critical_rule": (
            "CRITICAL requires all of: classified an industrial fire, corroborated by "
            "2+ detections, within 1 km of a mapped facility, and NOT a persistent "
            "source. Routine flaring is explicitly excluded — a stack that burns every "
            "day must never page anyone, or operators learn to ignore the system."
        ),
        "delivery": (
            "In-dashboard only. No email, SMS or webhook delivery is implemented, and "
            "none is simulated."
        ),
        "no_auth": (
            "There is no authentication. The actor recorded against an action is a name "
            "entered at the console — traceability, not identity."
        ),
        "deduplication": (
            "One incident per fire event, keyed on the event_id derived from the "
            "event's first detection time and position. Re-running the analysis over "
            "the same event updates the existing incident and never raises a second "
            "alert, so an operator cannot be paged twice for one fire."
        ),
        "cooldown": (
            "There is no timed cooldown, because identity-based de-duplication makes "
            "one unnecessary: a repeat observation of the same source resolves to the "
            "same event_id and lands on the existing incident. A timer would be the "
            "wrong mechanism — it would also suppress a genuinely new fire that "
            "started nearby within the window."
        ),
        "escalation": (
            "The two cases where a repeat observation is NOT silent: an alert level "
            "rising on an open incident is logged as an escalation, and an event that "
            "re-alerts after being resolved or dismissed is logged as a re-alert. "
            "Neither changes the incident's status on its own — reopening is an "
            "operator decision — but both are recorded so a re-ignition cannot pass "
            "unnoticed."
        ),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def sync(events: Iterable[FireEvent]) -> dict[str, int]:
    """Create incident rows for fire events that warrant an alert.

    Existing incidents keep their status and assignee — re-running the analysis
    must never quietly reset an acknowledgement. Only the detection counts and
    the priority, which genuinely change as more passes arrive, are refreshed.
    """
    ensure_schema()
    store = get_store()
    if not store.ready:
        return {"created": 0, "updated": 0, "skipped": 0}

    created = updated = skipped = 0
    escalated = re_alerted = 0
    now = _now()

    try:
        with store.connect() as conn:
            for event in events:
                level, reasons = alert_for(event)
                if level is None:
                    skipped += 1
                    continue

                row = conn.execute(
                    "SELECT status, alert_level FROM incidents WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        """INSERT INTO incidents
                           (event_id, status, priority_level, priority_score, label,
                            latitude, longitude, detection_count, first_detected,
                            last_detected, assigned_to, alert_level, alert_reasons,
                            created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            event.event_id, NEW, event.priority_level, event.priority_score,
                            event.label, event.latitude, event.longitude,
                            event.detection_count, event.first_detected.isoformat(),
                            event.last_detected.isoformat(), None, level,
                            json.dumps(reasons), now, now,
                        ),
                    )
                    conn.execute(
                        """INSERT INTO incident_actions
                           (event_id, action, from_status, to_status, actor, note, at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            event.event_id, "raised", None, NEW, "system",
                            f"{level} alert raised: {reasons[0] if reasons else ''}", now,
                        ),
                    )
                    created += 1
                else:
                    # The incident already exists, so this is NOT a second alert.
                    # Refresh the facts that genuinely change and leave the
                    # workflow alone — but do not let two situations pass
                    # silently, because both mean something to an operator.
                    previous_status = row["status"]
                    previous_level = row["alert_level"]

                    if previous_status in CLOSED_STATUSES:
                        # A closed incident whose event is alerting again. The
                        # status is NOT changed — reopening is an operator
                        # decision — but a silent UPDATE here would bury a
                        # genuine re-ignition, so it is written to the log.
                        conn.execute(
                            """INSERT INTO incident_actions
                               (event_id, action, from_status, to_status, actor, note, at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (
                                event.event_id, "re-alert", previous_status, previous_status,
                                "system",
                                f"Event alerted again at {level} while {previous_status}. "
                                f"Status unchanged; reopen to act on it.",
                                now,
                            ),
                        )
                        re_alerted += 1
                    elif _rank(level) > _rank(previous_level):
                        conn.execute(
                            """INSERT INTO incident_actions
                               (event_id, action, from_status, to_status, actor, note, at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (
                                event.event_id, "escalated", previous_status, previous_status,
                                "system",
                                f"Alert level escalated {previous_level} -> {level}.",
                                now,
                            ),
                        )
                        escalated += 1

                    conn.execute(
                        """UPDATE incidents
                           SET priority_level = ?, priority_score = ?, detection_count = ?,
                               last_detected = ?, alert_level = ?, alert_reasons = ?,
                               updated_at = ?
                           WHERE event_id = ?""",
                        (
                            event.priority_level, event.priority_score, event.detection_count,
                            event.last_detected.isoformat(), level, json.dumps(reasons),
                            now, event.event_id,
                        ),
                    )
                    updated += 1
    except sqlite3.Error as exc:
        log.error("[INCIDENTS] sync failed: %s", exc)
        return {"created": 0, "updated": 0, "skipped": 0, "escalated": 0, "re_alerted": 0}

    if created or escalated or re_alerted:
        log.info(
            "[ALERT] %d raised, %d updated, %d escalated, %d re-alerted while closed",
            created, updated, escalated, re_alerted,
        )
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "escalated": escalated,
        "re_alerted": re_alerted,
    }


def list_incidents(status: str | None = None, limit: int = 200) -> list[dict]:
    ensure_schema()
    store = get_store()
    if not store.ready:
        return []
    sql = "SELECT * FROM incidents"
    params: list[object] = []
    if status == "open":
        sql += f" WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})"
        params += sorted(OPEN_STATUSES)
    elif status == "closed":
        sql += f" WHERE status IN ({','.join('?' * len(CLOSED_STATUSES))})"
        params += sorted(CLOSED_STATUSES)
    elif status:
        sql += " WHERE status = ?"
        params.append(status.upper())
    sql += " ORDER BY priority_score DESC LIMIT ?"
    params.append(int(limit))

    try:
        with store.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        log.error("[INCIDENTS] query failed: %s", exc)
        return []

    return [_row_to_dict(r) for r in rows]


def get_incident(event_id: str) -> dict | None:
    ensure_schema()
    store = get_store()
    if not store.ready:
        return None
    try:
        with store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return None
            incident = _row_to_dict(row)
            actions = conn.execute(
                "SELECT * FROM incident_actions WHERE event_id = ? ORDER BY id", (event_id,)
            ).fetchall()
    except sqlite3.Error:
        return None

    incident["actions"] = [dict(a) for a in actions]
    incident["available_actions"] = sorted(TRANSITIONS.get(incident["status"], {}).keys()) + sorted(
        NON_TRANSITION_ACTIONS
    )
    return incident


def act(event_id: str, action: str, actor: str = "operator", note: str | None = None) -> dict:
    """Apply an action to an incident and append it to the audit log."""
    ensure_schema()
    store = get_store()
    if not store.ready:
        raise IncidentError("Incident store is unavailable.")

    action = action.strip().lower()
    actor = (actor or "operator").strip()[:80]

    with store.connect() as conn:
        row = conn.execute(
            "SELECT status FROM incidents WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise IncidentError(f"No incident {event_id}.")
        current = row["status"]

        if action in NON_TRANSITION_ACTIONS:
            target = current
            if action == "assign":
                conn.execute(
                    "UPDATE incidents SET assigned_to = ?, updated_at = ? WHERE event_id = ?",
                    (note or None, _now(), event_id),
                )
        else:
            allowed = TRANSITIONS.get(current, {})
            if action not in allowed:
                raise IncidentError(
                    f"Cannot '{action}' an incident that is {current}. "
                    f"Allowed from here: {', '.join(sorted(allowed)) or 'none'}."
                )
            target = allowed[action]
            conn.execute(
                "UPDATE incidents SET status = ?, updated_at = ? WHERE event_id = ?",
                (target, _now(), event_id),
            )

        conn.execute(
            """INSERT INTO incident_actions
               (event_id, action, from_status, to_status, actor, note, at)
               VALUES (?,?,?,?,?,?,?)""",
            (event_id, action, current, target, actor, note, _now()),
        )

    log.info("[INCIDENT] %s %s: %s -> %s by %s", event_id, action, current, target, actor)
    return get_incident(event_id) or {}


def counts() -> dict[str, int]:
    ensure_schema()
    store = get_store()
    if not store.ready:
        return {}
    try:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM incidents GROUP BY status"
            ).fetchall()
    except sqlite3.Error:
        return {}
    out = {s: 0 for s in [NEW, ACKNOWLEDGED, DISPATCHED, MONITORING, RESOLVED, DISMISSED]}
    for r in rows:
        out[r["status"]] = r["n"]
    out["open"] = sum(out[s] for s in OPEN_STATUSES)
    return out


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["alert_reasons"] = json.loads(d.get("alert_reasons") or "[]")
    except json.JSONDecodeError:
        d["alert_reasons"] = []
    return d


def lifecycle_summary() -> dict[str, object]:
    return {
        "statuses": [NEW, ACKNOWLEDGED, DISPATCHED, MONITORING, RESOLVED, DISMISSED],
        "open": sorted(OPEN_STATUSES),
        "closed": sorted(CLOSED_STATUSES),
        "transitions": {k: v for k, v in TRANSITIONS.items()},
        "labels": ACTION_LABELS,
        "note": (
            "Transitions are validated. An action not allowed from the current status is "
            "rejected, so the audit log cannot record an impossible sequence such as "
            "resolving an incident nobody acknowledged."
        ),
    }

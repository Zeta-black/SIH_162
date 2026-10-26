"""The notification engine.

Implements docs/NOTIFICATION_POLICY.md. Read that first — the policy is the
specification and this is only its mechanism.

The design rule that matters most: **replay safety is enforced at creation, not
per channel.** `evaluate()` takes a `suppress` flag and, when it is set, returns
what *would* have fired without writing or sending anything. A new channel added
later cannot forget to honour it, because it never sees a suppressed item.

Nothing in here invents a notification. Every item is derived from a site the
analysis already produced, and an "above its normal range" claim requires an
assessed baseline — the notification equivalent of the Pass 1 abnormality
defect, which is tested directly.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.config import settings

log = logging.getLogger("firetrace.notify")

POLICY_VERSION = "1.0.0"

# --- reason codes ----------------------------------------------------------
NEEDS_ATTENTION = "NEEDS_ATTENTION"
ABNORMAL_PERSISTENT = "ABNORMAL_PERSISTENT"
NEW_HEAT_AT_FACILITY = "NEW_HEAT_AT_FACILITY"
SYSTEM_FEED_DELAYED = "SYSTEM_FEED_DELAYED"
SYSTEM_WEBHOOK_FAILED = "SYSTEM_WEBHOOK_FAILED"

OPERATIONAL_REASONS = {NEEDS_ATTENTION, ABNORMAL_PERSISTENT, NEW_HEAT_AT_FACILITY}
SYSTEM_REASONS = {SYSTEM_FEED_DELAYED, SYSTEM_WEBHOOK_FAILED}

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}

# Language that would overstate what a thermal detection can establish. Checked
# by test on every generated message.
FORBIDDEN_WORDS = (
    "confirmed",
    "definitely",
    "certain",
    "guaranteed",
    "100%",
    "real-time",
    "realtime",
    "instant",
    "ai-powered",
)


@dataclass
class Notification:
    """One item in the queue."""

    id: str
    reason_code: str
    severity: str
    title: str
    body: str
    site_id: str | None
    site_name: str | None
    status: str | None
    created_at: datetime
    state: str = "created"
    seen_at: datetime | None = None
    acknowledged_at: datetime | None = None
    snoozed_until: datetime | None = None
    resolved_at: datetime | None = None
    priority_score: float | None = None
    observed_at: str | None = None
    policy_version: str = POLICY_VERSION
    is_test: bool = False
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "reason_code": self.reason_code,
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "site_id": self.site_id,
            "site_name": self.site_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "state": self.state,
            "seen_at": self.seen_at.isoformat() if self.seen_at else None,
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "priority_score": self.priority_score,
            "observed_at": self.observed_at,
            "policy_version": self.policy_version,
            "is_test": self.is_test,
            "group": "system" if self.reason_code in SYSTEM_REASONS else "attention",
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------
def _check_language(text: str) -> str:
    """Fail loudly in development if a message overstates the evidence."""
    lowered = text.lower()
    for word in FORBIDDEN_WORDS:
        if word in lowered:
            raise ValueError(
                f"Notification text may not contain {word!r} — see "
                f"docs/NOTIFICATION_POLICY.md section 1. Offending text: {text!r}"
            )
    return text


def _site_label(site: dict) -> str:
    return site.get("title") or site.get("nearest_facility_name") or "an unnamed location"


def _build(reason: str, site: dict) -> tuple[str, str, str]:
    """(severity, title, body) for a site-derived reason."""
    name = _site_label(site)

    if reason == NEEDS_ATTENTION:
        return (
            "high",
            _check_language(f"Needs attention at {name}"),
            _check_language(site.get("verdict") or "Clearly unusual for this location."),
        )

    if reason == ABNORMAL_PERSISTENT:
        score = site.get("abnormality_score")
        days = site.get("distinct_days") or 0
        return (
            "high",
            _check_language(f"Unusual heat at {name} — above its normal range"),
            _check_language(
                f"Abnormality {score}/100 against {days} days of recorded history "
                f"at this location."
            ),
        )

    # NEW_HEAT_AT_FACILITY. Deliberately "new heat detected", never "fire".
    return (
        "medium",
        _check_language(f"New heat detected at {name}"),
        _check_language(
            "No previous heat recorded at this location in the history window. "
            "Proximity to a facility is context, not proof of cause."
        ),
    )


# ---------------------------------------------------------------------------
# Trigger rules
# ---------------------------------------------------------------------------
def _reasons_for(site: dict) -> list[str]:
    """Which reasons this site qualifies for, if any.

    Normal, Watch and Not sure produce nothing — they live on the map. That is a
    policy decision about alert fatigue, not an oversight.
    """
    reasons: list[str] = []
    status = site.get("status")

    if status == "needs_attention":
        reasons.append(NEEDS_ATTENTION)

    # An "above its normal range" claim is only permitted where a baseline was
    # actually assessed. Without one there is no normal range to exceed.
    if (
        site.get("persistent")
        and site.get("abnormality_status") == "assessed"
        and (site.get("abnormality_score") or 0) >= settings.notify_abnormal_threshold
    ):
        reasons.append(ABNORMAL_PERSISTENT)

    # New heat at a mapped facility: on or near the footprint, no prior history.
    km = site.get("nearest_facility_km")
    if (
        site.get("nearest_facility_name")
        and km is not None
        and km <= settings.facility_onsite_km
        and site.get("history_available")
        and (site.get("distinct_days") or 0) == 0
        and status in ("needs_attention", "watch")
    ):
        reasons.append(NEW_HEAT_AT_FACILITY)

    return reasons


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id              TEXT PRIMARY KEY,
    reason_code     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    site_id         TEXT,
    site_name       TEXT,
    status          TEXT,
    created_at      TEXT NOT NULL,
    state           TEXT NOT NULL,
    seen_at         TEXT,
    acknowledged_at TEXT,
    snoozed_until   TEXT,
    resolved_at     TEXT,
    priority_score  REAL,
    observed_at     TEXT,
    policy_version  TEXT NOT NULL,
    is_test         INTEGER NOT NULL DEFAULT 0,
    meta            TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_notif_site ON notifications(site_id, reason_code);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id TEXT NOT NULL,
    channel         TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    ok              INTEGER NOT NULL,
    status_code     INTEGER,
    error           TEXT,
    attempted_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_notif ON notification_deliveries(notification_id);
"""


class NotificationStore:
    """SQLite-backed queue. Shares the main database file."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.database_path
        self.ready = False
        self.error: str | None = None
        try:
            with self.connect() as conn:
                conn.executescript(SCHEMA)
            self.ready = True
        except sqlite3.Error as exc:
            self.error = str(exc)
            log.error("[NOTIFY] store unavailable: %s", exc)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # -- writes ------------------------------------------------------------
    def insert(self, notification: Notification) -> None:
        if not self.ready:
            return
        d = notification.as_dict()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO notifications "
                "(id, reason_code, severity, title, body, site_id, site_name, status, "
                " created_at, state, seen_at, acknowledged_at, snoozed_until, resolved_at, "
                " priority_score, observed_at, policy_version, is_test, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    d["id"], d["reason_code"], d["severity"], d["title"], d["body"],
                    d["site_id"], d["site_name"], d["status"], d["created_at"], d["state"],
                    d["seen_at"], d["acknowledged_at"], d["snoozed_until"], d["resolved_at"],
                    d["priority_score"], d["observed_at"], d["policy_version"],
                    1 if d["is_test"] else 0, json.dumps(d["meta"]),
                ),
            )

    def set_state(self, notification_id: str, state: str, **stamps: str | None) -> bool:
        if not self.ready:
            return False
        columns = ", ".join(f"{k} = ?" for k in stamps)
        sql = f"UPDATE notifications SET state = ?{', ' + columns if columns else ''} WHERE id = ?"
        params = [state, *stamps.values(), notification_id]
        with self.connect() as conn:
            return conn.execute(sql, params).rowcount > 0

    def record_delivery(
        self,
        notification_id: str,
        channel: str,
        attempt: int,
        ok: bool,
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        if not self.ready:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO notification_deliveries "
                "(notification_id, channel, attempt, ok, status_code, error, attempted_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    notification_id,
                    channel,
                    attempt,
                    1 if ok else 0,
                    status_code,
                    error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    # -- reads -------------------------------------------------------------
    def recent(self, limit: int = 50, include_resolved: bool = False) -> list[dict]:
        if not self.ready:
            return []
        sql = "SELECT * FROM notifications"
        if not include_resolved:
            sql += " WHERE state != 'resolved'"
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def last_for(self, site_id: str, reason: str) -> dict | None:
        if not self.ready:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM notifications WHERE site_id = ? AND reason_code = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (site_id, reason),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def system_count_today(self) -> int:
        if not self.ready:
            return 0
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        placeholders = ",".join("?" for _ in SYSTEM_REASONS)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM notifications WHERE created_at >= ? "
                f"AND reason_code IN ({placeholders})",
                (since, *SYSTEM_REASONS),
            ).fetchone()
        return int(row[0]) if row else 0

    def deliveries(self, notification_id: str) -> list[dict]:
        if not self.ready:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_deliveries WHERE notification_id = ? "
                "ORDER BY attempt",
                (notification_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        if not self.ready:
            return {"unread": 0, "open": 0}
        with self.connect() as conn:
            unread = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE state = 'created'"
            ).fetchone()[0]
            open_items = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE state != 'resolved'"
            ).fetchone()[0]
        return {"unread": int(unread), "open": int(open_items)}

    def clear(self) -> None:
        if not self.ready:
            return
        with self.connect() as conn:
            conn.execute("DELETE FROM notifications")
            conn.execute("DELETE FROM notification_deliveries")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["is_test"] = bool(d.get("is_test"))
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except (TypeError, ValueError):
        d["meta"] = {}
    d["group"] = "system" if d["reason_code"] in SYSTEM_REASONS else "attention"
    return d


_store: NotificationStore | None = None


def get_store() -> NotificationStore:
    global _store
    if _store is None:
        _store = NotificationStore()
    return _store


def reset_store_for_tests(path: str | None = None) -> NotificationStore:
    global _store
    _store = NotificationStore(path)
    return _store


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
_seeded = False


def _notification_id(site_id: str, reason: str, when: datetime) -> str:
    return f"{reason}:{site_id}:{int(when.timestamp())}"


def evaluate(
    sites: list[dict],
    *,
    suppress: bool,
    feed: dict | None = None,
    now: datetime | None = None,
    seed_only: bool | None = None,
) -> dict:
    """Decide what to notify about.

    `suppress=True` (Past data) computes the same answer and writes nothing, so
    the interface can show a "Would have alerted" preview without any channel
    being able to leak a real alert.
    """
    global _seeded
    now = now or datetime.now(timezone.utc)
    store = get_store()

    if not settings.notify_enabled:
        return {"created": [], "preview": [], "suppressed": suppress, "reason": "disabled"}

    candidates: list[Notification] = []
    for site in sites:
        reasons = _reasons_for(site)
        # One site, one notification per evaluation.
        #
        # A site can legitimately qualify for several reasons at once — a new
        # detection on a facility footprint is both NEEDS_ATTENTION and
        # NEW_HEAT_AT_FACILITY. Sending both is two bells for one event, which
        # is the fatigue this policy exists to avoid, so only the most severe
        # reason speaks. The others are still derivable from the site itself.
        if reasons:
            reasons = [max(reasons, key=lambda r: SEVERITY_RANK[_build(r, site)[0]])]
        for reason in reasons:
            severity, title, body = _build(reason, site)
            candidates.append(
                Notification(
                    id=_notification_id(site["id"], reason, now),
                    reason_code=reason,
                    severity=severity,
                    title=title,
                    body=body,
                    site_id=site["id"],
                    site_name=_site_label(site),
                    status=site.get("status"),
                    created_at=now,
                    priority_score=site.get("priority_score"),
                    observed_at=site.get("observed_at"),
                    meta={
                        "lat": site.get("lat"),
                        "lon": site.get("lon"),
                        "abnormality_score": site.get("abnormality_score"),
                        "abnormality_status": site.get("abnormality_status"),
                    },
                )
            )

    # Feed-delay notice, capped per day.
    if feed and not suppress:
        age = feed.get("observed_age_minutes")
        if age is not None and age > settings.notify_feed_delay_hours * 60:
            if store.system_count_today() < settings.notify_system_daily_cap:
                hours = age // 60
                candidates.append(
                    Notification(
                        id=f"{SYSTEM_FEED_DELAYED}:{now.strftime('%Y%m%d%H')}",
                        reason_code=SYSTEM_FEED_DELAYED,
                        severity="low",
                        title=_check_language("Satellite feed delayed"),
                        body=_check_language(
                            f"The newest detection is {hours} h old. FIRETRACE is "
                            f"retrying in the background and is showing saved data."
                        ),
                        site_id=None,
                        site_name=None,
                        status=None,
                        created_at=now,
                    )
                )

    # In replay nothing is written or sent — only previewed.
    if suppress:
        return {
            "created": [],
            "preview": [n.as_dict() for n in candidates],
            "suppressed": True,
            "reason": "replay",
            "policy_version": POLICY_VERSION,
        }

    # The first evaluation after a cold start seeds state without notifying, or
    # every pre-existing Needs-attention site would alert at once.
    first_run = seed_only if seed_only is not None else not _seeded
    _seeded = True

    created: list[dict] = []
    for candidate in candidates:
        if candidate.site_id is None:
            # System notices skip per-site hygiene; the daily cap already applied.
            if not first_run:
                store.insert(candidate)
                created.append(candidate.as_dict())
            continue

        previous = store.last_for(candidate.site_id, candidate.reason_code)
        if previous is not None:
            last_at = datetime.fromisoformat(previous["created_at"])
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            within_cooldown = now - last_at < timedelta(hours=settings.notify_cooldown_hours)
            escalated = (
                SEVERITY_RANK.get(candidate.severity, 0)
                > SEVERITY_RANK.get(previous["severity"], 0)
            )
            # Hysteresis: a site hovering on the threshold must have moved
            # meaningfully before it can speak again.
            previous_score = previous.get("priority_score") or 0.0
            current_score = candidate.priority_score or 0.0
            moved = abs(current_score - previous_score) >= settings.notify_hysteresis

            if within_cooldown and not escalated:
                continue
            if not escalated and not moved:
                continue

        if first_run:
            # Record it so the cooldown clock starts, but do not surface it.
            candidate.state = "resolved"
            candidate.resolved_at = now
            store.insert(candidate)
            continue

        store.insert(candidate)
        created.append(candidate.as_dict())

    return {
        "created": created,
        "preview": [],
        "suppressed": False,
        "seeded": first_run,
        "policy_version": POLICY_VERSION,
    }


def reset_seed_for_tests() -> None:
    global _seeded
    _seeded = False


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
def webhook_payload(notification: dict, link_base: str = "") -> dict:
    """Generic JSON whose `text` field Slack, Teams and Discord all render."""
    prefix = "[TEST] " if notification.get("is_test") else ""
    return {
        "text": f"{prefix}FIRETRACE · {notification['title']}",
        "firetrace": {
            "policy_version": notification.get("policy_version", POLICY_VERSION),
            "reason_code": notification["reason_code"],
            "severity": notification["severity"],
            "site_id": notification.get("site_id"),
            "site_name": notification.get("site_name"),
            "status": notification.get("status"),
            "verdict": notification.get("body"),
            "observed_at": notification.get("observed_at"),
            "link": (
                f"{link_base}/?site={notification['site_id']}"
                if link_base and notification.get("site_id")
                else None
            ),
            "is_test": bool(notification.get("is_test")),
            "replay": False,
        },
    }


def deliver_webhook(notification: dict, link_base: str = "") -> dict:
    """Send one notification outbound. Never raises; always records attempts."""
    url = settings.webhook_url
    if not url:
        return {"sent": False, "reason": "no webhook configured"}

    import httpx

    store = get_store()
    payload = webhook_payload(notification, link_base)
    attempts = max(1, settings.webhook_retries + 1)
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=settings.webhook_timeout_seconds) as client:
                response = client.post(url, json=payload)
            ok = 200 <= response.status_code < 300
            store.record_delivery(
                notification["id"], "webhook", attempt, ok, response.status_code,
                None if ok else response.text[:200],
            )
            if ok:
                return {"sent": True, "attempts": attempt, "status_code": response.status_code}
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - delivery must never crash a request
            last_error = type(exc).__name__
            store.record_delivery(notification["id"], "webhook", attempt, False, None, last_error)

        if attempt < attempts:
            time.sleep(settings.webhook_backoff_seconds * (2 ** (attempt - 1)))

    log.warning("[NOTIFY] webhook delivery failed after %d attempts: %s", attempts, last_error)
    return {"sent": False, "attempts": attempts, "error": last_error}


def policy_summary() -> dict:
    """Exposed by the API so the UI can show the policy it is operating under."""
    return {
        "policy_version": POLICY_VERSION,
        "reasons": [
            {"code": NEEDS_ATTENTION, "severity": "high",
             "when": "A site enters Needs attention, or escalates within it."},
            {"code": ABNORMAL_PERSISTENT, "severity": "high",
             "when": "A persistent source with an assessed baseline shows heat above its own history."},
            {"code": NEW_HEAT_AT_FACILITY, "severity": "medium",
             "when": "Heat on a mapped facility with no prior history there."},
            {"code": SYSTEM_FEED_DELAYED, "severity": "low",
             "when": f"The feed is more than {settings.notify_feed_delay_hours} h behind."},
            {"code": SYSTEM_WEBHOOK_FAILED, "severity": "low",
             "when": "A webhook delivery failed after all retries."},
        ],
        "never_notifies_for": ["normal", "watch", "not_sure"],
        "hygiene": {
            "cooldown_hours": settings.notify_cooldown_hours,
            "hysteresis": settings.notify_hysteresis,
            "system_daily_cap": settings.notify_system_daily_cap,
            "dedupe": "per site and reason code",
            "escalation_overrides_cooldown": True,
        },
        "channels": {
            "in_app": True,
            "toast": "high severity only",
            "browser": "opt-in, high severity only",
            "webhook": bool(settings.webhook_url),
        },
        "replay": "In Past data mode nothing is written or sent; a preview is shown instead.",
        "language_rule": (
            "A notification never claims a fire is confirmed. Heat is reported as "
            "detected, and facility proximity is stated as context, not cause."
        ),
    }

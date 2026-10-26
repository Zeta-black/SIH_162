"""Which date ranges FIRETRACE actually holds, and how fresh the feed is.

Two jobs, both in service of one rule: the interface may never present a date
range, or a freshness claim, that the data does not support.

The "Past data" picker is built from this module rather than from a constant.
Pass 1 had a hard-coded date in the chrome ("12 September"), which is exactly the
failure this prevents: a label that keeps saying the same thing after the data
underneath it has moved on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.schemas import HotspotEvent
from app.services import livecache
from app.services import snapshot as snapshot_service
from app.store.db import get_store

log = logging.getLogger("firetrace.timeline")

# A run of consecutive days shorter than this is noise rather than a period
# worth offering as a replay. Three days is the shortest span in which a
# persistent source can show a repeat and still be seen as a pattern.
MIN_RUN_DAYS = 3

# How stale the newest observation may be before the feed is called delayed.
# VIIRS gives 2-4 overpasses a day over India and FIRMS publishes a few hours
# behind the pass, so a quiet six hours is normal and twelve is not.
DELAYED_AFTER_HOURS = 12


def _month_abbr(d: date) -> str:
    return d.strftime("%b")


def human_range(start: date, end: date) -> str:
    """'1-10 Sep 2026' / '28 Feb - 3 Mar 2026' / '11 Nov 2025'.

    Written out rather than taken from a locale formatter so the label is the
    same in every environment, including the demo laptop.
    """
    if start == end:
        return f"{start.day} {_month_abbr(start)} {start.year}"
    if start.year != end.year:
        return f"{start.day} {_month_abbr(start)} {start.year} - {end.day} {_month_abbr(end)} {end.year}"
    if start.month != end.month:
        return f"{start.day} {_month_abbr(start)} - {end.day} {_month_abbr(end)} {end.year}"
    return f"{start.day}-{end.day} {_month_abbr(end)} {end.year}"


@dataclass
class DateRange:
    start: date
    end: date
    days: int
    detections: int

    def as_dict(self, kind: str = "archive") -> dict[str, object]:
        return {
            "id": f"{self.start.isoformat()}:{self.end.isoformat()}",
            "kind": kind,
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "label": human_range(self.start, self.end),
            "days": self.days,
            "detections": self.detections,
        }


def _runs(events: list[HotspotEvent]) -> list[DateRange]:
    """Group the days we hold into contiguous runs."""
    if not events:
        return []

    per_day: dict[date, int] = {}
    for event in events:
        day = getattr(event, "acquisition_date", None) or event.event.acquisition_date
        per_day[day] = per_day.get(day, 0) + 1

    days = sorted(per_day)
    runs: list[list[date]] = [[days[0]]]
    for previous, current in zip(days, days[1:]):
        if current - previous == timedelta(days=1):
            runs[-1].append(current)
        else:
            runs.append([current])

    out = [
        DateRange(
            start=run[0],
            end=run[-1],
            days=len(run),
            detections=sum(per_day[d] for d in run),
        )
        for run in runs
        if len(run) >= MIN_RUN_DAYS
    ]
    # Most recent first: a reader scanning the list wants the latest period.
    out.sort(key=lambda r: r.end, reverse=True)
    return out


def available_ranges() -> list[dict[str, object]]:
    """Every period the Past-data picker may offer, newest first.

    Generated from the data actually held — the frozen archive plus anything the
    local store has ingested. Nothing here is hard-coded, so the picker cannot
    advertise a week we do not have.
    """
    ranges: list[dict[str, object]] = []

    # Rolling windows first, but only when the store genuinely holds that much.
    store = get_store()
    newest = _store_newest_date()
    if newest is not None:
        for days, label in ((1, "Last 24 hours"), (7, "Last 7 days")):
            start = newest - timedelta(days=days - 1)
            count = store.count_between(start.isoformat(), newest.isoformat())
            if count > 0:
                ranges.append(
                    {
                        "id": f"rolling-{days}",
                        "kind": "rolling",
                        "from": start.isoformat(),
                        "to": newest.isoformat(),
                        "label": label,
                        "days": days,
                        "detections": count,
                    }
                )

    snap = snapshot_service.load_snapshot()
    if snap and snap.events:
        ranges.extend(run.as_dict("archive") for run in _runs(snap.events))

    return ranges


def _store_newest_date() -> date | None:
    try:
        newest = get_store().newest_event_date()
        return date.fromisoformat(newest) if newest else None
    except Exception:  # noqa: BLE001 - the picker must never break the page
        return None


def resolve_range(range_id: str | None) -> tuple[date, date] | None:
    """Turn a picker id back into real dates, or None if we do not hold it.

    Never trusts the client: an id for a period we do not have returns None and
    the caller falls back rather than rendering an empty week as if it were real.
    """
    if not range_id:
        return None

    for candidate in available_ranges():
        if candidate["id"] == range_id:
            return (
                date.fromisoformat(str(candidate["from"])),
                date.fromisoformat(str(candidate["to"])),
            )

    # Also accept a literal from:to, so a deep link keeps working after the
    # underlying runs shift — but only when we actually hold detections in it.
    # Accepting any well-formed span would let a link render an empty week as
    # though it were a real period, which is the whole failure this module
    # exists to prevent.
    if ":" in range_id:
        try:
            raw_start, raw_end = range_id.split(":", 1)
            start, end = date.fromisoformat(raw_start), date.fromisoformat(raw_end)
        except ValueError:
            return None
        if start > end:
            return None
        if _holds_detections(start, end):
            return start, end
    return None


def _holds_detections(start: date, end: date) -> bool:
    """Whether any stored or archived detection falls inside this span."""
    if get_store().count_between(start.isoformat(), end.isoformat()) > 0:
        return True
    snap = snapshot_service.load_snapshot()
    if snap and snap.events:
        return any(start <= e.acquisition_date <= end for e in snap.events)
    return False


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
def feed_freshness(
    events: list[HotspotEvent],
    resolved_mode: str,
    retrieved_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """How old what is on screen actually is.

    `observed_*` is when the satellite saw it. `retrieved_*` is when FIRETRACE
    asked. They are different facts and the interface shows both — the age is
    always real even when the label is reassuring.
    """
    now = now or datetime.now(timezone.utc)

    observed_at: datetime | None = None
    if events:
        # Accepts either a raw HotspotEvent or a ClassifiedEvent wrapping one,
        # because both shapes reach this from different callers.
        moments = [getattr(e, "acquired_at", None) or e.event.acquired_at for e in events]
        observed_at = max(moments)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

    def age_minutes(moment: datetime | None) -> int | None:
        if moment is None:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0, int((now - moment).total_seconds() // 60))

    observed_age = age_minutes(observed_at)
    retrieved_age = age_minutes(retrieved_at)

    return {
        "observed_at": observed_at.isoformat() if observed_at else None,
        "observed_age_minutes": observed_age,
        "retrieved_at": retrieved_at.isoformat() if retrieved_at else None,
        "retrieved_age_minutes": retrieved_age,
        "source": "NASA FIRMS VIIRS/MODIS near-real-time",
        # Said once, here, so no surface has to invent its own wording — and so
        # nothing can imply the detection is simultaneous with the fire.
        "latency_note": (
            "Detections are published a few hours after the satellite pass. "
            "FIRETRACE shows the observation time, not the time of the fire."
        ),
        "stale": (
            observed_age is not None and observed_age > DELAYED_AFTER_HOURS * 60
        ),
        "delayed_after_hours": DELAYED_AFTER_HOURS,
    }


def cached_feed_note() -> dict[str, object] | None:
    """Age of the on-disk last-good live fetch, when there is one."""
    cached = livecache.load()
    if cached is None:
        return None
    return {
        "cached_at": cached.cached_at.isoformat(),
        "age_minutes": cached.age_minutes,
        "events": len(cached.events),
    }

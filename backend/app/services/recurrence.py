"""Temporal / spatial recurrence features.

This is the part that separates a flare stack from a fire. A refinery flare
lights up the same pixel on most days; a crop fire appears for a day or two in
a seasonal window; a forest fire burns for a few days and never returns to
exactly that spot.

LEAKAGE RULE
------------
Every counter here is computed from detections that were already observable at
the moment the event under test was acquired:

* history counters use detections with acq_date STRICTLY BEFORE the event date;
* same-day density uses detections with acquired_at <= the event's acquired_at.

Nothing from the event's future is ever used, so features built for a
historical event during training match what the live pipeline can see at
inference time.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.config import settings
from app.schemas import HotspotEvent, RecurrenceResult
from app.services.geo import GridPoint, SpatialGrid

# A source seen on this many distinct days inside the window, and on this share
# of it, is flagged persistent. Prototype defaults, configurable, not validated
# against ground truth.
PERSISTENT_MIN_DISTINCT_DAYS = 5
PERSISTENT_MIN_RATIO = 0.25


class HistoryIndex:
    """Spatial index over historical detections, queried per event."""

    def __init__(self, events: list[HotspotEvent], cell_degrees: float = 0.1) -> None:
        self.grid = SpatialGrid(
            (GridPoint(lat=e.latitude, lon=e.longitude, payload=e) for e in events),
            cell_degrees=cell_degrees,
        )
        self.count = len(events)

    def __len__(self) -> int:
        return self.count

    def compute(
        self,
        event: HotspotEvent,
        radius_km: float | None = None,
        window_days: int | None = None,
        density_radius_km: float | None = None,
    ) -> RecurrenceResult:
        radius_km = radius_km if radius_km is not None else settings.recurrence_radius_km
        window_days = window_days if window_days is not None else settings.recurrence_lookback_days
        density_radius_km = (
            density_radius_km if density_radius_km is not None else settings.density_radius_km
        )

        if self.count == 0:
            return RecurrenceResult(
                recurrence_count=0,
                distinct_days=0,
                recent_count_7d=0,
                first_seen=None,
                last_seen_before_event=None,
                persistence_ratio=0.0,
                nearby_density=0,
                is_persistent=False,
                window_days=window_days,
                radius_km=radius_km,
                history_available=False,
            )

        window_start: date = event.acquisition_date - timedelta(days=window_days)
        recent_start: date = event.acquisition_date - timedelta(days=7)

        # --- recurrence at the same source ---------------------------------
        prior_dates: list[date] = []
        recurrence_count = 0
        recent_count = 0
        for point, _dist in self.grid.within(event.latitude, event.longitude, radius_km):
            other: HotspotEvent = point.payload  # type: ignore[assignment]
            if other.event_id == event.event_id:
                continue
            d = other.acquisition_date
            if d >= event.acquisition_date:  # strictly-before rule
                continue
            if d < window_start:
                continue
            recurrence_count += 1
            prior_dates.append(d)
            if d >= recent_start:
                recent_count += 1

        distinct = sorted(set(prior_dates))
        distinct_days = len(distinct)
        observed_span = max(1, min(window_days, (event.acquisition_date - (distinct[0] if distinct else event.acquisition_date)).days))
        persistence_ratio = round(distinct_days / observed_span, 4) if distinct_days else 0.0
        persistence_ratio = min(1.0, persistence_ratio)

        # --- co-detected density on the same pass --------------------------
        nearby_density = 0
        for point, _dist in self.grid.within(event.latitude, event.longitude, density_radius_km):
            other = point.payload  # type: ignore[assignment]
            if other.event_id == event.event_id:
                continue
            if other.acquisition_date != event.acquisition_date:
                continue
            if other.acquired_at > event.acquired_at:
                continue
            nearby_density += 1

        is_persistent = (
            distinct_days >= PERSISTENT_MIN_DISTINCT_DAYS
            and persistence_ratio >= PERSISTENT_MIN_RATIO
        )

        return RecurrenceResult(
            recurrence_count=recurrence_count,
            distinct_days=distinct_days,
            recent_count_7d=recent_count,
            first_seen=distinct[0] if distinct else None,
            last_seen_before_event=distinct[-1] if distinct else None,
            persistence_ratio=persistence_ratio,
            nearby_density=nearby_density,
            is_persistent=is_persistent,
            window_days=window_days,
            radius_km=radius_km,
            history_available=True,
        )

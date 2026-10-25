"""Fire-event clustering.

THE PROBLEM THIS SOLVES

A satellite does not see "a fire". It sees hot pixels. One fire burning for six
hours across three overpasses can produce a dozen separate FIRMS records, and
until this module existed the interface listed all twelve as if they were twelve
independent incidents. An operator would have had to work out by eye that they
were one thing, and the headline count of "900 detections" was not a count of
900 fires.

WHAT IT DOES

Detections are grouped into a FIRE EVENT when they are close enough in space and
time to be the same burning thing. The rule is deliberately simple enough to
state out loud:

    two detections belong to the same event if they are within
    EVENT_RADIUS_KM of each other AND within EVENT_WINDOW_HOURS of each other,
    and membership is transitive.

That last word matters: a fire front that creeps 4 km over a day still forms one
event, because each detection links to the next even though the endpoints are far
apart. This is single-linkage clustering, implemented with a union-find over a
neighbour graph built on the existing spatial index.

WHY NOT DBSCAN

scikit-learn is already a dependency, so DBSCAN was available. It was not used
because its `eps` is a single distance in one metric space, and this problem has
two incommensurable axes — kilometres and hours. Combining them means inventing a
conversion factor ("1 km equals how many minutes?") that has no physical meaning
and that nobody could defend under questioning. Two explicit thresholds are both
more honest and easier to explain.

THRESHOLDS

EVENT_RADIUS_KM = 1.5
    A VIIRS pixel is 375 m and a MODIS pixel is 1 km. Adjacent pixels of a single
    fire front therefore sit well inside 1.5 km, while two genuinely separate
    fires in the same district usually do not.

EVENT_WINDOW_HOURS = 12
    VIIRS gives roughly two to four overpasses per day over India. Twelve hours
    keeps consecutive passes of the same fire together without merging fires that
    happen to recur at the same spot several days apart — which is precisely the
    distinction the persistence feature depends on, so it must not be blurred.

Both are configurable and both are reported in the API response, so a reviewer
can see what produced a given grouping rather than having to trust it.
"""
from __future__ import annotations

import hashlib
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from app.config import settings
from app.schemas import ClassifiedEvent
from app.services.geo import GridPoint, SpatialGrid, centroid, haversine_km

log = logging.getLogger("firetrace.events")

EVENT_RADIUS_KM = 1.5
EVENT_WINDOW_HOURS = 12.0


class _UnionFind:
    """Disjoint-set over detection indices, with path compression."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


@dataclass
class FireEvent:
    """A group of detections judged to be one burning thing."""

    event_id: str
    latitude: float
    longitude: float
    detection_count: int
    first_detected: datetime
    last_detected: datetime
    duration_hours: float

    label: str
    label_display: str
    label_confidence: float
    label_agreement: float
    class_distribution: dict[str, int]

    priority_score: float
    priority_level: str

    frp_total_mw: float | None
    frp_max_mw: float | None
    brightness_max_k: float | None

    satellites: list[str]
    products: list[str]
    spread_km: float
    distinct_passes: int

    nearest_facility_name: str | None
    nearest_facility_km: float | None
    land_cover: str
    persistent: bool
    # How many distinct prior days this location was detected on, and whether a
    # history window was actually loaded. The verdict layer needs both: "no
    # prior detections" and "no history to check" are different statements and
    # must not collapse into one.
    distinct_days: int = 0
    history_available: bool = False
    # Kept separate from priority_score on purpose: "how unusual" and "how
    # urgently to look" are different questions. None = no baseline to judge
    # against, which is the honest answer for most of this archive.
    abnormality_score: int | None = None
    abnormality_status: str = "assessed"

    risk_factors: list[str] = field(default_factory=list)
    detection_ids: list[str] = field(default_factory=list)
    lead_detection_id: str = ""


def _event_id(first_seen: datetime, lat: float, lon: float) -> str:
    """Stable, readable identifier.

    Derived from the earliest detection and the centroid rather than from a
    counter, so re-running the same analysis produces the same event id and an
    operator's reference to "FE-2026-4A7C" keeps meaning the same thing.
    """
    seed = f"{first_seen.isoformat()}|{lat:.4f}|{lon:.4f}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:4].upper()
    return f"FE-{first_seen.year}-{digest}"


def cluster(
    classified: list[ClassifiedEvent],
    radius_km: float = EVENT_RADIUS_KM,
    window_hours: float = EVENT_WINDOW_HOURS,
) -> list[FireEvent]:
    """Group classified detections into fire events."""
    if not classified:
        return []

    n = len(classified)
    uf = _UnionFind(n)

    # A spatial index keeps this near-linear instead of comparing every pair.
    grid = SpatialGrid(
        (
            GridPoint(lat=c.event.latitude, lon=c.event.longitude, payload=i)
            for i, c in enumerate(classified)
        ),
        cell_degrees=0.05,
    )

    window_seconds = window_hours * 3600.0
    for i, item in enumerate(classified):
        for point, _distance in grid.within(item.event.latitude, item.event.longitude, radius_km):
            j: int = point.payload  # type: ignore[assignment]
            if j <= i:
                continue
            gap = abs((classified[j].event.acquired_at - item.event.acquired_at).total_seconds())
            if gap <= window_seconds:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    events = [_summarise([classified[i] for i in members]) for members in groups.values()]
    events.sort(key=lambda e: e.priority_score, reverse=True)

    log.info(
        "[EVENTS] %d detections grouped into %d events (radius=%.1fkm window=%.0fh)",
        n,
        len(events),
        radius_km,
        window_hours,
    )
    return events


def _summarise(members: list[ClassifiedEvent]) -> FireEvent:
    """Roll a group of detections up into one event record."""
    members = sorted(members, key=lambda c: c.event.acquired_at)
    first, last = members[0], members[-1]

    lats = [m.event.latitude for m in members]
    lons = [m.event.longitude for m in members]
    centre = centroid(list(zip(lats, lons))) or (lats[0], lons[0])

    duration = (last.event.acquired_at - first.event.acquired_at).total_seconds() / 3600.0

    # Widest separation inside the group — how far the thing has spread.
    spread = 0.0
    if len(members) > 1:
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                spread = max(
                    spread,
                    haversine_km(lats[i], lons[i], lats[j], lons[j]),
                )

    # Class of the event: the class its members carry the most *confidence* in,
    # not a plain majority. Ten low-confidence guesses should not outvote three
    # confident ones.
    weights: dict[str, float] = {}
    counts: dict[str, int] = {}
    for m in members:
        label = m.classification.label
        weights[label] = weights.get(label, 0.0) + m.classification.confidence
        counts[label] = counts.get(label, 0) + 1
    label = max(weights, key=weights.get) if weights else "UNKNOWN"
    lead = max(
        (m for m in members if m.classification.label == label),
        key=lambda m: m.classification.confidence,
        default=members[0],
    )
    agreement = counts.get(label, 0) / len(members)

    # An event is as urgent as its most urgent detection.
    top = max(members, key=lambda m: m.priority.score)

    frps = [m.event.frp_mw for m in members if m.event.frp_mw is not None]
    brights = [m.event.brightness_k for m in members if m.event.brightness_k is not None]

    facility_holder = min(
        (m for m in members if m.evidence.nearest_facility),
        key=lambda m: m.evidence.nearest_facility.distance_km,  # type: ignore[union-attr]
        default=None,
    )
    land_covers = [
        m.evidence.land_cover.label
        for m in members
        if m.evidence.land_cover.category != "unknown"
    ]

    passes = len({(m.event.acquisition_date, m.event.acquisition_time) for m in members})

    return FireEvent(
        event_id=_event_id(first.event.acquired_at, centre[0], centre[1]),
        latitude=round(centre[0], 5),
        longitude=round(centre[1], 5),
        detection_count=len(members),
        first_detected=first.event.acquired_at,
        last_detected=last.event.acquired_at,
        duration_hours=round(duration, 2),
        label=label,
        label_display=lead.classification.label_display,
        label_confidence=round(lead.classification.confidence, 4),
        label_agreement=round(agreement, 3),
        class_distribution=counts,
        priority_score=top.priority.score,
        priority_level=top.priority.level,
        frp_total_mw=round(sum(frps), 2) if frps else None,
        frp_max_mw=round(max(frps), 2) if frps else None,
        brightness_max_k=round(max(brights), 1) if brights else None,
        satellites=sorted({m.event.satellite for m in members if m.event.satellite}),
        products=sorted({m.event.source_product for m in members}),
        spread_km=round(spread, 2),
        distinct_passes=passes,
        nearest_facility_name=(
            (facility_holder.evidence.nearest_facility.name
             or facility_holder.evidence.nearest_facility.category_label)
            if facility_holder
            else None
        ),
        nearest_facility_km=(
            facility_holder.evidence.distance_to_nearest_facility_km if facility_holder else None
        ),
        land_cover=(
            statistics.mode(land_covers) if land_covers else "Not mapped in OpenStreetMap"
        ),
        persistent=any(m.evidence.recurrence.is_persistent for m in members),
        distinct_days=max((m.evidence.recurrence.distinct_days for m in members), default=0),
        history_available=any(m.evidence.recurrence.history_available for m in members),
        abnormality_score=top.priority.abnormality_score,
        abnormality_status=top.priority.abnormality_status,
        risk_factors=_risk_factors(members, top, spread, duration, frps, facility_holder),
        detection_ids=[m.event.event_id for m in members],
        lead_detection_id=lead.event.event_id,
    )


def _risk_factors(members, top, spread, duration, frps, facility_holder) -> list[str]:
    """Plain-language reasons this event scored the way it did.

    Every line is generated from a measured value on the event. Nothing here is
    a template sentence that appears regardless of the data — if the condition
    does not hold, the line is not produced.
    """
    reasons: list[str] = []
    count = len(members)

    if count > 1:
        minutes = duration * 60
        if duration >= 1:
            reasons.append(f"{count} satellite detections over {duration:.1f} h")
        elif minutes >= 1:
            reasons.append(f"{count} satellite detections over {minutes:.0f} min")
        else:
            # Same overpass: several adjacent hot pixels, not a span of time.
            # Rendering this as "over 0 min" was wrong on 54 of 390 sites.
            reasons.append(f"{count} adjacent hot pixels in a single overpass")
    else:
        reasons.append("Single detection — no corroborating pass yet")

    passes = len({(m.event.acquisition_date, m.event.acquisition_time) for m in members})
    if passes > 1:
        reasons.append(f"Confirmed across {passes} separate satellite passes")

    sats = {m.event.satellite for m in members if m.event.satellite}
    if len(sats) > 1:
        reasons.append(f"Seen by {len(sats)} different platforms ({', '.join(sorted(sats))})")

    if spread >= 1.0:
        reasons.append(f"Spread across {spread:.1f} km")

    if frps:
        peak = max(frps)
        if peak >= 15:
            reasons.append(f"Peak radiative power {peak:.0f} MW")
        total = sum(frps)
        if total >= 50:
            reasons.append(f"Combined radiative power {total:.0f} MW")

    if facility_holder is not None:
        d = facility_holder.evidence.distance_to_nearest_facility_km
        name = (
            facility_holder.evidence.nearest_facility.name
            or facility_holder.evidence.nearest_facility.category_label
        )
        if d is not None and d <= settings.facility_onsite_km:
            reasons.append(f"On the footprint of {name} ({d * 1000:.0f} m)")
        elif d is not None and d <= 3.0:
            reasons.append(f"{d:.2f} km from {name}")

    if any(m.evidence.recurrence.is_persistent for m in members):
        days = max(m.evidence.recurrence.distinct_days for m in members)
        reasons.append(f"Recurring source — detected on {days} separate days")
    elif all(m.evidence.recurrence.distinct_days == 0 for m in members if m.evidence.recurrence.history_available):
        reasons.append("No previous detection at this location")

    lc = [m.evidence.land_cover.label for m in members if m.evidence.land_cover.category != "unknown"]
    if lc:
        reasons.append(f"Land cover: {statistics.mode(lc)}")

    if top.classification.abstained:
        reasons.append("Model abstained — evidence insufficient to assert a class")

    return reasons


def config_summary() -> dict[str, object]:
    """Exposed by the API so the grouping rule is visible, not implied."""
    return {
        "radius_km": EVENT_RADIUS_KM,
        "window_hours": EVENT_WINDOW_HOURS,
        "method": "single-linkage spatio-temporal clustering (union-find)",
        "rule": (
            f"Two detections join the same event if they are within "
            f"{EVENT_RADIUS_KM} km AND {EVENT_WINDOW_HOURS} h of each other. "
            "Membership is transitive, so a creeping fire front stays one event."
        ),
        "why_not_dbscan": (
            "DBSCAN needs a single eps in one metric space. Space and time are not "
            "commensurable, and combining them requires inventing a km-per-hour "
            "conversion with no physical meaning. Two explicit thresholds are more "
            "defensible and easier to state."
        ),
        "pixel_note": "VIIRS pixel 375 m, MODIS 1 km — adjacent pixels of one front fall well inside the radius.",
    }

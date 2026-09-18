"""Orchestration: Detect -> Analyse -> Classify -> Visualise -> Monitor.

This module is the one place that knows the whole flow. Everything it calls is
independently testable, and every external dependency it touches is allowed to
fail without taking the request down:

    FIRMS unreachable   -> fall back to the frozen snapshot
    Overpass unreachable-> fall back to cached, then stored, then no facilities
    land-use unreachable-> land cover reported as "unknown", never guessed
    model missing       -> every event reported as Unclassified, UI still works

The result of a full analysis is cached briefly, because a dashboard that
polls should not re-query NASA on every render.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.config import settings
from app.schemas import (
    ClassifiedEvent,
    DataSourceStatus,
    Evidence,
    Facility,
    HotspotEvent,
    LandCoverResult,
    NearestFacility,
    SummaryCounts,
)
from app.services import firms as firms_service
from app.services import landcover as landcover_service
from app.services import osm as osm_service
from app.services import snapshot as snapshot_service
from app.services.classifier import DISCLAIMER, INDUSTRIAL_RELATED, get_classifier
from app.services.geo import GridPoint, SpatialGrid, parse_bbox
from app.services.priority import compute_priority
from app.services.recurrence import HistoryIndex
from app.store.db import get_store
from app.taxonomy import ALL_CLASSES, FACILITY_LABELS, UNKNOWN

log = logging.getLogger("firetrace.pipeline")

# Analysing every detection in a country-sized bbox would make the dashboard
# crawl. The most significant events are kept: strongest radiative power and
# most recent first.
MAX_ANALYSED_EVENTS = 900
# Local explanations are by far the most expensive step: walking every tree's
# decision path costs ~0.11s per event, measured, against 0.19s to SCORE all
# 716 snapshot events at once. Explaining 220 of them added ~25s to every
# request for reasons nobody had asked to see yet.
#
# So only the handful shown on the overview are explained up front; the detail
# endpoint explains the one event a user actually opened.
MAX_EXPLAINED_EVENTS = 12


@dataclass
class AnalysisResult:
    events: list[ClassifiedEvent] = field(default_factory=list)
    status: DataSourceStatus | None = None
    facilities: list[Facility] = field(default_factory=list)
    built_at: float = 0.0
    bbox: tuple[float, float, float, float] | None = None


class _Cache:
    """Small TTL cache so repeated dashboard loads do not re-hit NASA."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, AnalysisResult] = {}

    def get(self, key: str, ttl_seconds: float) -> AnalysisResult | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry and (time.time() - entry.built_at) <= ttl_seconds:
                return entry
            return None

    def put(self, key: str, value: AnalysisResult) -> None:
        with self._lock:
            self._entries[key] = value
            # Keep the cache small; this is a single-laptop prototype.
            if len(self._entries) > 12:
                oldest = min(self._entries, key=lambda k: self._entries[k].built_at)
                self._entries.pop(oldest, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _Cache()


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------
def _acquire_events(
    bbox: tuple[float, float, float, float],
    days: int,
    mode: str,
) -> tuple[list[HotspotEvent], str, str, str, list[str]]:
    """Return (events, resolved_mode, firms_status, firms_message, products).

    `mode` is one of auto | live | demo.
    """
    store = get_store()
    firms_failure_kind: str | None = None
    firms_failure_message: str | None = None

    if mode != "demo":
        try:
            client = firms_service.FirmsClient()
            result = client.fetch_area(bbox=bbox, day_range=days)
            if result.events:
                store.upsert_events(result.events)
                store.record_ingest(
                    "live",
                    ",".join(f"{c:.2f}" for c in bbox),
                    result.products_used,
                    len(result.events),
                    "; ".join(result.errors)[:400],
                )
                message = f"Live NASA FIRMS feed, {len(result.events)} detections in the last {days} day(s)."
                if result.errors:
                    message += f" {len(result.errors)} product(s) unavailable."
                return result.events, "live", "ok", message, result.products_used

            # A valid FIRMS response with no usable rows is a successful live
            # query, not an outage. This applies to Auto as well as explicit
            # Live mode: only an actual client failure may select the snapshot.
            return (
                [],
                "live",
                "no_data",
                f"NASA FIRMS returned no detections in this area for the last {days} day(s).",
                result.products_used,
            )
        except firms_service.FirmsError as exc:
            if mode == "live":
                return [], "live", exc.kind, str(exc), []  # type: ignore[return-value]
            firms_failure_kind = exc.kind
            firms_failure_message = str(exc)
            log.warning("[FALLBACK] FIRMS unavailable (%s); demo mode activated", exc)
        except Exception as exc:  # noqa: BLE001
            if mode == "live":
                return [], "live", "unavailable", f"FIRMS request failed ({type(exc).__name__}).", []
            log.warning("[FALLBACK] FIRMS error %s; demo mode activated", type(exc).__name__)

    snap = snapshot_service.load_snapshot()
    if snap is None or not snap.events:
        return (
            [],
            "snapshot",
            "unavailable",
            "No live FIRMS data and no demo snapshot is present. "
            "Run `python -m ml.build_snapshot` to create one.",
            [],
        )

    products = sorted({e.source_product for e in snap.events})
    if mode == "demo":
        message = "Demo mode selected. Showing the frozen historical snapshot."
        status = "ok"
    elif firms_failure_kind == "not_configured":
        message = (
            f"{firms_failure_message} Showing the historical snapshot instead."
        )
        status = "not_configured"
    elif not settings.has_firms_key:
        message = "NASA FIRMS key is not configured, so FIRETRACE is using the historical snapshot."
        status = "not_configured"
    else:
        message = (
            "Live FIRMS data is currently unavailable. FIRETRACE has switched to "
            "Demo/Historical mode so the analysis workflow remains available."
        )
        status = "unavailable"
    return snap.events, "snapshot", status, message, products


def _acquire_facilities(
    bbox: tuple[float, float, float, float],
    resolved_mode: str,
    points: list[tuple[float, float]],
) -> tuple[list[Facility], str, str]:
    """Return (facilities, status, message).

    Facilities are fetched for the tiles the detections actually fall in, not
    for the whole area of interest. Querying Overpass for a country-sized box
    is a request it will not answer.
    """
    store = get_store()
    snap = snapshot_service.load_snapshot()

    if resolved_mode == "live" and points:
        try:
            facilities, status = osm_service.fetch_facilities_for_points(
                points, budget_seconds=settings.osm_live_budget_seconds
            )
            if facilities:
                store.upsert_facilities(facilities)
                msg = (
                    f"{len(facilities)} industrial features from OpenStreetMap"
                    + (" (cached)" if status == "cached" else " (Overpass)")
                    + "."
                )
                return facilities, status, msg
        except Exception as exc:  # noqa: BLE001
            log.warning("[OSM] facility fetch failed: %s", type(exc).__name__)

    stored = store.load_facilities(bbox)
    if stored:
        return (
            stored,
            "cached",
            f"{len(stored)} industrial features from the local OpenStreetMap cache.",
        )

    if snap and snap.facilities:
        return (
            snap.facilities,
            "snapshot",
            f"{len(snap.facilities)} industrial features from the frozen OpenStreetMap snapshot.",
        )

    return [], "unavailable", "No OpenStreetMap facility data available for this area."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_analysis(
    bbox_str: str | None = None,
    days: int = settings.firms_default_day_range,
    mode: str = "auto",
    force_refresh: bool = False,
) -> AnalysisResult:
    """Fetch, enrich, classify and prioritise hotspots for an area."""
    bbox = parse_bbox(bbox_str or settings.firms_default_bbox)
    days = max(1, min(int(days), settings.firms_max_day_range))
    mode = mode if mode in {"auto", "live", "demo"} else "auto"

    cache_key = f"{bbox}|{days}|{mode}"
    if not force_refresh:
        cached = _cache.get(cache_key, settings.live_cache_ttl_minutes * 60)
        if cached is not None:
            log.debug("[PIPELINE] serving cached analysis for %s", cache_key)
            return cached

    started = time.time()
    events, resolved_mode, firms_status, firms_message, products = _acquire_events(bbox, days, mode)

    # Analysis is limited to the most significant detections, so geographic
    # context only needs to be gathered where those actually are.
    analysed = _select_events(events, MAX_ANALYSED_EVENTS)
    points = [(e.latitude, e.longitude) for e in analysed]

    facilities, osm_status, osm_message = _acquire_facilities(bbox, resolved_mode, points)

    snap = snapshot_service.load_snapshot()
    provider, provider_name = landcover_service.build_provider(
        points if resolved_mode == "live" else None,
        snapshot_polygons=snap.landuse if snap else None,
        allow_network=(resolved_mode == "live"),
    )

    # History for recurrence. In live mode that is everything ingested into the
    # store so far; in snapshot mode it is the snapshot's own multi-day window.
    if resolved_mode == "live":
        history_since = date.today() - timedelta(days=settings.recurrence_lookback_days)
        history = get_store().load_events(bbox=bbox, since=history_since)
        if len(history) < len(events):
            history = events  # store unavailable; at least use what we fetched
    else:
        history = events

    history_index = HistoryIndex(history)
    facility_grid = SpatialGrid(
        (GridPoint(lat=f.latitude, lon=f.longitude, payload=f) for f in facilities),
        cell_degrees=0.1,
    )

    log.info(
        "[PIPELINE] mode=%s events=%d analysed=%d facilities=%d history=%d landcover=%s",
        resolved_mode,
        len(events),
        len(analysed),
        len(facilities),
        len(history_index),
        provider_name,
    )

    enriched: list[tuple[HotspotEvent, NearestFacility | None, LandCoverResult, object]] = []
    for event in analysed:
        nearest = _nearest_facility(facility_grid, event)
        land_cover = provider.lookup(event.latitude, event.longitude)
        recurrence = history_index.compute(event)
        enriched.append((event, nearest, land_cover, recurrence))

    classifier = get_classifier()
    model_info = classifier.info()

    # Score everything in one vectorised call, explain only what will be shown.
    scored = classifier.predict_batch(enriched, explain=False)  # type: ignore[arg-type]

    classified: list[ClassifiedEvent] = []
    for (event, nearest, land_cover, recurrence), (classification, probabilities, _) in zip(
        enriched, scored
    ):
        priority = compute_priority(event, classification, nearest, recurrence)  # type: ignore[arg-type]
        classified.append(
            ClassifiedEvent(
                event=event,
                classification=classification,
                probabilities=probabilities,
                evidence=Evidence(
                    distance_to_nearest_facility_km=(
                        round(nearest.distance_km, 3) if nearest else None
                    ),
                    nearest_facility=nearest,
                    land_cover=land_cover,
                    recurrence=recurrence,  # type: ignore[arg-type]
                    thermal_intensity_k=event.brightness_k,
                    frp_mw=event.frp_mw,
                    firms_confidence=event.firms_confidence_level,
                    day_night=event.day_night,
                ),
                factors=[],
                priority=priority,
                model=model_info,
                disclaimer=DISCLAIMER,
            )
        )

    classified.sort(key=lambda c: c.priority.score, reverse=True)

    # Explain the top slice now; the rest are explained on demand when opened.
    for item in classified[:MAX_EXPLAINED_EVENTS]:
        item.factors = classifier.explain_one(
            item.event,
            item.evidence.nearest_facility,
            item.evidence.land_cover,
            item.evidence.recurrence,
            item.classification.top_trained_label,
            item.classification.abstained,
        )

    status = DataSourceStatus(
        mode="live" if resolved_mode == "live" else "snapshot",
        label="Live NASA FIRMS" if resolved_mode == "live" else "Demo / Historical Data",
        firms_status=firms_status,  # type: ignore[arg-type]
        firms_message=firms_message,
        firms_products_used=products,
        osm_status=osm_status,  # type: ignore[arg-type]
        osm_message=osm_message,
        land_cover_provider=provider_name,
        last_updated=datetime.now(timezone.utc),
        snapshot_note=(snap.note if snap and resolved_mode == "snapshot" else None),
    )

    result = AnalysisResult(
        events=classified,
        status=status,
        facilities=facilities,
        built_at=time.time(),
        bbox=bbox,
    )
    _cache.put(cache_key, result)
    log.info("[PIPELINE] analysis complete in %.2fs", time.time() - started)
    return result


def _select_events(events: list[HotspotEvent], limit: int) -> list[HotspotEvent]:
    """Keep the most significant detections when there are too many.

    Sorted by recency first and radiative power second, so a country-wide query
    still surfaces the events an operator would care about rather than an
    arbitrary slice.
    """
    if len(events) <= limit:
        return list(events)
    ranked = sorted(
        events,
        key=lambda e: (e.acquired_at, e.frp_mw if e.frp_mw is not None else 0.0),
        reverse=True,
    )
    return ranked[:limit]


def _nearest_facility(grid: SpatialGrid, event: HotspotEvent) -> NearestFacility | None:
    if len(grid) == 0:
        return None
    point, distance = grid.nearest(
        event.latitude, event.longitude, settings.facility_search_radius_km
    )
    if point is None or distance is None:
        return None
    facility: Facility = point.payload  # type: ignore[assignment]
    return NearestFacility(
        facility_id=facility.facility_id,
        name=facility.name,
        category=facility.category,
        category_label=FACILITY_LABELS.get(facility.category, facility.category),
        latitude=facility.latitude,
        longitude=facility.longitude,
        distance_km=round(distance, 3),
    )


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def summarise(events: list[ClassifiedEvent]) -> SummaryCounts:
    by_class = {cls: 0 for cls in ALL_CLASSES}
    by_priority = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    industrial = 0
    high_priority = 0
    low_confidence = 0
    persistent = 0
    frp_total = 0.0
    dates: list[str] = []

    for item in events:
        label = item.classification.label
        by_class[label] = by_class.get(label, 0) + 1
        by_priority[item.priority.level] = by_priority.get(item.priority.level, 0) + 1
        if label in INDUSTRIAL_RELATED:
            industrial += 1
        if item.priority.level == "HIGH":
            high_priority += 1
        if item.classification.confidence_level == "LOW" or label == UNKNOWN:
            low_confidence += 1
        if item.evidence.recurrence.is_persistent:
            persistent += 1
        if item.event.frp_mw:
            frp_total += item.event.frp_mw
        dates.append(item.event.acquisition_date.isoformat())

    return SummaryCounts(
        total_events=len(events),
        industrial_related=industrial,
        high_priority=high_priority,
        low_confidence=low_confidence,
        persistent_sources=persistent,
        by_class=by_class,
        by_priority=by_priority,
        frp_total_mw=round(frp_total, 2),
        date_range={
            "from": min(dates) if dates else None,
            "to": max(dates) if dates else None,
        },
    )

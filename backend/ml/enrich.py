"""Shared enrichment for the offline scripts.

`build_dataset.py` and `build_snapshot.py` both need the same thing: take raw
FIRMS detections for a region and attach the facility, land-cover and
recurrence context. That work is done here, using exactly the same services the
live API uses, so an offline-built training row is constructed the same way a
live prediction is.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.schemas import Facility, HotspotEvent, LandCoverResult, NearestFacility, RecurrenceResult
from app.services import osm as osm_service
from app.services.geo import GridPoint, SpatialGrid
from app.services.landcover import OsmLanduseProvider, unknown_result
from app.services.osm import LandusePolygon
from app.services.pipeline import _nearest_facility
from app.services.recurrence import HistoryIndex

log = logging.getLogger("firetrace.enrich")

# Politeness delay between Overpass calls. The public instances are donated
# infrastructure; hammering them is both rude and a good way to get blocked.
OVERPASS_DELAY_SECONDS = 2.0


@dataclass
class RegionContext:
    facilities: list[Facility]
    landuse: list[LandusePolygon]
    facility_status: str
    landuse_status: str


@dataclass
class EnrichedEvent:
    event: HotspotEvent
    nearest_facility: NearestFacility | None
    land_cover: LandCoverResult
    recurrence: RecurrenceResult


def load_region_context(
    bbox: tuple[float, float, float, float],
    polite: bool = True,
    cache_only: bool = False,
) -> RegionContext:
    """Fetch (or reuse cached) OSM facilities and land-use polygons for a region.

    `cache_only` makes an offline rebuild genuinely offline. Without it a
    tile that was never cached costs three mirror timeouts before it gives
    up, which turns a supposedly local rebuild into a very slow one.
    """
    facilities: list[Facility] = []
    landuse: list[LandusePolygon] = []
    fac_status = "unavailable"
    lu_status = "unavailable"

    try:
        facilities, fac_status = osm_service.fetch_facilities(bbox, cache_only=cache_only)
    except Exception as exc:  # noqa: BLE001
        log.warning("  facilities failed: %s", type(exc).__name__)

    if polite and fac_status == "ok":
        time.sleep(OVERPASS_DELAY_SECONDS)

    try:
        landuse, lu_status = osm_service.fetch_landuse(bbox, cache_only=cache_only)
    except Exception as exc:  # noqa: BLE001
        log.warning("  land-use failed: %s", type(exc).__name__)

    if polite and lu_status == "ok":
        time.sleep(OVERPASS_DELAY_SECONDS)

    return RegionContext(facilities, landuse, fac_status, lu_status)


def enrich_events(
    events: list[HotspotEvent],
    context: RegionContext,
    history: list[HotspotEvent] | None = None,
) -> list[EnrichedEvent]:
    """Attach facility, land-cover and recurrence context to each detection.

    `history` defaults to the events themselves, which is correct here: the
    recurrence calculation only ever looks at detections strictly earlier than
    the one being enriched, so passing the full set does not leak the future
    into a row.
    """
    history = history if history is not None else events

    facility_grid = SpatialGrid(
        (GridPoint(lat=f.latitude, lon=f.longitude, payload=f) for f in context.facilities),
        cell_degrees=0.1,
    )
    provider = OsmLanduseProvider(context.landuse) if context.landuse else None
    history_index = HistoryIndex(history)

    out: list[EnrichedEvent] = []
    for event in events:
        nearest = _nearest_facility(facility_grid, event) if len(facility_grid) else None
        land_cover = (
            provider.lookup(event.latitude, event.longitude) if provider else unknown_result()
        )
        recurrence = history_index.compute(event)
        out.append(EnrichedEvent(event, nearest, land_cover, recurrence))
    return out

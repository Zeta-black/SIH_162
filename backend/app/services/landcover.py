"""Land-cover context.

IMPORTANT — what this is and is not.

FIRETRACE does not classify land cover from satellite reflectance. It reads
land-use and natural-area polygons that OpenStreetMap contributors have mapped
and asks which one contains the hotspot. That is a *cartographic* land-cover
proxy, not a spectral product, and every result says so in `source_note` so the
dashboard cannot imply otherwise.

The service is pluggable: `OsmLanduseProvider` queries Overpass live (with
caching), `SnapshotLanduseProvider` replays polygons frozen into the demo
snapshot, and `UnavailableProvider` returns an honest "unknown" so the rest of
the pipeline keeps working when neither is reachable.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.config import settings
from app.schemas import LandCoverResult
from app.services import osm
from app.services.osm import LandusePolygon, point_in_ring
from app.taxonomy import LAND_COVER_LABELS, LC_UNKNOWN

log = logging.getLogger("firetrace.landcover")

OSM_NOTE = (
    "Derived from OpenStreetMap land-use/natural polygons containing this point. "
    "Cartographic proxy, not a satellite land-cover classification."
)
SNAPSHOT_NOTE = (
    "From the frozen demo snapshot of OpenStreetMap land-use polygons. "
    "Cartographic proxy, not a satellite land-cover classification."
)
UNAVAILABLE_NOTE = (
    "No land-use polygon covers this point in OpenStreetMap, or the land-use "
    "source was unreachable. Treated as unknown rather than guessed."
)


def unknown_result(note: str = UNAVAILABLE_NOTE, provider: str = "unavailable") -> LandCoverResult:
    return LandCoverResult(
        category=LC_UNKNOWN,
        label=LAND_COVER_LABELS[LC_UNKNOWN],
        provider=provider,  # type: ignore[arg-type]
        source_note=note,
        matched_osm_tag=None,
    )


class LandCoverProvider(Protocol):
    name: str

    def lookup(self, lat: float, lon: float) -> LandCoverResult: ...


class PolygonProvider:
    """Shared point-in-polygon logic over a list of land-use polygons."""

    name = "polygon"
    note = OSM_NOTE
    provider_id = "osm_landuse"

    def __init__(self, polygons: list[LandusePolygon]) -> None:
        # Smallest polygon first: a factory inside an industrial estate should
        # win over the estate, and a wood inside a district over the district.
        self.polygons = sorted(polygons, key=lambda p: p.area_deg2)

    def lookup(self, lat: float, lon: float) -> LandCoverResult:
        for poly in self.polygons:
            # Cheap bbox rejection before the full ray cast.
            if not (poly.min_lat <= lat <= poly.max_lat and poly.min_lon <= lon <= poly.max_lon):
                continue
            if point_in_ring(lat, lon, poly.ring):
                return LandCoverResult(
                    category=poly.category,
                    label=LAND_COVER_LABELS.get(poly.category, poly.category),
                    provider=self.provider_id,  # type: ignore[arg-type]
                    source_note=self.note,
                    matched_osm_tag=poly.tag,
                )
        return unknown_result()


class OsmLanduseProvider(PolygonProvider):
    name = "osm_landuse"
    note = OSM_NOTE
    provider_id = "osm_landuse"


class SnapshotLanduseProvider(PolygonProvider):
    name = "snapshot"
    note = SNAPSHOT_NOTE
    provider_id = "snapshot"


class UnavailableProvider:
    name = "unavailable"

    def lookup(self, lat: float, lon: float) -> LandCoverResult:
        return unknown_result()


def build_provider(
    points: list[tuple[float, float]] | None,
    snapshot_polygons: list[LandusePolygon] | None = None,
    allow_network: bool = True,
) -> tuple[LandCoverProvider, str]:
    """Pick the best land-cover provider available for a set of detections.

    Takes the detection POINTS rather than a bounding box on purpose: land-use
    polygons are only ever needed where hotspots actually are, and tiling a
    whole area of interest would mean thousands of Overpass queries for a
    country-sized view.

    Returns (provider, provider_name). Never raises: an unreachable Overpass
    degrades to the snapshot, and an absent snapshot degrades to "unknown".
    """
    if allow_network and points:
        try:
            polygons, status = osm.fetch_landuse_for_points(
                points, budget_seconds=settings.osm_live_budget_seconds
            )
            if polygons:
                log.info(
                    "[LANDCOVER] provider=osm_landuse polygons=%d status=%s",
                    len(polygons),
                    status,
                )
                return OsmLanduseProvider(polygons), "osm_landuse"
        except Exception as exc:  # noqa: BLE001 - never fatal
            log.warning("[LANDCOVER] OSM land-use lookup failed: %s", type(exc).__name__)

    if snapshot_polygons:
        log.info("[LANDCOVER] provider=snapshot polygons=%d", len(snapshot_polygons))
        return SnapshotLanduseProvider(snapshot_polygons), "snapshot"

    log.info("[LANDCOVER] provider=unavailable")
    return UnavailableProvider(), "unavailable"

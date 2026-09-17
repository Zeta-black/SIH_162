"""OpenStreetMap geographic context via the Overpass API.

Two things are pulled from OSM:

1. Industrial facilities (refineries, power plants, works, mines, ...) used for
   the distance-to-facility feature.
2. Land-use / natural polygons used by the land-cover service.

Public Overpass instances are a shared free resource, so this module is
deliberately frugal with them: requests snap to a tile grid so nearby areas
reuse one request, every response is cached on disk for a week, and mirrors are
tried in order so a failure degrades to cache rather than to a crash.

Two Overpass behaviours here were found by testing against the live API, not
assumed, and both were silently destroying the land-cover layer:

* `out tags geom` does NOT expand relation members. Every large forest in
  India is mapped as a multipolygon *relation*, so they all came back with no
  geometry and no hotspot ever landed in one. `out geom` returns tags and
  member geometry both.
* Overpass truncates at the element cap in arbitrary order, so a single query
  over a whole region can return thousands of polygons clustered in one corner
  and leave the rest with zero coverage. Land-use is therefore fetched in small
  tiles that each stay well under the cap.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import CACHE_DIR, settings
from app.schemas import Facility
from app.services.geo import snap_bbox_to_grid
from app.taxonomy import FACILITY_LABELS

log = logging.getLogger("firetrace.osm")

FACILITY_CACHE = CACHE_DIR / "osm_facilities"
LANDUSE_CACHE = CACHE_DIR / "osm_landuse"

# Land-use / natural tag values mapped onto FIRETRACE land-cover categories.
LANDUSE_TO_CATEGORY: dict[tuple[str, str], str] = {
    ("landuse", "industrial"): "industrial_builtup",
    ("landuse", "port"): "industrial_builtup",
    ("landuse", "railway"): "industrial_builtup",
    ("landuse", "quarry"): "bare_open",
    ("landuse", "brownfield"): "bare_open",
    ("landuse", "landfill"): "bare_open",
    ("landuse", "farmland"): "cropland",
    ("landuse", "farmyard"): "cropland",
    ("landuse", "orchard"): "cropland",
    ("landuse", "vineyard"): "cropland",
    ("landuse", "plantation"): "cropland",
    ("landuse", "paddy"): "cropland",
    ("landuse", "forest"): "forest_vegetation",
    ("landuse", "meadow"): "grassland_scrub",
    ("landuse", "grass"): "grassland_scrub",
    ("landuse", "residential"): "urban_residential",
    ("landuse", "commercial"): "urban_residential",
    ("landuse", "retail"): "urban_residential",
    ("landuse", "reservoir"): "water",
    ("landuse", "basin"): "water",
    ("natural", "wood"): "forest_vegetation",
    ("natural", "forest"): "forest_vegetation",
    ("natural", "scrub"): "grassland_scrub",
    ("natural", "heath"): "grassland_scrub",
    ("natural", "grassland"): "grassland_scrub",
    ("natural", "water"): "water",
    ("natural", "wetland"): "water",
    ("natural", "bare_rock"): "bare_open",
    ("natural", "sand"): "bare_open",
    ("natural", "scree"): "bare_open",
    ("natural", "desert"): "bare_open",
}


class OverpassUnavailable(Exception):
    """Every configured Overpass mirror failed."""


@dataclass
class LandusePolygon:
    """A closed ring with its land-cover category and bounding box."""

    category: str
    tag: str
    ring: list[tuple[float, float]]  # (lat, lon)
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    area_deg2: float


# ---------------------------------------------------------------------------
# Tag interpretation
# ---------------------------------------------------------------------------
def categorize_facility(tags: dict[str, str]) -> str | None:
    """Classify an OSM feature into a FIRETRACE facility category.

    Ordered most-specific first, because a refinery is also tagged as works and
    sits inside an industrial landuse polygon.
    """
    t = {k.lower(): (v or "").lower() for k, v in tags.items()}
    name = t.get("name", "")
    industrial = t.get("industrial", "")
    product = t.get("product", "")
    blob = f"{name} {industrial} {product} {t.get('plant:source', '')}"

    if "refinery" in blob or industrial in {"oil", "petroleum", "refinery"}:
        return "refinery"
    if t.get("power") == "plant" or industrial == "power":
        return "power_plant"
    if any(w in blob for w in ("steel", "iron", "smelter", "aluminium", "aluminum", "foundry")):
        return "steel_metal"
    if "chemical" in blob or "petrochemical" in blob or "fertilis" in blob or "fertiliz" in blob:
        return "chemical"
    if "cement" in blob or "clinker" in blob:
        return "cement"
    if (
        t.get("landuse") == "quarry"
        or t.get("man_made") == "mineshaft"
        or industrial in {"mine", "quarry"}
        or "colliery" in blob
    ):
        return "mine_quarry"
    if t.get("man_made") in {
        "petroleum_well",
        "gasometer",
        "flare",
        "storage_tank",
        "oil_well",
        "pipeline",
    }:
        return "gas_oil_infrastructure"
    if t.get("man_made") == "works" or industrial == "factory":
        return "factory_works"
    if t.get("landuse") == "industrial":
        return "industrial_area"
    if industrial:
        return "factory_works"
    return None


def landuse_category(tags: dict[str, str]) -> tuple[str, str] | None:
    """Map OSM land-use/natural tags onto a land-cover category."""
    for key in ("landuse", "natural"):
        value = (tags.get(key) or "").lower()
        if not value:
            continue
        cat = LANDUSE_TO_CATEGORY.get((key, value))
        if cat:
            return cat, f"{key}={value}"
    return None


# ---------------------------------------------------------------------------
# Overpass transport
# ---------------------------------------------------------------------------
def _cache_path(root: Path, bbox: tuple[float, float, float, float], kind: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{kind}|{bbox}".encode("utf-8")).hexdigest()[:16]
    return root / f"{kind}_{key}.json"


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    payload["_cache_age_hours"] = round(age_hours, 2)
    payload["_cache_stale"] = age_hours > settings.overpass_cache_ttl_hours
    return payload


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        log.warning("[OSM] could not write cache %s: %s", path.name, exc)


def run_overpass(query: str, deadline: float | None = None) -> dict:
    """POST a query to the first Overpass mirror that answers.

    `deadline` is a `time.monotonic()` value. Without it, one unlucky tile can
    cost three full mirror timeouts back to back, which is how a "bounded"
    request still took minutes. With it, the remaining budget is checked before
    each mirror and also clamps that request's own timeout, so the whole call
    returns within the budget instead of overshooting it threefold.
    """
    last_error = "no endpoint configured"
    headers = {"User-Agent": settings.overpass_user_agent, "Accept": "application/json"}
    for endpoint in settings.overpass_endpoint_list:
        timeout = settings.overpass_timeout_seconds
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                last_error = "time budget exhausted before a mirror answered"
                log.info("[OSM] %s", last_error)
                break
            timeout = min(timeout, remaining)
        try:
            resp = httpx.post(
                endpoint,
                data={"data": query},
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code != 200:
                last_error = f"{endpoint} -> HTTP {resp.status_code}"
                log.warning("[OSM] %s", last_error)
                continue
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_error = f"{endpoint} -> {type(exc).__name__}"
            log.warning("[OSM] %s", last_error)
            continue
    raise OverpassUnavailable(last_error)


def _tiles(
    bbox: tuple[float, float, float, float], step: float
) -> list[tuple[float, float, float, float]]:
    """Split a bbox into grid-aligned tiles of `step` degrees."""
    west, south, east, north = snap_bbox_to_grid(bbox, step)
    out: list[tuple[float, float, float, float]] = []
    lat = south
    while lat < north - 1e-9:
        lon = west
        while lon < east - 1e-9:
            out.append((round(lon, 4), round(lat, 4), round(lon + step, 4), round(lat + step, 4)))
            lon += step
        lat += step
    return out


def tiles_for_points(
    points: list[tuple[float, float]], step: float, max_tiles: int
) -> list[tuple[float, float, float, float]]:
    """The busiest grid tiles containing the given (lat, lon) points.

    Tiling a whole area of interest does not scale: an India-wide bounding box
    at half-degree resolution is over three thousand tiles, which as a live
    request means thousands of Overpass queries and a dashboard that never
    loads. Geographic context is only ever needed *where detections actually
    are*, which is a tiny fraction of any large box.

    Tiles are ranked by how many detections fall in them, so when the cap bites
    it drops the emptiest corners rather than an arbitrary slice.
    """
    if not points or max_tiles <= 0:
        return []
    counts: dict[tuple[float, float], int] = {}
    for lat, lon in points:
        key = (
            round(math.floor(lon / step) * step, 4),
            round(math.floor(lat / step) * step, 4),
        )
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:max_tiles]
    return [
        (west, south, round(west + step, 4), round(south + step, 4))
        for (west, south), _ in ranked
    ]


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
FACILITY_QUERY = """
[out:json][timeout:{timeout}];
(
  node[man_made=works]({s},{w},{n},{e});
  way[man_made=works]({s},{w},{n},{e});
  node[power=plant]({s},{w},{n},{e});
  way[power=plant]({s},{w},{n},{e});
  relation[power=plant]({s},{w},{n},{e});
  way[landuse=industrial]({s},{w},{n},{e});
  relation[landuse=industrial]({s},{w},{n},{e});
  way[landuse=quarry]({s},{w},{n},{e});
  node[man_made=petroleum_well]({s},{w},{n},{e});
  node[man_made=gasometer]({s},{w},{n},{e});
  way[man_made=gasometer]({s},{w},{n},{e});
  node[man_made=storage_tank]({s},{w},{n},{e});
  way[man_made=storage_tank]({s},{w},{n},{e});
  node[man_made=mineshaft]({s},{w},{n},{e});
  node[industrial]({s},{w},{n},{e});
  way[industrial]({s},{w},{n},{e});
);
out tags center {maxsize};
"""


def fetch_facilities(
    bbox: tuple[float, float, float, float],
    use_cache: bool = True,
    max_features: int = 4000,
    cache_only: bool = False,
    deadline: float | None = None,
) -> tuple[list[Facility], str]:
    """Industrial facilities inside a bbox.

    Returns (facilities, status) where status is ok | cached | unavailable.
    A point location is all this needs, so `out tags center` is enough and the
    payload stays small.
    """
    snapped = snap_bbox_to_grid(bbox, settings.osm_tile_degrees)
    path = _cache_path(FACILITY_CACHE, snapped, "fac")

    cached = _read_cache(path) if use_cache else None
    if cached and not cached.get("_cache_stale"):
        return _facilities_from_elements(cached.get("elements", [])), "cached"

    # cache_only means "never touch the network": used by offline rebuilds so a
    # missing tile costs nothing instead of three mirror timeouts.
    if cache_only:
        if cached:
            return _facilities_from_elements(cached.get("elements", [])), "cached"
        return [], "unavailable"

    west, south, east, north = snapped
    query = FACILITY_QUERY.format(
        timeout=int(settings.overpass_timeout_seconds),
        s=f"{south:.4f}",
        w=f"{west:.4f}",
        n=f"{north:.4f}",
        e=f"{east:.4f}",
        maxsize=max_features,
    )
    try:
        payload = run_overpass(query, deadline=deadline)
    except OverpassUnavailable as exc:
        if cached:
            log.warning("[OSM] Overpass unavailable (%s); serving stale cache", exc)
            return _facilities_from_elements(cached.get("elements", [])), "cached"
        log.warning("[OSM] Overpass unavailable (%s) and no cache present", exc)
        return [], "unavailable"

    elements = payload.get("elements", [])
    _write_cache(path, {"elements": elements, "bbox": snapped, "fetched_at": time.time()})
    facilities = _facilities_from_elements(elements)
    log.info("[OSM] facilities loaded bbox=%s count=%d", snapped, len(facilities))
    return facilities, "ok"


def _facilities_from_elements(elements: list[dict]) -> list[Facility]:
    out: list[Facility] = []
    seen: set[str] = set()
    for el in elements:
        tags = el.get("tags") or {}
        category = categorize_facility(tags)
        if category is None:
            continue
        center = el.get("center") or {}
        lat = el.get("lat", center.get("lat"))
        lon = el.get("lon", center.get("lon"))
        if lat is None or lon is None:
            continue
        osm_type = el.get("type", "node")
        osm_id = int(el.get("id", 0))
        fid = f"{osm_type[0].upper()}{osm_id}"
        if fid in seen:
            continue
        seen.add(fid)
        keep = {
            k: v
            for k, v in tags.items()
            if k
            in {
                "name",
                "operator",
                "industrial",
                "product",
                "power",
                "plant:source",
                "man_made",
                "landuse",
            }
        }
        out.append(
            Facility(
                facility_id=fid,
                name=tags.get("name") or tags.get("operator"),
                category=category,
                category_label=FACILITY_LABELS.get(category, category),
                latitude=float(lat),
                longitude=float(lon),
                osm_type=osm_type,
                osm_id=osm_id,
                tags=keep,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Land use polygons
# ---------------------------------------------------------------------------
LANDUSE_VALUES = (
    "industrial|farmland|farmyard|orchard|vineyard|plantation|forest|meadow|grass|"
    "residential|commercial|retail|quarry|brownfield|landfill|reservoir|basin|port|railway"
)
NATURAL_VALUES = "wood|forest|scrub|heath|grassland|water|wetland|bare_rock|sand|scree|desert"

LANDUSE_QUERY = """
[out:json][timeout:{timeout}];
(
  way[landuse~"^({landuse})$"]({s},{w},{n},{e});
  way[natural~"^({natural})$"]({s},{w},{n},{e});
  relation[landuse~"^({landuse})$"]({s},{w},{n},{e});
  relation[natural~"^({natural})$"]({s},{w},{n},{e});
);
out geom {maxsize};
"""

# Small enough that a tile never hits the element cap, which is what silently
# erases coverage from the rest of a large query area.
LANDUSE_TILE_DEGREES = 0.5


def fetch_landuse(
    bbox: tuple[float, float, float, float],
    use_cache: bool = True,
    max_features: int = 4000,
    polite_delay: float = 0.4,
    cache_only: bool = False,
) -> tuple[list[LandusePolygon], str]:
    """Land-use / natural polygons covering a bbox, fetched tile by tile."""
    tiles = _tiles(bbox, LANDUSE_TILE_DEGREES)
    polygons: list[LandusePolygon] = []
    statuses: list[str] = []
    network_hits = 0

    for tile in tiles:
        tile_polys, status = _fetch_landuse_tile(tile, use_cache, max_features, cache_only)
        polygons.extend(tile_polys)
        statuses.append(status)
        if status == "ok":
            network_hits += 1
            if polite_delay and len(tiles) > 1:
                time.sleep(polite_delay)

    if not polygons:
        return [], "unavailable"
    overall = "ok" if network_hits else ("cached" if "cached" in statuses else "unavailable")
    log.info(
        "[OSM] land-use %d polygons over %d tile(s), %d fetched / %d cached",
        len(polygons),
        len(tiles),
        network_hits,
        len(tiles) - network_hits,
    )
    return polygons, overall


def fetch_facilities_for_points(
    points: list[tuple[float, float]],
    max_tiles: int = 9,
    use_cache: bool = True,
    budget_seconds: float | None = None,
) -> tuple[list[Facility], str]:
    """Facilities around where the detections actually are.

    Used by the live pipeline instead of one query over the whole area of
    interest, which for a country-sized box is a query Overpass will not
    answer.
    """
    tiles = tiles_for_points(points, settings.osm_tile_degrees, max_tiles)
    if not tiles:
        return [], "unavailable"

    merged: dict[str, Facility] = {}
    statuses: list[str] = []
    deadline = (time.monotonic() + budget_seconds) if budget_seconds else None
    exhausted = False

    for tile in tiles:
        # Tiles are ranked busiest-first, so when the budget runs out the ones
        # dropped to cache-only are the sparsest.
        out_of_time = deadline is not None and time.monotonic() > deadline
        if out_of_time and not exhausted:
            exhausted = True
            log.info("[OSM] facility budget spent; remaining tiles served from cache only")
        facilities, status = fetch_facilities(
            tile, use_cache=use_cache, cache_only=out_of_time, deadline=deadline
        )
        statuses.append(status)
        for f in facilities:
            merged[f.facility_id] = f

    if not merged:
        return [], "unavailable"
    overall = "ok" if "ok" in statuses else ("cached" if "cached" in statuses else "unavailable")
    return list(merged.values()), overall


def fetch_landuse_for_points(
    points: list[tuple[float, float]],
    max_tiles: int = 12,
    use_cache: bool = True,
    budget_seconds: float | None = None,
) -> tuple[list[LandusePolygon], str]:
    """Land-use polygons around where the detections actually are."""
    tiles = tiles_for_points(points, LANDUSE_TILE_DEGREES, max_tiles)
    if not tiles:
        return [], "unavailable"

    polygons: list[LandusePolygon] = []
    statuses: list[str] = []
    fetched = 0
    deadline = (time.monotonic() + budget_seconds) if budget_seconds else None
    exhausted = False

    for tile in tiles:
        # Tiles are ranked busiest-first, so when the budget runs out the ones
        # dropped to cache-only are the sparsest.
        out_of_time = deadline is not None and time.monotonic() > deadline
        if out_of_time and not exhausted:
            exhausted = True
            log.info("[OSM] land-use budget spent; remaining tiles served from cache only")
        tile_polys, status = _fetch_landuse_tile(
            tile, use_cache, 4000, cache_only=out_of_time, deadline=deadline
        )
        polygons.extend(tile_polys)
        statuses.append(status)
        if status == "ok":
            fetched += 1
            time.sleep(0.3)

    if not polygons:
        return [], "unavailable"
    overall = "ok" if fetched else ("cached" if "cached" in statuses else "unavailable")
    log.info(
        "[OSM] land-use %d polygons over %d event tile(s), %d fetched",
        len(polygons),
        len(tiles),
        fetched,
    )
    return polygons, overall


def _fetch_landuse_tile(
    tile: tuple[float, float, float, float],
    use_cache: bool,
    max_features: int,
    cache_only: bool = False,
    deadline: float | None = None,
) -> tuple[list[LandusePolygon], str]:
    path = _cache_path(LANDUSE_CACHE, tile, "lu")
    cached = _read_cache(path) if use_cache else None
    if cached and not cached.get("_cache_stale"):
        return _polygons_from_elements(cached.get("elements", [])), "cached"

    if cache_only:
        if cached:
            return _polygons_from_elements(cached.get("elements", [])), "cached"
        return [], "unavailable"

    west, south, east, north = tile
    query = LANDUSE_QUERY.format(
        timeout=int(settings.overpass_timeout_seconds),
        landuse=LANDUSE_VALUES,
        natural=NATURAL_VALUES,
        s=f"{south:.4f}",
        w=f"{west:.4f}",
        n=f"{north:.4f}",
        e=f"{east:.4f}",
        maxsize=max_features,
    )
    try:
        payload = run_overpass(query, deadline=deadline)
    except OverpassUnavailable as exc:
        if cached:
            return _polygons_from_elements(cached.get("elements", [])), "cached"
        log.warning("[OSM] land-use tile %s unavailable (%s)", tile, exc)
        return [], "unavailable"

    elements = payload.get("elements", [])
    # Geometry is bulky; store only what the point-in-polygon test needs.
    slim: list[dict] = []
    for el in elements:
        tags = el.get("tags") or {}
        if not landuse_category(tags):
            continue
        if el.get("type") == "way" and el.get("geometry"):
            slim.append({"type": "way", "tags": tags, "geometry": el["geometry"]})
        elif el.get("type") == "relation" and el.get("members"):
            outer = [
                {"geometry": m["geometry"]}
                for m in el["members"]
                if m.get("role") in ("outer", "") and m.get("geometry")
            ]
            if outer:
                slim.append({"type": "relation", "tags": tags, "members": outer})
    _write_cache(path, {"elements": slim, "bbox": tile, "fetched_at": time.time()})
    return _polygons_from_elements(slim), "ok"


def _ring_from_geometry(geom: list[dict]) -> list[tuple[float, float]]:
    return [
        (float(p["lat"]), float(p["lon"]))
        for p in geom
        if isinstance(p, dict) and "lat" in p and "lon" in p
    ]


def _stitch_rings(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Assemble multipolygon outer rings from their member ways.

    An OSM multipolygon's outer boundary is usually split across several ways
    that share endpoints but arrive in no particular order and in either
    direction. Each is walked end to end, flipping segments as needed, until
    the ring closes or nothing else connects to it.
    """
    closed: list[list[tuple[float, float]]] = []
    open_segments: list[list[tuple[float, float]]] = []

    for seg in segments:
        if len(seg) < 2:
            continue
        if seg[0] == seg[-1] and len(seg) >= 4:
            closed.append(seg)
        else:
            open_segments.append(seg)

    guard = 0
    while open_segments and guard < 10000:
        guard += 1
        ring = open_segments.pop(0)
        extended = True
        while extended and ring[0] != ring[-1] and open_segments:
            extended = False
            for i, candidate in enumerate(open_segments):
                if candidate[0] == ring[-1]:
                    ring = ring + candidate[1:]
                elif candidate[-1] == ring[-1]:
                    ring = ring + list(reversed(candidate))[1:]
                elif candidate[-1] == ring[0]:
                    ring = candidate[:-1] + ring
                elif candidate[0] == ring[0]:
                    ring = list(reversed(candidate))[:-1] + ring
                else:
                    continue
                open_segments.pop(i)
                extended = True
                break
        if len(ring) >= 4:
            closed.append(ring)
    return closed


def _polygons_from_elements(elements: list[dict]) -> list[LandusePolygon]:
    polys: list[LandusePolygon] = []
    for el in elements:
        tags = el.get("tags") or {}
        mapped = landuse_category(tags)
        if mapped is None:
            continue
        category, tag = mapped

        rings: list[list[tuple[float, float]]] = []
        if el.get("type") == "relation":
            segments = [_ring_from_geometry(m.get("geometry", [])) for m in el.get("members", [])]
            rings = _stitch_rings([s for s in segments if s])
        else:
            ring = _ring_from_geometry(el.get("geometry") or [])
            if len(ring) >= 4:
                rings = [ring]

        for ring in rings:
            if len(ring) < 4:
                continue
            lats = [p[0] for p in ring]
            lons = [p[1] for p in ring]
            polys.append(
                LandusePolygon(
                    category=category,
                    tag=tag,
                    ring=ring,
                    min_lat=min(lats),
                    min_lon=min(lons),
                    max_lat=max(lats),
                    max_lon=max(lons),
                    area_deg2=(max(lats) - min(lats)) * (max(lons) - min(lons)),
                )
            )
    return polys


def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test.

    Cast a ray east from the point and count boundary crossings: an odd count
    means the point is inside. Written out rather than pulled from a geometry
    library so the whole land-cover path stays dependency-free and readable.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = ring[i]
        lat_j, lon_j = ring[j]
        if (lat_i > lat) != (lat_j > lat):
            denom = lat_j - lat_i
            if denom != 0:
                x_cross = lon_i + (lat - lat_i) * (lon_j - lon_i) / denom
                if lon < x_cross:
                    inside = not inside
        j = i
    return inside

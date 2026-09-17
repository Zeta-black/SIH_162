"""Geospatial helpers.

Distances are computed with the haversine formula on a spherical Earth. That
is accurate to roughly 0.3% which is far beyond what this application needs,
and it is deliberately NOT naive degree subtraction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def valid_coordinate(lat: float | None, lon: float | None) -> bool:
    """Reject nulls, NaNs, out-of-range values and the null-island artefact."""
    if lat is None or lon is None:
        return False
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        return False
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False
    # 0,0 is in the Gulf of Guinea; in fire feeds it is almost always a
    # placeholder for a missing coordinate.
    if lat == 0.0 and lon == 0.0:
        return False
    return True


def km_to_deg_lat(km: float) -> float:
    return km / 110.574


def km_to_deg_lon(km: float, at_lat: float) -> float:
    """Degrees of longitude spanning `km` at a given latitude."""
    denom = 111.320 * math.cos(math.radians(max(-89.5, min(89.5, at_lat))))
    if abs(denom) < 1e-9:
        return 180.0
    return km / denom


def bbox_around(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(west, south, east, north) box that contains the radius circle."""
    dlat = km_to_deg_lat(radius_km)
    dlon = km_to_deg_lon(radius_km, lat)
    return (
        max(-180.0, lon - dlon),
        max(-90.0, lat - dlat),
        min(180.0, lon + dlon),
        min(90.0, lat + dlat),
    )


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse 'west,south,east,north' and validate ordering and ranges."""
    parts = [p.strip() for p in str(value).split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be 'west,south,east,north'")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be numbers") from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("bbox longitudes must be between -180 and 180")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("bbox latitudes must be between -90 and 90")
    if west >= east or south >= north:
        raise ValueError("bbox must satisfy west < east and south < north")
    return west, south, east, north


def point_in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


def snap_bbox_to_grid(
    bbox: tuple[float, float, float, float], step: float
) -> tuple[float, float, float, float]:
    """Expand a bbox outwards to grid boundaries.

    Snapping makes two nearby requests resolve to the same cache key, which is
    what keeps the public Overpass instances from being queried repeatedly for
    almost-identical areas.
    """
    west, south, east, north = bbox
    return (
        math.floor(west / step) * step,
        math.floor(south / step) * step,
        math.ceil(east / step) * step,
        math.ceil(north / step) * step,
    )


@dataclass(frozen=True)
class GridPoint:
    """Anything that can be indexed spatially."""

    lat: float
    lon: float
    payload: object


class SpatialGrid:
    """A uniform lat/lon grid index for nearest-neighbour and radius queries.

    A KD-tree would be marginally faster, but a grid keeps the dependency
    surface small and stays trivially readable — which matters when the code
    has to be explained by students at a hackathon. Lookup is O(points in the
    few cells touched) rather than O(all points).
    """

    def __init__(self, points: Iterable[GridPoint], cell_degrees: float = 0.25) -> None:
        self.cell = max(0.01, float(cell_degrees))
        self._cells: dict[tuple[int, int], list[GridPoint]] = {}
        self._count = 0
        for p in points:
            if not valid_coordinate(p.lat, p.lon):
                continue
            self._cells.setdefault(self._key(p.lat, p.lon), []).append(p)
            self._count += 1

    def __len__(self) -> int:
        return self._count

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return (int(math.floor(lat / self.cell)), int(math.floor(lon / self.cell)))

    def _candidates(self, lat: float, lon: float, radius_km: float) -> list[GridPoint]:
        dlat_cells = int(math.ceil(km_to_deg_lat(radius_km) / self.cell))
        dlon_cells = int(math.ceil(km_to_deg_lon(radius_km, lat) / self.cell))
        # Guard against a pathological cell count near the poles.
        dlon_cells = min(dlon_cells, 360)
        base_y, base_x = self._key(lat, lon)
        out: list[GridPoint] = []
        for dy in range(-dlat_cells, dlat_cells + 1):
            for dx in range(-dlon_cells, dlon_cells + 1):
                bucket = self._cells.get((base_y + dy, base_x + dx))
                if bucket:
                    out.extend(bucket)
        return out

    def nearest(
        self, lat: float, lon: float, max_radius_km: float
    ) -> tuple[GridPoint | None, float | None]:
        """Nearest indexed point within the radius, with its distance in km."""
        best: GridPoint | None = None
        best_d = float("inf")
        for cand in self._candidates(lat, lon, max_radius_km):
            d = haversine_km(lat, lon, cand.lat, cand.lon)
            if d < best_d:
                best, best_d = cand, d
        if best is None or best_d > max_radius_km:
            return None, None
        return best, best_d

    def within(self, lat: float, lon: float, radius_km: float) -> list[tuple[GridPoint, float]]:
        """All indexed points inside the radius, nearest first."""
        hits = []
        for cand in self._candidates(lat, lon, radius_km):
            d = haversine_km(lat, lon, cand.lat, cand.lon)
            if d <= radius_km:
                hits.append((cand, d))
        hits.sort(key=lambda t: t[1])
        return hits


def centroid(coords: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """Mean position of a set of (lat, lon) pairs."""
    pts = [(a, b) for a, b in coords if valid_coordinate(a, b)]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

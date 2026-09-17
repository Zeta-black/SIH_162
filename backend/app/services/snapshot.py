"""Demo / fallback snapshot.

WHAT THIS IS: a frozen capture of REAL NASA FIRMS detections and REAL
OpenStreetMap features, taken once by `ml/build_snapshot.py` and committed to
the repository.

WHAT IT IS NOT: synthetic data, and not live data. Every response built from
it is tagged `mode="snapshot"` and the dashboard shows a
"Demo / Historical Data" banner, because presenting a frozen capture as a live
feed would be dishonest even though the underlying observations are genuine.

It exists so the whole Detect -> Analyse -> Classify -> Visualise -> Monitor
chain still runs when NASA is unreachable, the API key is missing, or the
venue wifi is hostile — which at a hackathon is the normal case, not the edge
case.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR
from app.schemas import Facility, HotspotEvent
from app.services.osm import LandusePolygon

log = logging.getLogger("firetrace.snapshot")

SNAPSHOT_PATH = DATA_DIR / "demo_snapshot.json"


class Snapshot:
    def __init__(self, payload: dict) -> None:
        self.meta: dict = payload.get("meta", {})
        self.events: list[HotspotEvent] = []
        self.facilities: list[Facility] = []
        self.landuse: list[LandusePolygon] = []
        self.scenarios: list[dict] = payload.get("scenarios", [])

        for raw in payload.get("events", []):
            try:
                raw = dict(raw)
                raw["source_mode"] = "snapshot"
                self.events.append(HotspotEvent.model_validate(raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("[SNAPSHOT] skipping malformed event: %s", type(exc).__name__)

        for raw in payload.get("facilities", []):
            try:
                self.facilities.append(Facility.model_validate(raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("[SNAPSHOT] skipping malformed facility: %s", type(exc).__name__)

        for raw in payload.get("landuse", []):
            ring = [(float(a), float(b)) for a, b in raw.get("ring", [])]
            if len(ring) < 4:
                continue
            lats = [p[0] for p in ring]
            lons = [p[1] for p in ring]
            self.landuse.append(
                LandusePolygon(
                    category=raw["category"],
                    tag=raw.get("tag", ""),
                    ring=ring,
                    min_lat=min(lats),
                    min_lon=min(lons),
                    max_lat=max(lats),
                    max_lon=max(lons),
                    area_deg2=(max(lats) - min(lats)) * (max(lons) - min(lons)),
                )
            )

    @property
    def captured_at(self) -> str:
        return self.meta.get("captured_at", "unknown")

    @property
    def note(self) -> str:
        return self.meta.get(
            "note",
            "Frozen capture of real NASA FIRMS detections and OpenStreetMap features. "
            "Historical, not live.",
        )

    def bbox(self) -> tuple[float, float, float, float] | None:
        bb = self.meta.get("bbox")
        if isinstance(bb, list) and len(bb) == 4:
            return tuple(float(x) for x in bb)  # type: ignore[return-value]
        return None

    def summary(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "events": len(self.events),
            "facilities": len(self.facilities),
            "landuse_polygons": len(self.landuse),
            "products": self.meta.get("products", []),
            "date_range": self.meta.get("date_range"),
            "regions": self.meta.get("regions", []),
            "scenarios": [s.get("id") for s in self.scenarios],
            "note": self.note,
        }


_cache: Snapshot | None = None


def load_snapshot(path: Path | None = None, refresh: bool = False) -> Snapshot | None:
    """Read the snapshot from disk once and keep it in memory."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    target = path or SNAPSHOT_PATH
    if not target.exists():
        log.warning("[SNAPSHOT] no snapshot at %s", target)
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("[SNAPSHOT] could not read snapshot: %s", exc)
        return None
    snap = Snapshot(payload)
    log.info(
        "[SNAPSHOT] loaded events=%d facilities=%d landuse=%d",
        len(snap.events),
        len(snap.facilities),
        len(snap.landuse),
    )
    _cache = snap
    return snap


def snapshot_available() -> bool:
    return SNAPSHOT_PATH.exists()


def reset_snapshot_cache() -> None:
    global _cache
    _cache = None

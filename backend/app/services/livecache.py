"""Last-good live response, persisted to disk.

The in-memory analysis cache in `pipeline` is a latency optimisation: it dies
with the process and holds nothing after a restart. This is a different thing —
a durable record of the most recent successful NASA FIRMS fetch, so that a
restart on a dead venue network still has real, recent, *live-sourced* data to
show instead of falling all the way back to the 2025-2026 archive.

Two rules govern it:

1. A cached response is never presented as fresh. Every read carries the real
   `cached_at` timestamp, and the caller is expected to render the "Offline —
   showing saved data from <time>" state, not the live one.
2. It expires. Past `live_disk_cache_max_age_hours` the file is ignored, because
   a two-week-old "live" feed is worse than an archive that is honestly labelled
   as an archive.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import CACHE_DIR, settings
from app.schemas import HotspotEvent

log = logging.getLogger("firetrace.livecache")

CACHE_FILE = CACHE_DIR / "last_live_fetch.json"


@dataclass
class CachedFetch:
    events: list[HotspotEvent]
    cached_at: datetime
    bbox: str
    day_range: int
    products: list[str]

    @property
    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - self.cached_at

    @property
    def age_minutes(self) -> int:
        return int(self.age.total_seconds() // 60)

    def is_fresh_enough(self) -> bool:
        return self.age <= timedelta(hours=settings.live_disk_cache_max_age_hours)


def _ensure_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save(
    events: list[HotspotEvent],
    bbox: str,
    day_range: int,
    products: list[str],
) -> None:
    """Record a successful live fetch. Best effort: never breaks a request.

    An empty result is not written. "NASA says there is nothing burning" is a
    valid live answer but a useless thing to fall back to, and saving it would
    overwrite a good cache with a blank one.
    """
    if not events:
        return

    try:
        _ensure_dir()
        payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "bbox": bbox,
            "day_range": day_range,
            "products": products,
            "events": [json.loads(e.model_dump_json()) for e in events],
        }
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        # Atomic replace, so a crash mid-write cannot leave a truncated cache
        # that then fails to parse at the worst possible moment.
        tmp.replace(CACHE_FILE)
        log.info("[CACHE] saved %d live detections to disk", len(events))
    except Exception as exc:  # noqa: BLE001 - caching must never fail a request
        log.warning("[CACHE] could not save live response: %s", type(exc).__name__)


def load() -> CachedFetch | None:
    """The last good live fetch, or None when there is nothing usable."""
    if not CACHE_FILE.exists():
        return None

    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(payload["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        events = [HotspotEvent.model_validate(raw) for raw in payload.get("events", [])]
        if not events:
            return None

        cached = CachedFetch(
            events=events,
            cached_at=cached_at,
            bbox=payload.get("bbox", ""),
            day_range=int(payload.get("day_range", 1)),
            products=list(payload.get("products", [])),
        )

        if not cached.is_fresh_enough():
            log.info(
                "[CACHE] on-disk live cache is %d h old; ignoring it",
                int(cached.age.total_seconds() // 3600),
            )
            return None

        return cached
    except Exception as exc:  # noqa: BLE001
        log.warning("[CACHE] could not read live cache: %s", type(exc).__name__)
        return None


def status() -> dict[str, object]:
    """What the cache holds, for /health and the sources page."""
    cached = load()
    if cached is None:
        return {"present": False, "note": "No usable cached live response on disk."}
    return {
        "present": True,
        "cached_at": cached.cached_at.isoformat(),
        "age_minutes": cached.age_minutes,
        "events": len(cached.events),
        "bbox": cached.bbox,
        "products": cached.products,
        "note": (
            "Most recent successful NASA FIRMS fetch. Shown only as explicitly "
            "labelled offline data, never as a live feed."
        ),
    }


def clear() -> None:
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

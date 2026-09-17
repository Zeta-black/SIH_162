"""Build the demo / fallback snapshot.

Run:  python -m ml.build_snapshot          (from the backend/ directory)
      python -m ml.build_snapshot --offline

Captures REAL NASA FIRMS detections and REAL OpenStreetMap context for a set of
regions and freezes them into `app/data/demo_snapshot.json`, together with four
curated scenarios that walk an evaluator through the whole workflow.

This is not synthetic data. Every coordinate, brightness value, FRP reading and
facility in the file came from the live sources. It is, however, HISTORICAL —
frozen at capture time — and every API response built from it is tagged
`mode="snapshot"` with a "Demo / Historical Data" banner, because showing a
frozen capture as a live feed would be dishonest even when the observations
themselves are genuine.

Why it exists: at a hackathon the venue wifi, the NASA endpoint or the Overpass
mirrors will fail at exactly the wrong moment. With this file present the
entire Detect -> Analyse -> Classify -> Visualise -> Monitor chain still runs
with no network at all.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR  # noqa: E402
from app.schemas import HotspotEvent  # noqa: E402
from app.services import firms as firms_service  # noqa: E402
from app.services.geo import haversine_km  # noqa: E402
from app.services.labeling import assign_label  # noqa: E402
from app.store.db import get_store  # noqa: E402
from ml.enrich import enrich_events, load_region_context  # noqa: E402
from ml.regions import REGIONS_BY_ID  # noqa: E402
from app.taxonomy import (  # noqa: E402
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    LC_CROPLAND,
    LC_FOREST,
    NATURAL_FIRE,
)

OUTPUT = DATA_DIR / "demo_snapshot.json"

# Regions chosen so the snapshot contains all four scenario shapes: a heavy
# industrial cluster, a second industrial belt, a cropland belt and a forest.
SNAPSHOT_REGIONS = ["jamnagar", "hazira", "singrauli", "korba", "punjab_central", "similipal"]

# Only polygons near an actual detection are frozen. Keeping every polygon in
# the region would make this file tens of megabytes for no benefit.
LANDUSE_KEEP_RADIUS_KM = 6.0
MAX_EVENTS_PER_REGION = 260

log = logging.getLogger("firetrace.snapshot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("firetrace").setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def recent_windows() -> list[tuple[str, int]]:
    """Two contiguous 5-day windows ending a day back.

    FIRMS near-real-time data lags by a few hours, so the window starts one day
    behind today to avoid asking for a period that is still being populated.
    """
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    first = end - timedelta(days=4)
    second = first - timedelta(days=5)
    return [(first.isoformat(), 5), (second.isoformat(), 5)]


def fetch_region_events(region_id: str, offline: bool) -> list[HotspotEvent]:
    region = REGIONS_BY_ID[region_id]
    if offline:
        events = get_store().load_events(bbox=region.bbox)
        log.info("    offline: %d detections from the store", len(events))
        return events[:MAX_EVENTS_PER_REGION]

    collected: list[HotspotEvent] = []
    client = firms_service.FirmsClient()
    for start, days in recent_windows():
        try:
            result = client.fetch_area(
                bbox=region.bbox,
                day_range=days,
                start_date=date.fromisoformat(start),
                products=["VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"],
            )
            collected.extend(result.events)
            log.info("    %s +%dd -> %d detections", start, days, len(result.events))
        except firms_service.FirmsError as exc:
            log.warning("    %s unavailable: %s", start, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("    %s failed: %s", start, type(exc).__name__)
        time.sleep(0.3)

    # Fall back to whatever the store already holds for this region, so a
    # snapshot can still be rebuilt when NRT happens to be empty.
    if not collected:
        collected = get_store().load_events(bbox=region.bbox)
        log.info("    no live rows; using %d stored detections", len(collected))

    seen: set[str] = set()
    unique: list[HotspotEvent] = []
    for e in collected:
        if e.event_id in seen:
            continue
        seen.add(e.event_id)
        unique.append(e)
    return unique[:MAX_EVENTS_PER_REGION]


def pick_scenarios(enriched_all: list) -> list[dict]:
    """Choose four real detections that demonstrate the four evidence shapes.

    Nothing here is fabricated: each scenario points at a detection that is
    genuinely in the snapshot and genuinely has the described evidence. If no
    detection fits a shape, that scenario is simply omitted rather than faked.
    """
    scenarios: list[dict] = []

    def add(item, sid, title, description):
        scenarios.append(
            {
                "id": sid,
                "title": title,
                "description": description,
                "event_id": item.event.event_id,
                "latitude": item.event.latitude,
                "longitude": item.event.longitude,
                "bbox": _bbox_for(item, 0.45),
                "days": 5,
            }
        )

    # A — on an industrial facility, repeating, strong signal.
    industrial = [
        i
        for i in enriched_all
        if i.nearest_facility
        and i.nearest_facility.distance_km <= 1.5
        and i.recurrence.distinct_days >= 3
    ]
    industrial.sort(
        key=lambda i: (i.recurrence.distinct_days, i.event.frp_mw or 0), reverse=True
    )
    if industrial:
        top = industrial[0]
        add(
            top,
            "A_persistent_industrial",
            "A · Persistent industrial heat",
            f"On {top.nearest_facility.name or top.nearest_facility.category_label}, "
            f"{top.nearest_facility.distance_km:.2f} km away, seen on "
            f"{top.recurrence.distinct_days} separate days.",
        )

    # B — episodic, close to industry, strong radiative power.
    episodic = [
        i
        for i in enriched_all
        if i.nearest_facility
        and i.nearest_facility.distance_km <= 2.0
        and i.recurrence.distinct_days <= 2
        and (i.event.frp_mw or 0) >= 8
    ]
    episodic.sort(key=lambda i: i.event.frp_mw or 0, reverse=True)
    if episodic:
        top = episodic[0]
        add(
            top,
            "B_episodic_industrial",
            "B · One-off event near industry",
            f"{top.event.frp_mw:.0f} MW, {top.nearest_facility.distance_km:.2f} km from "
            f"{top.nearest_facility.category_label.lower()}, with no history of repeating.",
        )

    # C — cropland or forest, well clear of any industry.
    vegetation = [
        i
        for i in enriched_all
        if i.land_cover.category in {LC_CROPLAND, LC_FOREST}
        and (i.nearest_facility is None or i.nearest_facility.distance_km >= 4)
    ]
    vegetation.sort(key=lambda i: i.event.frp_mw or 0, reverse=True)
    if vegetation:
        top = vegetation[0]
        add(
            top,
            "C_vegetation",
            "C · Vegetation fire away from industry",
            f"{top.land_cover.label} land cover, no industrial facility within "
            f"{'the search radius' if not top.nearest_facility else f'{top.nearest_facility.distance_km:.1f} km'}.",
        )

    # D — genuinely ambiguous: mid-range distance, no land cover, no history.
    ambiguous = [
        i
        for i in enriched_all
        if assign_label(i.event, i.nearest_facility, i.land_cover, i.recurrence).label is None
        and i.nearest_facility
        and 1.5 < i.nearest_facility.distance_km < 5.0
    ]
    if ambiguous:
        top = ambiguous[0]
        add(
            top,
            "D_ambiguous",
            "D · Ambiguous evidence",
            "Mid-range from industry with weak supporting evidence — the case where "
            "FIRETRACE should abstain rather than guess.",
        )

    return scenarios


def _bbox_for(item, pad: float) -> str:
    lat, lon = item.event.latitude, item.event.longitude
    return f"{lon - pad:.3f},{lat - pad:.3f},{lon + pad:.3f},{lat + pad:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the FIRETRACE demo snapshot.")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    setup_logging()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = get_store()

    all_events: list[HotspotEvent] = []
    all_facilities: dict[str, object] = {}
    all_landuse: list = []
    enriched_all: list = []
    regions_used: list[str] = []
    bounds = [180.0, 90.0, -180.0, -90.0]  # w, s, e, n

    log.info("=" * 74)
    log.info("FIRETRACE demo snapshot builder")
    log.info("=" * 74)

    for region_id in SNAPSHOT_REGIONS:
        region = REGIONS_BY_ID[region_id]
        log.info("[%s] %s", region_id, region.name)

        events = fetch_region_events(region_id, args.offline)
        if not events:
            log.warning("    no detections; skipping region")
            continue
        store.upsert_events(events)

        context = load_region_context(region.bbox, polite=not args.offline)
        log.info(
            "    context: %d facilities, %d land-use polygons",
            len(context.facilities),
            len(context.landuse),
        )
        store.upsert_facilities(context.facilities)

        enriched = enrich_events(events, context)
        enriched_all.extend(enriched)
        all_events.extend(events)
        regions_used.append(region_id)

        for f in context.facilities:
            all_facilities[f.facility_id] = f

        # Keep only polygons near a detection, so the file stays small.
        for poly in context.landuse:
            clat = (poly.min_lat + poly.max_lat) / 2
            clon = (poly.min_lon + poly.max_lon) / 2
            if any(
                haversine_km(clat, clon, e.latitude, e.longitude) <= LANDUSE_KEEP_RADIUS_KM
                for e in events
            ):
                all_landuse.append(poly)

        w, s, e, n = region.bbox
        bounds = [min(bounds[0], w), min(bounds[1], s), max(bounds[2], e), max(bounds[3], n)]

    if not all_events:
        log.error("No detections captured. Nothing written.")
        sys.exit(1)

    # Facilities far from every detection add weight without adding value.
    kept_facilities = [
        f
        for f in all_facilities.values()
        if any(
            haversine_km(f.latitude, f.longitude, e.latitude, e.longitude) <= 15.0
            for e in all_events
        )
    ]

    scenarios = pick_scenarios(enriched_all)
    dates = sorted({e.acquisition_date.isoformat() for e in all_events})
    label_preview = Counter(
        assign_label(i.event, i.nearest_facility, i.land_cover, i.recurrence).label or "UNLABELLED"
        for i in enriched_all
    )

    payload = {
        "meta": {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "bbox": bounds,
            "regions": regions_used,
            "products": sorted({e.source_product for e in all_events}),
            "date_range": {"from": dates[0], "to": dates[-1]} if dates else None,
            "note": (
                "Frozen capture of real NASA FIRMS detections and real OpenStreetMap features. "
                "Historical, not live. Presented as Demo / Historical Data throughout the UI."
            ),
            "source_disclaimer": (
                "Observations are genuine. Classifications shown over this data are model "
                "outputs, not verified incident reports."
            ),
        },
        "events": [json.loads(e.model_dump_json()) for e in all_events],
        "facilities": [json.loads(f.model_dump_json()) for f in kept_facilities],
        "landuse": [
            {"category": p.category, "tag": p.tag, "ring": [[a, b] for a, b in p.ring]}
            for p in all_landuse
        ],
        "scenarios": scenarios,
    }

    OUTPUT.write_text(json.dumps(payload), encoding="utf-8")
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)

    log.info("=" * 74)
    log.info("events     : %d", len(all_events))
    log.info("facilities : %d", len(kept_facilities))
    log.info("land use   : %d polygons", len(all_landuse))
    log.info("scenarios  : %s", ", ".join(s["id"] for s in scenarios) or "none")
    log.info("date range : %s", f"{dates[0]} to {dates[-1]}" if dates else "n/a")
    log.info("label mix  : %s", dict(label_preview))
    log.info("written    : %s (%.1f MB)", OUTPUT.name, size_mb)
    log.info("=" * 74)


if __name__ == "__main__":
    main()

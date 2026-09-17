"""Build the prototype training dataset from real NASA FIRMS + OSM data.

Run:  python -m ml.build_dataset                  (from the backend/ directory)
      python -m ml.build_dataset --offline        (rebuild from cached data only)
      python -m ml.build_dataset --workers 1      (strictly serial)
      python -m ml.build_dataset --regions jamnagar,punjab_central

What this produces
------------------
`ml/data/training_dataset.csv` — one row per labelled detection, containing the
full feature vector, the assigned label, the rule that assigned it and enough
provenance to audit any row.

Honesty, restated
-----------------
The detections are real. The labels are NOT verified ground truth; they come
from the documented rule policy in `app/services/labeling.py`. Detections whose
evidence is ambiguous get no label and are written to a separate file rather
than being forced into a class. See the README section "Scientific and
Prototype Limitations".

Concurrency note
----------------
Regions are fetched on a small thread pool because almost all of the wall time
is spent waiting on HTTP, not computing. The pool is deliberately small (three
workers) because Overpass is donated public infrastructure. All SQLite writes
happen on the main thread as results arrive, so no two threads ever hold the
database at once.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

# Allow `python -m ml.build_dataset` from backend/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ML_DIR  # noqa: E402
from app.schemas import HotspotEvent  # noqa: E402
from app.services import firms as firms_service  # noqa: E402
from app.services.features import FEATURE_NAMES, FEATURE_VERSION, build_feature_row  # noqa: E402
from app.services.labeling import LABEL_POLICY_VERSION, assign_label  # noqa: E402
from app.store.db import get_store  # noqa: E402
from ml.enrich import enrich_events, load_region_context  # noqa: E402
from ml.regions import REGIONS, Region  # noqa: E402
from ml.windows import TRAINING_WINDOWS, Window  # noqa: E402

DATA_DIR = ML_DIR / "data"
OUTPUT_CSV = DATA_DIR / "training_dataset.csv"
UNLABELLED_CSV = DATA_DIR / "unlabelled_detections.csv"
MANIFEST = DATA_DIR / "dataset_manifest.json"

DATASET_VERSION = "1.0.0"

# Cap per region+window so one enormous stubble-burning window cannot drown
# out every other class in the training set.
MAX_ROWS_PER_REGION_WINDOW = 400

log = logging.getLogger("firetrace.dataset")
_print_lock = threading.Lock()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("firetrace").setLevel(logging.INFO)
    # httpx logs full request URLs at INFO, which would print the FIRMS key.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The per-request OSM/FIRMS chatter is too noisy once regions run in
    # parallel; each region reports one summary line instead.
    logging.getLogger("firetrace.osm").setLevel(logging.WARNING)
    logging.getLogger("firetrace.firms").setLevel(logging.WARNING)
    logging.getLogger("firetrace.store").setLevel(logging.WARNING)


@dataclass
class RegionResult:
    region: Region
    events: list
    facilities: list
    enriched: list
    failures: int
    note: str


def fetch_window(region: Region, window: Window) -> list[HotspotEvent]:
    """Fetch one region/window from FIRMS. Returns [] on any failure."""
    client = firms_service.FirmsClient()
    start = date.fromisoformat(window.start) if window.start else None
    try:
        result = client.fetch_area(
            bbox=region.bbox,
            day_range=window.days,
            start_date=start,
            products=list(window.products),
        )
        return result.events
    except firms_service.FirmsError:
        return []
    except Exception:  # noqa: BLE001
        return []


def subsample(events: list[HotspotEvent], limit: int) -> list[HotspotEvent]:
    """Keep a deterministic spread rather than the first N rows.

    Sorting by event_id (a hash) then taking a stride gives a reproducible,
    geographically mixed sample instead of one dense corner of the bbox.
    """
    if len(events) <= limit:
        return events
    ordered = sorted(events, key=lambda e: e.event_id)
    stride = len(ordered) / limit
    return [ordered[int(i * stride)] for i in range(limit)]


def process_region(region: Region, offline: bool, store_events: list) -> RegionResult:
    """Fetch + enrich one region. Runs on a worker thread; touches no database."""
    started = time.time()
    failures = 0
    events: list[HotspotEvent] = []

    if offline:
        events = list(store_events)
    else:
        for window in TRAINING_WINDOWS:
            got = fetch_window(region, window)
            if not got:
                failures += 1
                continue
            events.extend(subsample(got, MAX_ROWS_PER_REGION_WINDOW))
            time.sleep(0.15)

    if not events:
        return RegionResult(region, [], [], [], failures, "no detections")

    # De-duplicate: overlapping windows and two satellites will repeat pixels.
    seen: set[str] = set()
    unique: list[HotspotEvent] = []
    for e in events:
        if e.event_id not in seen:
            seen.add(e.event_id)
            unique.append(e)

    context = load_region_context(region.bbox, polite=not offline, cache_only=offline)
    enriched = enrich_events(unique, context)

    note = (
        f"{len(unique)} detections, {len(context.facilities)} facilities, "
        f"{len(context.landuse)} land-use polygons, {time.time() - started:.0f}s"
    )
    return RegionResult(region, unique, context.facilities, enriched, failures, note)


def build(offline: bool = False, regions: list[Region] | None = None, workers: int = 3) -> None:
    setup_logging()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    regions = regions or REGIONS
    store = get_store()

    started = datetime.now(timezone.utc)
    labelled_rows: list[dict] = []
    unlabelled_rows: list[dict] = []
    rule_counts: Counter[str] = Counter()
    region_stats: list[dict] = []
    fetch_failures = 0

    log.info("=" * 74)
    log.info(
        "FIRETRACE dataset builder  (feature v%s, policy v%s)",
        FEATURE_VERSION,
        LABEL_POLICY_VERSION,
    )
    log.info(
        "regions=%d windows=%d workers=%d offline=%s",
        len(regions),
        len(TRAINING_WINDOWS),
        workers,
        offline,
    )
    log.info("=" * 74)

    # Offline mode reads detections from the store up front, on the main
    # thread, so worker threads never touch SQLite.
    preloaded = {r.id: (store.load_events(bbox=r.bbox) if offline else []) for r in regions}

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(process_region, r, offline, preloaded[r.id]): r for r in regions
        }
        for future in as_completed(futures):
            region = futures[future]
            completed += 1
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("[%2d/%d] %-38s FAILED (%s)", completed, len(regions), region.id, type(exc).__name__)
                region_stats.append({"region": region.id, "events": 0, "labelled": 0})
                continue

            fetch_failures += result.failures
            if not result.events:
                log.warning("[%2d/%d] %-38s no detections", completed, len(regions), region.id)
                region_stats.append({"region": region.id, "events": 0, "labelled": 0})
                continue

            # All database writes happen here, on the main thread.
            store.upsert_events(result.events)
            store.upsert_facilities(result.facilities)

            region_labelled = 0
            for item in result.enriched:
                decision = assign_label(
                    item.event, item.nearest_facility, item.land_cover, item.recurrence
                )
                rule_counts[decision.rule] += 1

                features = build_feature_row(
                    item.event, item.nearest_facility, item.land_cover, item.recurrence
                )
                provenance = {
                    "event_id": item.event.event_id,
                    "latitude": item.event.latitude,
                    "longitude": item.event.longitude,
                    "acquisition_date": item.event.acquisition_date.isoformat(),
                    "source_product": item.event.source_product,
                    "region_id": region.id,
                    "region_character": region.character,
                    "nearest_facility_category": (
                        item.nearest_facility.category if item.nearest_facility else "none"
                    ),
                    "nearest_facility_km": (
                        round(item.nearest_facility.distance_km, 4)
                        if item.nearest_facility
                        else None
                    ),
                    "land_cover": item.land_cover.category,
                    "distinct_days": item.recurrence.distinct_days,
                    "label_rule": decision.rule,
                    "label_rationale": decision.rationale,
                }
                row = {**features, **provenance}
                if decision.label is None:
                    unlabelled_rows.append(row)
                else:
                    row["label"] = decision.label
                    labelled_rows.append(row)
                    region_labelled += 1

            log.info(
                "[%2d/%d] %-38s %s -> %d labelled",
                completed,
                len(regions),
                region.id,
                result.note,
                region_labelled,
            )
            region_stats.append(
                {
                    "region": region.id,
                    "events": len(result.enriched),
                    "labelled": region_labelled,
                }
            )

    if not labelled_rows:
        log.error("No labelled rows were produced. Nothing written.")
        sys.exit(1)

    frame = pd.DataFrame(labelled_rows)

    # Deduplicate by detection id BEFORE anything else.
    #
    # Region bounding boxes overlap on purpose — punjab_central spans 75.05-76.05
    # and punjab_malwa 74.35-75.35 — so a detection in the shared strip is
    # fetched once per region and appears twice with different region_id values.
    # A split grouped on region_id then puts the SAME physical observation in
    # both train and test, which is textbook leakage. Measured on the first
    # build: 18 detections, all in the Punjab overlap.
    #
    # The detection id is a hash of position, acquisition time and product, so
    # equal ids really are the same observation and dropping the later copy
    # loses nothing.
    before = len(frame)
    frame = frame.drop_duplicates(subset="event_id", keep="first").reset_index(drop=True)
    deduped = before - len(frame)
    if deduped:
        log.warning(
            "removed %d duplicate detection(s) appearing in overlapping regions", deduped
        )
    provenance_cols = [c for c in frame.columns if c not in FEATURE_NAMES and c != "label"]
    frame = frame[[*FEATURE_NAMES, *provenance_cols, "label"]]
    frame.to_csv(OUTPUT_CSV, index=False)

    # The ambiguous rows carry duplicates from the same overlapping-region strip,
    # so they are deduped on the same key. The count below is taken AFTER that
    # drop, because the manifest must describe the file that is actually on disk
    # — reporting the pre-dedupe figure made the manifest disagree with the CSV.
    unlabelled = pd.DataFrame(unlabelled_rows)
    unlabelled_before = len(unlabelled)
    if unlabelled_before:
        unlabelled = unlabelled.drop_duplicates(subset="event_id", keep="first")
        unlabelled.to_csv(UNLABELLED_CSV, index=False)
    n_unlabelled = len(unlabelled)
    unlabelled_deduped = unlabelled_before - n_unlabelled

    label_counts = Counter(frame["label"])
    manifest = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_policy_version": LABEL_POLICY_VERSION,
        "built_at": started.isoformat(),
        "built_offline": offline,
        "rows_labelled": int(len(frame)),
        "duplicate_detections_removed": int(deduped),
        "duplicate_unlabelled_removed": int(unlabelled_deduped),
        "rows_unlabelled_excluded": int(n_unlabelled),
        "rows_total_after_dedupe": int(len(frame) + n_unlabelled),
        "label_counts": {k: int(v) for k, v in label_counts.items()},
        "rule_counts": dict(rule_counts),
        "regions": region_stats,
        "windows": [
            {"id": w.id, "products": list(w.products), "start": w.start, "days": w.days}
            for w in TRAINING_WINDOWS
        ],
        "fetch_failures": fetch_failures,
        "observation_source": "NASA FIRMS (real detections)",
        "context_source": "OpenStreetMap via Overpass (real features)",
        "label_source": "weak supervision rules (NOT verified ground truth)",
        "caveat": (
            "Labels are inferred by a documented rule policy, not by field verification. "
            "Any model metric computed on this dataset measures agreement with that policy."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    total = len(frame) + n_unlabelled
    log.info("=" * 74)
    log.info("detections processed : %d", total)
    log.info("labelled rows        : %d  -> %s", len(frame), OUTPUT_CSV.name)
    log.info(
        "excluded (ambiguous) : %d  (%.0f%%, not forced into a class)",
        n_unlabelled,
        100 * n_unlabelled / max(1, total),
    )
    for label, count in label_counts.most_common():
        log.info("   %-30s %5d  (%.1f%%)", label, count, 100 * count / len(frame))
    log.info("rules fired:")
    for rule, count in rule_counts.most_common():
        log.info("   %-42s %5d", rule, count)
    log.info("=" * 74)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the FIRETRACE training dataset.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild from already-stored FIRMS detections and cached OSM data.",
    )
    parser.add_argument(
        "--regions", type=str, default="", help="Comma-separated region ids (default: all)."
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Parallel regions. Keep small; Overpass is shared."
    )
    args = parser.parse_args()

    selected = None
    if args.regions:
        wanted = {r.strip() for r in args.regions.split(",") if r.strip()}
        selected = [r for r in REGIONS if r.id in wanted]
        if not selected:
            print(f"No matching regions. Known ids: {', '.join(r.id for r in REGIONS)}")
            sys.exit(1)

    build(offline=args.offline, regions=selected, workers=args.workers)


if __name__ == "__main__":
    main()

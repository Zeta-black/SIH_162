"""Measure how long the pipeline actually takes at 10, 100 and 1000 events.

Run:  python -m ml.benchmark              (from the backend/ directory)
      python -m ml.benchmark --repeats 5

Writes `docs/PERFORMANCE_RESULTS.md` with the measured numbers and the machine
they were measured on.

WHAT IS AND IS NOT MEASURED
---------------------------
This measures OUR processing, on data already in hand: enrichment, feature
extraction, ML inference, priority scoring, clustering, the alert rule and the
database write. It deliberately excludes NASA FIRMS and Overpass network time,
because that is someone else's latency and varies with their load — mixing the
two would produce a number that describes neither.

Every figure written by this script is measured on the machine that runs it. If
a scale cannot be reached with the data available, the script says so instead of
extrapolating.
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import ClassifiedEvent, Evidence  # noqa: E402
from app.services import events as events_service  # noqa: E402
from app.services import incidents as incidents_service  # noqa: E402
from app.services import landcover as landcover_service  # noqa: E402
from app.services import snapshot as snapshot_service  # noqa: E402
from app.services.classifier import DISCLAIMER, get_classifier  # noqa: E402
from app.services.features import build_feature_row  # noqa: E402
from app.services.geo import GridPoint, SpatialGrid  # noqa: E402
from app.services.priority import compute_priority  # noqa: E402
from app.services.recurrence import HistoryIndex  # noqa: E402
from app.services.replay import _nearest  # noqa: E402
from app.store.db import EventStore  # noqa: E402

SCALES = [10, 100, 1000]
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_PATH = REPO_ROOT / "docs" / "PERFORMANCE_RESULTS.md"

log = logging.getLogger("firetrace.benchmark")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    # These are noisy at INFO and say nothing about performance.
    for name in ("firetrace.pipeline", "firetrace.events", "firetrace.snapshot",
                 "firetrace.landcover", "firetrace.incidents", "firetrace.store"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _os_name() -> str:
    """Report the OS accurately.

    `platform.release()` returns "10" on Windows 11 — a Win32 compatibility
    quirk, not a Python bug. The build number in `platform.version()` is the
    reliable discriminator: 22000 and above is Windows 11. A report about
    measurement should not open by naming the wrong operating system.
    """
    system = platform.system()
    release = platform.release()
    version = platform.version()
    if system == "Windows":
        try:
            build = int(version.split(".")[2])
            if build >= 22000 and release == "10":
                release = "11"
        except (IndexError, ValueError):
            pass
        return f"Windows {release} (build {version})"
    return f"{system} {release}"


def environment() -> dict[str, str]:
    """The machine and software the numbers below were measured on."""
    import sklearn

    try:
        import psutil  # type: ignore

        mem = f"{psutil.virtual_memory().total / 1024 ** 3:.1f} GB"
        cpu_count = str(psutil.cpu_count(logical=True))
    except Exception:  # noqa: BLE001
        import os

        mem = "not measured (psutil not installed)"
        cpu_count = str(os.cpu_count() or "unknown")

    return {
        "os": _os_name(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "logical_cpus": cpu_count,
        "total_memory": mem,
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "database": "SQLite (single file, single process)",
    }


def peak_memory_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / 1024 ** 2
    except Exception:  # noqa: BLE001
        return None


class Harness:
    """Holds the fixed context so each scale measures processing, not setup."""

    def __init__(self, tmp_db: Path) -> None:
        snap = snapshot_service.load_snapshot()
        if snap is None or not snap.events:
            raise SystemExit("No snapshot available. Run `python -m ml.build_snapshot` first.")
        self.snap = snap
        self.grid = SpatialGrid(
            (GridPoint(lat=f.latitude, lon=f.longitude, payload=f) for f in snap.facilities),
            cell_degrees=0.1,
        )
        self.provider, self.provider_name = landcover_service.build_provider(
            None, snapshot_polygons=snap.landuse, allow_network=False
        )
        self.history = HistoryIndex(snap.events)
        self.classifier = get_classifier()
        self.store = EventStore(tmp_db)

    def sample(self, n: int) -> tuple[list, bool]:
        """n detections, and whether they had to be repeated to reach n.

        The snapshot holds a finite number of real detections. Rather than
        fabricate extra ones, larger scales cycle through the real set and the
        report says so plainly.
        """
        events = self.snap.events
        if n <= len(events):
            return events[:n], False
        repeated = [events[i % len(events)] for i in range(n)]
        return repeated, True

    def run_once(self, n: int) -> dict[str, float]:
        batch, _ = self.sample(n)
        timings: dict[str, float] = {}

        t = time.perf_counter()
        enriched = [
            (e, _nearest(self.grid, e), self.provider.lookup(e.latitude, e.longitude),
             self.history.compute(e))
            for e in batch
        ]
        timings["enrichment_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        [build_feature_row(e, nf, lc, rc) for e, nf, lc, rc in enriched]
        timings["feature_extraction_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        if self.classifier.loaded:
            scored = self.classifier.predict_batch(enriched, explain=False)  # type: ignore[arg-type]
        else:
            scored = [self.classifier.predict(e, nf, lc, rc) for e, nf, lc, rc in enriched]
        timings["ml_inference_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        model_info = self.classifier.info()
        classified: list[ClassifiedEvent] = []
        for (e, nf, lc, rc), (classification, probabilities, _) in zip(enriched, scored):
            classified.append(
                ClassifiedEvent(
                    event=e,
                    classification=classification,
                    probabilities=probabilities,
                    evidence=Evidence(
                        distance_to_nearest_facility_km=(round(nf.distance_km, 3) if nf else None),
                        nearest_facility=nf,
                        land_cover=lc,
                        recurrence=rc,
                        thermal_intensity_k=e.brightness_k,
                        frp_mw=e.frp_mw,
                        firms_confidence=e.firms_confidence_level,
                        day_night=e.day_night,
                    ),
                    factors=[],
                    priority=compute_priority(e, classification, nf, rc),
                    model=model_info,
                    disclaimer=DISCLAIMER,
                )
            )
        timings["risk_priority_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        fire_events = events_service.cluster(classified)
        timings["clustering_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        alerts = sum(1 for fe in fire_events if incidents_service.alert_for(fe)[0] is not None)
        timings["alert_generation_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        self.store.upsert_events(list(batch))
        timings["database_ms"] = (time.perf_counter() - t) * 1000

        timings["total_ms"] = sum(
            timings[k] for k in (
                "enrichment_ms", "feature_extraction_ms", "ml_inference_ms",
                "risk_priority_ms", "clustering_ms", "alert_generation_ms", "database_ms",
            )
        )
        timings["_fire_events"] = float(len(fire_events))
        timings["_alerts"] = float(alerts)
        return timings


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the FIRETRACE pipeline.")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    setup_logging()
    import tempfile

    env = environment()
    log.info("=" * 74)
    log.info("FIRETRACE pipeline benchmark")
    log.info("=" * 74)
    for k, v in env.items():
        log.info("  %-16s %s", k, v)

    with tempfile.TemporaryDirectory() as tmp:
        harness = Harness(Path(tmp) / "bench.sqlite3")
        available = len(harness.snap.events)
        log.info("  %-16s %d real detections", "snapshot", available)
        log.info("")

        results = []
        for n in SCALES:
            _, repeated = harness.sample(n)
            runs = []
            failures = 0
            for i in range(args.repeats):
                try:
                    runs.append(harness.run_once(n))
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    log.error("  run %d at n=%d FAILED: %s", i + 1, n, exc)
            if not runs:
                results.append({"n": n, "failed": True, "failures": failures})
                continue

            def med(key: str) -> float:
                return statistics.median(r[key] for r in runs)

            row = {
                "n": n,
                "repeats": len(runs),
                "failures": failures,
                "repeated_data": repeated,
                "total_ms": med("total_ms"),
                "per_event_ms": med("total_ms") / n,
                "enrichment_ms": med("enrichment_ms"),
                "feature_extraction_ms": med("feature_extraction_ms"),
                "ml_inference_ms": med("ml_inference_ms"),
                "risk_priority_ms": med("risk_priority_ms"),
                "clustering_ms": med("clustering_ms"),
                "alert_generation_ms": med("alert_generation_ms"),
                "database_ms": med("database_ms"),
                "fire_events": int(med("_fire_events")),
                "alerts": int(med("_alerts")),
                "peak_rss_mb": peak_memory_mb(),
            }
            results.append(row)
            log.info(
                "  n=%-5d total %8.1f ms   per event %6.3f ms   ml %7.1f ms   "
                "cluster %7.1f ms   db %6.1f ms%s",
                n, row["total_ms"], row["per_event_ms"], row["ml_inference_ms"],
                row["clustering_ms"], row["database_ms"],
                "  [cycled data]" if repeated else "",
            )

    write_report(env, results, available, args.repeats)
    log.info("")
    log.info("report -> %s", OUT_PATH)


def write_report(env: dict, results: list[dict], available: int, repeats: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    lines: list[str] = []
    a = lines.append

    a("# Performance results")
    a("")
    a(f"Measured {ts} by `python -m ml.benchmark --repeats {repeats}`.")
    a("Every number below was produced by executing the pipeline on this machine.")
    a("Nothing here is estimated, extrapolated or copied from a previous run.")
    a("")
    a("## Environment")
    a("")
    a("| | |")
    a("|---|---|")
    for k, v in env.items():
        a(f"| {k.replace('_', ' ').title()} | {v} |")
    a(f"| Detections available | {available} real FIRMS detections in the snapshot |")
    a("")
    a("## What is measured")
    a("")
    a("Enrichment (facility proximity, land cover, recurrence), feature extraction,")
    a("ML inference, priority scoring, clustering, alert-rule evaluation and the")
    a("database write.")
    a("")
    a("**Excluded: NASA FIRMS and Overpass network time.** That is a third party's")
    a("latency, it varies with their load, and blending it into ours would produce a")
    a("number that describes neither. A cold live query is dominated by it.")
    a("")
    a("## Results")
    a("")
    a("Median of each stage across repeats.")
    a("")
    a("| Events | Total | Per event | Enrich | Features | ML | Priority | Cluster | Alert | DB | Failures |")
    a("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        if r.get("failed"):
            a(f"| {r['n']} | **FAILED** | — | — | — | — | — | — | — | — | {r['failures']} |")
            continue
        a(
            f"| {r['n']} | {r['total_ms']:.1f} ms | {r['per_event_ms']:.3f} ms | "
            f"{r['enrichment_ms']:.1f} | {r['feature_extraction_ms']:.1f} | "
            f"{r['ml_inference_ms']:.1f} | {r['risk_priority_ms']:.1f} | "
            f"{r['clustering_ms']:.1f} | {r['alert_generation_ms']:.1f} | "
            f"{r['database_ms']:.1f} | {r['failures']} |"
        )
    a("")
    a("| Events | Fire events formed | Alerts raised | Peak RSS |")
    a("|---:|---:|---:|---:|")
    for r in results:
        if r.get("failed"):
            continue
        rss = f"{r['peak_rss_mb']:.0f} MB" if r.get("peak_rss_mb") else "not measured"
        a(f"| {r['n']} | {r['fire_events']} | {r['alerts']} | {rss} |")
    a("")

    cycled = [r for r in results if r.get("repeated_data")]
    a("## Honesty notes")
    a("")
    if cycled:
        ns = ", ".join(str(r["n"]) for r in cycled)
        a(f"- **Scales {ns} exceed the {available} real detections in the snapshot.**")
        a("  Rather than fabricate detections to fill the gap, the benchmark cycles")
        a("  through the real set. This is honest about throughput but it makes the")
        a("  *clustering* figure optimistic: repeated detections share coordinates, so")
        a("  they collapse into the same fire events instead of forming new ones. Treat")
        a("  the clustering column at those scales as a lower bound.")
    else:
        a(f"- All scales fit within the {available} real detections available.")
    a("- Single process, single node, SQLite. There is no queue, no worker pool and")
    a("  no scheduled ingestion, so these figures describe one request on one machine.")
    a("- Timings use `perf_counter`, which is monotonic. Medians are reported rather")
    a("  than means so one slow run does not set the headline.")
    a("- The database figure is a local SQLite write. A networked PostGIS instance")
    a("  would be slower and is not measured here.")
    a("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

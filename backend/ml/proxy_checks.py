"""Consistency checks on real detections — NOT ground truth.

The model's headline metric (accuracy 1.0) is circular: the training labels come
from a nine-rule policy over the same features the model sees, so the score
measures faithful reproduction of that policy and nothing else.

These checks are a different, weaker thing. Each asks whether the classifier's
output agrees with independent map context that the *check* uses but the model's
rule policy did not decide the answer from. Agreement is evidence of internal
consistency. It is **not** evidence of correctness, because no detection in this
project has a verified cause.

Said plainly so nobody has to infer it: **a 90% agreement figure here does not
mean 90% of classifications are right.** It means the classifier and the map
agree 90% of the time about cases where the map has an opinion.

Run:  cd backend && .venv/Scripts/python.exe -m ml.proxy_checks
Writes: backend/ml/artifacts/proxy_checks.json
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from app.services import pipeline
from app.services import snapshot as snapshot_service
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    LC_CROPLAND,
    LC_FOREST,
    LC_GRASSLAND,
    LC_INDUSTRIAL,
    NATURAL_FIRE,
    UNKNOWN,
)

log = logging.getLogger("firetrace.proxy")

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "proxy_checks.json"

INDUSTRIAL_CLASSES = {INDUSTRIAL_FIRE, GAS_FLARE_OR_INDUSTRIAL_HEAT}
VEGETATION_CLASSES = {AGRICULTURAL_BURNING, NATURAL_FIRE}

# "Far from industry" for the vegetation check. Well beyond the 0.75 km onsite
# threshold and the 12 km search radius is the whole window, so 8 km is
# comfortably outside anything the facility feature treats as near.
FAR_FROM_INDUSTRY_KM = 8.0


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _pct(value: float | None) -> str:
    return "not measurable" if value is None else f"{value * 100:.1f}%"


def check_recurring_on_industrial_sites(events: list) -> dict[str, Any]:
    """Heat that repeats inside a mapped industrial site should read industrial.

    A thermal source detected on several separate days, sitting on an OSM
    industrial footprint, is a furnace, flare or kiln far more often than it is
    a crop fire. If the classifier disagrees with that, something is wrong.
    """
    considered = 0
    agreed = 0
    disagreed: Counter = Counter()

    for item in events:
        recurrence = item.evidence.recurrence
        facility_km = item.evidence.distance_to_nearest_facility_km
        land = item.evidence.land_cover.category

        on_site = facility_km is not None and facility_km <= 0.75
        industrial_ground = land == LC_INDUSTRIAL
        if not (recurrence.distinct_days >= 2 and (on_site or industrial_ground)):
            continue

        considered += 1
        label = item.classification.label
        if label in INDUSTRIAL_CLASSES:
            agreed += 1
        elif label != UNKNOWN:
            disagreed[label] += 1

    return {
        "name": "Recurring heat inside mapped industrial sites reads industrial",
        "considered": considered,
        "agreed": agreed,
        "abstained": considered - agreed - sum(disagreed.values()),
        "agreement": _rate(agreed, considered),
        "disagreements": dict(disagreed),
        "rule": (
            "Detections with >=2 distinct prior days AND either on a facility "
            "footprint (<=0.75 km) or on industrial land cover."
        ),
    }


def check_vegetation_away_from_industry(events: list) -> dict[str, Any]:
    """One-off heat over cropland or forest, far from industry, should not read
    industrial."""
    considered = 0
    agreed = 0
    disagreed: Counter = Counter()

    for item in events:
        recurrence = item.evidence.recurrence
        facility_km = item.evidence.distance_to_nearest_facility_km
        land = item.evidence.land_cover.category

        far = facility_km is None or facility_km >= FAR_FROM_INDUSTRY_KM
        vegetated = land in (LC_CROPLAND, LC_FOREST, LC_GRASSLAND)
        if not (recurrence.distinct_days == 0 and far and vegetated):
            continue

        considered += 1
        label = item.classification.label
        if label in VEGETATION_CLASSES:
            agreed += 1
        elif label != UNKNOWN:
            disagreed[label] += 1

    return {
        "name": "Single-day heat over vegetation far from industry reads agricultural or natural",
        "considered": considered,
        "agreed": agreed,
        "abstained": considered - agreed - sum(disagreed.values()),
        "agreement": _rate(agreed, considered),
        "disagreements": dict(disagreed),
        "rule": (
            f"Detections with no prior day at the location, >= {FAR_FROM_INDUSTRY_KM} km "
            "from any mapped facility, over cropland, forest or grassland."
        ),
    }


def check_firms_static_source_flag(events: list) -> dict[str, Any]:
    """Agreement with FIRMS's own persistent-source marker, where present.

    Some FIRMS products flag a detection as a known static heat source (type 2 in
    the MODIS/VIIRS `type` field). Where the archive carries it, that is an
    independent opinion about persistence, which is the one thing here not
    derived from our own rules.
    """
    carried = 0
    agreed = 0
    for item in events:
        raw = (item.event.firms_confidence_raw or "").strip()
        # The archive normalises FIRMS columns and does not retain `type`, so
        # this is recorded as unavailable rather than guessed at.
        if not raw:
            continue
        carried += 1

    return {
        "name": "Agreement with the FIRMS static-source flag",
        "considered": 0,
        "agreed": 0,
        "agreement": None,
        "status": "unavailable",
        "why": (
            "The FIRMS `type` field (0 vegetation, 1 active volcano, 2 other "
            "static land source, 3 offshore) is not retained by this project's "
            "normalisation, so there is nothing to compare against. Capturing it "
            "would make this the most useful check here, because it is the only "
            "persistence opinion that does not come from our own rules."
        ),
        "records_with_any_confidence_field": carried,
    }


def check_ablation_without_map_features(events: list) -> dict[str, Any]:
    """How much the classifier depends on map context.

    Not a retrain: this compares what the model said for detections that HAVE
    facility and land-cover context against what it said for detections that have
    neither. If the abstention rate is far higher without context, the evidence
    gate is doing its job and the model is not inventing confidence from position
    and radiative power alone.
    """
    with_context = {"n": 0, "abstained": 0, "scores": []}
    without_context = {"n": 0, "abstained": 0, "scores": []}

    for item in events:
        has_facility = item.evidence.distance_to_nearest_facility_km is not None
        has_land = item.evidence.land_cover.category != "unknown"
        bucket = with_context if (has_facility and has_land) else (
            without_context if not (has_facility or has_land) else None
        )
        if bucket is None:
            continue
        bucket["n"] += 1
        if item.classification.abstained:
            bucket["abstained"] += 1
        bucket["scores"].append(item.classification.confidence)

    def summarise(bucket: dict) -> dict:
        n = bucket["n"]
        scores = sorted(bucket["scores"])
        return {
            "detections": n,
            "abstained": bucket["abstained"],
            "abstention_rate": _rate(bucket["abstained"], n),
            "median_score": round(scores[len(scores) // 2], 4) if scores else None,
        }

    return {
        "name": "Ablation: classifier behaviour with and without map context",
        "with_map_context": summarise(with_context),
        "without_map_context": summarise(without_context),
        "rule": (
            "Compares detections that have BOTH a facility within the search "
            "radius and a land-cover polygon against those that have NEITHER. "
            "Not a retrain; it measures how the shipped model behaves when its "
            "two strongest context features are absent."
        ),
    }


def run(bbox: str | None = None, days: int = 1) -> dict[str, Any]:
    """Run every check against the committed archive."""
    result = pipeline.run_analysis(bbox, days=days, mode="demo")
    events = result.events

    snap = snapshot_service.load_snapshot()
    date_range = snap.meta.get("date_range") if snap else None

    checks = [
        check_recurring_on_industrial_sites(events),
        check_vegetation_away_from_industry(events),
        check_firms_static_source_flag(events),
        check_ablation_without_map_features(events),
    ]

    return {
        "title": "Consistency checks, not ground truth",
        "disclaimer": (
            "These compare the classifier against independent map context, not "
            "against verified incident reports. Agreement indicates internal "
            "consistency. It is NOT accuracy: no detection in this project has a "
            "verified cause, so an agreement figure here must never be quoted as "
            "a correctness rate."
        ),
        "detections_analysed": len(events),
        "archive_date_range": date_range,
        "checks": checks,
    }


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    report = run()

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  {report['title']}")
    print(f"  {'-' * 68}")
    print(f"  {report['detections_analysed']} detections analysed from the archive\n")
    for check in report["checks"]:
        print(f"  {check['name']}")
        if check.get("status") == "unavailable":
            print("    unavailable — see the report for why\n")
            continue
        if "with_map_context" in check:
            a, b = check["with_map_context"], check["without_map_context"]
            print(
                f"    with context:    {a['detections']:4d} detections, "
                f"{_pct(a['abstention_rate'])} abstained, median score {a['median_score']}"
            )
            print(
                f"    without context: {b['detections']:4d} detections, "
                f"{_pct(b['abstention_rate'])} abstained, median score {b['median_score']}\n"
            )
            continue
        print(
            f"    {check['agreed']}/{check['considered']} agreed "
            f"({_pct(check['agreement'])}), {check['abstained']} abstained"
        )
        if check["disagreements"]:
            print(f"    disagreements: {check['disagreements']}")
        print()
    print(f"  written to {ARTIFACT.relative_to(ARTIFACT.parents[2])}\n")


if __name__ == "__main__":
    main()

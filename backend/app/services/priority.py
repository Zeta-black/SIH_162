"""FIRETRACE Priority Score.

A deliberately transparent weighted sum, not a second opaque model. Every
component is a named number between 0 and 1, every weight is configurable, and
the API returns both alongside the score so a user can see exactly how a value
was reached and disagree with it.

This is an operator triage aid invented for this prototype. It is not an
official government risk rating and has not been validated against outcomes.

    score = 0.20 * model_vote_score
          + 0.25 * class_severity
          + 0.20 * thermal_severity
          + 0.15 * industrial_proximity
          + 0.10 * abnormality
          + 0.10 * recency

`abnormality` is the component worth explaining at a demo: a flare stack that
burns every single day is routine and should sink down the queue, while a
strong detection at a plant that has never lit up before is exactly what an
emergency team wants at the top. So persistence *lowers* priority here.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.config import settings
from app.schemas import Classification, HotspotEvent, NearestFacility, PriorityResult, RecurrenceResult
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    INDUSTRIAL_FIRE,
    NATURAL_FIRE,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    UNKNOWN,
)

# How much attention each class warrants from an industrial-safety desk. An
# unknown event scores mid-range on purpose: it is unresolved, not harmless.
CLASS_SEVERITY: dict[str, float] = {
    INDUSTRIAL_FIRE: 1.00,
    GAS_FLARE_OR_INDUSTRIAL_HEAT: 0.55,
    UNKNOWN: 0.45,
    AGRICULTURAL_BURNING: 0.20,
    NATURAL_FIRE: 0.35,
}

RECENCY_HALF_LIFE_DAYS = 3.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def thermal_severity(event: HotspotEvent) -> float:
    """Normalise FRP onto 0-1 using a log scale.

    Log, because fire radiative power spans several orders of magnitude and a
    linear scale would flatten everything below a refinery flare to zero.
    """
    if event.frp_mw is None:
        # Fall back to brightness when FRP is absent, over the range where
        # VIIRS/MODIS detections actually vary (300-400 K).
        if event.brightness_k is None:
            return 0.35  # neutral: absence of data is not evidence of low severity
        return _clamp((event.brightness_k - 300.0) / 100.0)
    saturation = max(1.0, settings.priority_frp_saturation_mw)
    return _clamp(math.log1p(max(0.0, event.frp_mw)) / math.log1p(saturation))


def industrial_proximity(facility: NearestFacility | None) -> float:
    """1.0 on the facility footprint, decaying to 0 at the search radius."""
    if facility is None:
        return 0.0
    radius = max(0.1, settings.facility_search_radius_km)
    return _clamp(1.0 - (facility.distance_km / radius))


def abnormality(recurrence: RecurrenceResult) -> float:
    """How unusual this detection is for this location."""
    if not recurrence.history_available:
        return 0.5  # no history loaded: neither routine nor novel
    return _clamp(1.0 - recurrence.persistence_ratio)


def recency(event: HotspotEvent, now: datetime | None = None) -> float:
    """Exponential decay on detection age."""
    now = now or datetime.now(timezone.utc)
    acquired = event.acquired_at
    if acquired.tzinfo is None:
        acquired = acquired.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - acquired).total_seconds() / 86400.0)
    return _clamp(math.exp(-age_days / RECENCY_HALF_LIFE_DAYS))


def compute_priority(
    event: HotspotEvent,
    classification: Classification,
    facility: NearestFacility | None,
    recurrence: RecurrenceResult,
    now: datetime | None = None,
) -> PriorityResult:
    components = {
        "model_confidence": round(_clamp(classification.confidence), 4),
        "class_severity": round(CLASS_SEVERITY.get(classification.label, 0.4), 4),
        "thermal_severity": round(thermal_severity(event), 4),
        "industrial_proximity": round(industrial_proximity(facility), 4),
        "abnormality": round(abnormality(recurrence), 4),
        "recency": round(recency(event, now), 4),
    }
    weights = {
        "model_confidence": settings.priority_weight_confidence,
        "class_severity": settings.priority_weight_industrial_class,
        "thermal_severity": settings.priority_weight_thermal,
        "industrial_proximity": settings.priority_weight_proximity,
        "abnormality": settings.priority_weight_abnormality,
        "recency": settings.priority_weight_recency,
    }

    total_weight = sum(weights.values()) or 1.0
    score = sum(components[k] * weights[k] for k in components) / total_weight
    score = round(_clamp(score), 4)

    if score >= settings.priority_high_threshold:
        level = PRIORITY_HIGH
    elif score >= settings.priority_medium_threshold:
        level = PRIORITY_MEDIUM
    else:
        level = PRIORITY_LOW

    return PriorityResult(
        score=score,
        level=level,  # type: ignore[arg-type]
        components=components,
        weights={k: round(v / total_weight, 4) for k, v in weights.items()},
    )


def formula_description() -> dict[str, object]:
    """Exposed by the API so the dashboard can show the formula verbatim."""
    return {
        "name": "FIRETRACE Priority Score",
        "type": "transparent weighted sum",
        "range": [0.0, 1.0],
        "components": {
            "model_confidence": (
                "Uncalibrated Random Forest vote share for the leading trained class; "
                "not a calibrated probability."
            ),
            "class_severity": "How much attention the predicted class warrants.",
            "thermal_severity": "Fire radiative power on a log scale, or brightness if FRP is absent.",
            "industrial_proximity": "1.0 on a mapped facility, decaying to 0 at the search radius.",
            "abnormality": "1 - persistence. A source that burns every day scores low.",
            "recency": "Exponential decay on detection age (3-day half-life).",
        },
        "weights": {
            "model_confidence": settings.priority_weight_confidence,
            "class_severity": settings.priority_weight_industrial_class,
            "thermal_severity": settings.priority_weight_thermal,
            "industrial_proximity": settings.priority_weight_proximity,
            "abnormality": settings.priority_weight_abnormality,
            "recency": settings.priority_weight_recency,
        },
        "thresholds": {
            "high": settings.priority_high_threshold,
            "medium": settings.priority_medium_threshold,
        },
        "caveat": (
            "Prototype triage aid defined by this project. Not an official risk rating and "
            "not validated against incident outcomes."
        ),
    }

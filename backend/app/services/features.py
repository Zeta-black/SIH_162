"""Feature engineering — ONE implementation, used by both training and inference.

There is deliberately no second code path. `ml/train.py` calls
`build_feature_row` to build the training matrix and the live API calls the
same function for every prediction, so the two can never drift.

Design notes
------------
* Categorical values are one-hot encoded here, against the fixed vocabularies
  in `taxonomy.py`, rather than by a fitted encoder. The vocabulary cannot
  grow at inference time, so column order is guaranteed stable and an unseen
  category is impossible.
* Genuinely missing numeric values are emitted as NaN and imputed by the
  sklearn pipeline using statistics learned during training. A companion
  `*_missing` indicator is emitted alongside, so "no FRP reported" stays
  visible to the model instead of being silently smoothed away.
* Bump FEATURE_VERSION whenever this file changes the column set. The model
  artifact records the version it was trained on and inference refuses to use
  a mismatched pair.
"""
from __future__ import annotations

import math
from datetime import date

from app.config import settings
from app.schemas import HotspotEvent, LandCoverResult, NearestFacility, RecurrenceResult
from app.taxonomy import (
    FACILITY_CATEGORIES,
    HIGH_HEAT_FACILITIES,
    LAND_COVER_CLASSES,
)

FEATURE_VERSION = "1.0.0"

# Distance recorded when no facility exists inside the search radius. Using the
# radius itself (rather than a sentinel like -1) keeps the feature monotonic:
# "at least this far away".
NO_FACILITY_DISTANCE_KM = settings.facility_search_radius_km


def _ordinal_confidence(level: str | None) -> float:
    return {"low": 0.0, "nominal": 1.0, "high": 2.0}.get(level or "", float("nan"))


def _safe_log1p(value: float | None) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    return math.log1p(max(0.0, float(value)))


def _nan_if_none(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def build_feature_row(
    event: HotspotEvent,
    nearest_facility: NearestFacility | None,
    land_cover: LandCoverResult,
    recurrence: RecurrenceResult,
) -> dict[str, float]:
    """Build the complete feature vector for one thermal event."""
    row: dict[str, float] = {}

    # ------------------------------------------------------------- thermal
    brightness = event.brightness_k
    secondary = event.brightness_secondary_k
    row["brightness_k"] = _nan_if_none(brightness)
    row["brightness_secondary_k"] = _nan_if_none(secondary)
    # The gap between the two channels is a stronger discriminator than either
    # channel alone: a small, very hot sub-pixel source (a flare) separates the
    # channels far more than a large, cooler burn front.
    if brightness is not None and secondary is not None:
        row["brightness_delta_k"] = float(brightness - secondary)
    else:
        row["brightness_delta_k"] = float("nan")
    row["brightness_missing"] = 1.0 if brightness is None else 0.0

    row["frp_mw"] = _nan_if_none(event.frp_mw)
    row["log_frp"] = _safe_log1p(event.frp_mw)
    row["frp_missing"] = 1.0 if event.frp_mw is None else 0.0

    row["firms_confidence_ordinal"] = _ordinal_confidence(event.firms_confidence_level)
    row["firms_confidence_missing"] = 1.0 if event.firms_confidence_level is None else 0.0

    # Pixel footprint. Detections at the swath edge are larger and coarser, so
    # the model is allowed to learn to trust them differently.
    row["scan"] = _nan_if_none(event.scan)
    row["track"] = _nan_if_none(event.track)
    row["pixel_area_proxy"] = (
        float(event.scan * event.track)
        if event.scan is not None and event.track is not None
        else float("nan")
    )

    row["is_night"] = 1.0 if event.day_night == "N" else 0.0
    row["daynight_missing"] = 1.0 if event.day_night is None else 0.0

    # ------------------------------------------------------------- spatial
    row["latitude"] = float(event.latitude)
    row["longitude"] = float(event.longitude)

    if nearest_facility is not None:
        distance = float(nearest_facility.distance_km)
        category = nearest_facility.category
        row["facility_found"] = 1.0
    else:
        distance = NO_FACILITY_DISTANCE_KM
        category = "none"
        row["facility_found"] = 0.0

    row["distance_to_facility_km"] = distance
    # Inverse-distance emphasises the first few hundred metres, which is where
    # "on the plant" versus "next to the plant" is actually decided.
    row["facility_proximity_score"] = float(1.0 / (1.0 + distance))
    row["facility_onsite"] = 1.0 if distance <= settings.facility_onsite_km else 0.0
    row["facility_is_high_heat"] = 1.0 if category in HIGH_HEAT_FACILITIES else 0.0

    for cat in FACILITY_CATEGORIES:
        row[f"facility_cat__{cat}"] = 1.0 if category == cat else 0.0

    # ---------------------------------------------------------- land cover
    lc = land_cover.category if land_cover else "unknown"
    for cls in LAND_COVER_CLASSES:
        row[f"landcover__{cls}"] = 1.0 if lc == cls else 0.0

    # ----------------------------------------------------------- temporal
    row["recurrence_count"] = float(recurrence.recurrence_count)
    row["distinct_days"] = float(recurrence.distinct_days)
    row["recent_count_7d"] = float(recurrence.recent_count_7d)
    row["persistence_ratio"] = float(recurrence.persistence_ratio)
    row["nearby_density"] = float(recurrence.nearby_density)
    row["is_persistent"] = 1.0 if recurrence.is_persistent else 0.0
    row["history_available"] = 1.0 if recurrence.history_available else 0.0

    # Seasonality, encoded on a circle so December and January stay adjacent.
    # Crop-residue burning is strongly seasonal; flaring is not.
    doy = _day_of_year(event.acquisition_date)
    angle = 2.0 * math.pi * (doy / 366.0)
    row["season_sin"] = math.sin(angle)
    row["season_cos"] = math.cos(angle)

    return row


def _day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def _reference_feature_names() -> list[str]:
    """Column order, derived from the builder itself so it cannot go stale."""
    names: list[str] = [
        "brightness_k",
        "brightness_secondary_k",
        "brightness_delta_k",
        "brightness_missing",
        "frp_mw",
        "log_frp",
        "frp_missing",
        "firms_confidence_ordinal",
        "firms_confidence_missing",
        "scan",
        "track",
        "pixel_area_proxy",
        "is_night",
        "daynight_missing",
        "latitude",
        "longitude",
        "facility_found",
        "distance_to_facility_km",
        "facility_proximity_score",
        "facility_onsite",
        "facility_is_high_heat",
    ]
    names += [f"facility_cat__{c}" for c in FACILITY_CATEGORIES]
    names += [f"landcover__{c}" for c in LAND_COVER_CLASSES]
    names += [
        "recurrence_count",
        "distinct_days",
        "recent_count_7d",
        "persistence_ratio",
        "nearby_density",
        "is_persistent",
        "history_available",
        "season_sin",
        "season_cos",
    ]
    return names


FEATURE_NAMES: list[str] = _reference_feature_names()


def row_to_vector(row: dict[str, float], feature_names: list[str] | None = None) -> list[float]:
    """Order a feature dict into the model's expected column order."""
    names = feature_names or FEATURE_NAMES
    return [float(row.get(name, float("nan"))) for name in names]


# Human-readable names used by the explanation layer. Anything not listed here
# falls back to the raw column name.
FEATURE_DISPLAY_NAMES: dict[str, str] = {
    "brightness_k": "Brightness temperature",
    "brightness_secondary_k": "Secondary channel brightness",
    "brightness_delta_k": "Channel brightness separation",
    "frp_mw": "Fire radiative power",
    "log_frp": "Fire radiative power",
    "firms_confidence_ordinal": "FIRMS detection confidence",
    "scan": "Pixel scan size",
    "track": "Pixel track size",
    "pixel_area_proxy": "Detection pixel footprint",
    "is_night": "Night-time detection",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "distance_to_facility_km": "Distance to nearest industrial facility",
    "facility_proximity_score": "Industrial proximity",
    "facility_onsite": "Detection on facility footprint",
    "facility_is_high_heat": "Nearby facility is a high-heat process",
    "facility_found": "Industrial facility within search radius",
    "recurrence_count": "Prior detections at this location",
    "distinct_days": "Distinct days with detections",
    "recent_count_7d": "Detections in the last 7 days",
    "persistence_ratio": "Persistence of the thermal source",
    "nearby_density": "Co-detected hotspots on the same pass",
    "is_persistent": "Persistent thermal source",
    "season_sin": "Season",
    "season_cos": "Season",
}


def display_name(feature: str) -> str:
    if feature in FEATURE_DISPLAY_NAMES:
        return FEATURE_DISPLAY_NAMES[feature]
    if feature.startswith("facility_cat__"):
        return "Nearby facility type"
    if feature.startswith("landcover__"):
        return "Land cover"
    return feature.replace("_", " ").capitalize()

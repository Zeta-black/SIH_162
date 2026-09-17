"""Pydantic models describing everything that crosses the API boundary.

The normalized hotspot schema is the single internal representation. FIRMS
products do not all expose the same columns (VIIRS reports `bright_ti4` and a
letter confidence; MODIS reports `brightness` and a 0-100 confidence), so the
FIRMS service maps each product onto this shape and records what it could not
supply rather than inventing a value.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core observation
# ---------------------------------------------------------------------------
class HotspotEvent(BaseModel):
    """One normalized thermal hotspot detection."""

    event_id: str = Field(description="Deterministic ID derived from position, time and source.")
    latitude: float
    longitude: float
    acquisition_date: date
    acquisition_time: str = Field(description="UTC HH:MM as reported by the FIRMS product.")
    acquired_at: datetime = Field(description="Combined UTC timestamp.")

    brightness_k: float | None = Field(
        default=None,
        description="Brightness temperature in Kelvin (VIIRS I-4 or MODIS band 21/22).",
    )
    brightness_secondary_k: float | None = Field(
        default=None, description="Secondary channel brightness (VIIRS I-5 or MODIS band 31)."
    )
    frp_mw: float | None = Field(default=None, description="Fire radiative power in megawatts.")

    firms_confidence_raw: str | None = Field(
        default=None, description="Confidence exactly as the product reported it."
    )
    firms_confidence_level: Literal["low", "nominal", "high"] | None = Field(
        default=None, description="Product confidence normalized to three levels."
    )

    satellite: str | None = None
    instrument: str | None = None
    day_night: Literal["D", "N"] | None = None
    scan: float | None = None
    track: float | None = None
    version: str | None = None

    source_product: str = Field(description="FIRMS product, e.g. VIIRS_NOAA21_NRT.")
    source_mode: Literal["live", "snapshot"] = Field(
        description="live = fetched from NASA now; snapshot = frozen historical file."
    )
    raw_source_reference: str = Field(description="Which request or file this record came from.")
    ingested_at: datetime

    unavailable_fields: list[str] = Field(
        default_factory=list,
        description="Fields this FIRMS product did not supply. Never back-filled with fake values.",
    )


# ---------------------------------------------------------------------------
# Geographic context
# ---------------------------------------------------------------------------
class Facility(BaseModel):
    """An industrial feature taken from OpenStreetMap."""

    facility_id: str
    name: str | None = None
    category: str
    category_label: str
    latitude: float
    longitude: float
    osm_type: str
    osm_id: int
    tags: dict[str, str] = Field(default_factory=dict)


class NearestFacility(BaseModel):
    facility_id: str
    name: str | None
    category: str
    category_label: str
    latitude: float
    longitude: float
    distance_km: float


class LandCoverResult(BaseModel):
    category: str
    label: str
    provider: Literal["osm_landuse", "snapshot", "unavailable"]
    source_note: str
    matched_osm_tag: str | None = None


class RecurrenceResult(BaseModel):
    """Temporal behaviour of the thermal source at this location."""

    recurrence_count: int = Field(description="Prior detections within the recurrence radius.")
    distinct_days: int = Field(description="Distinct prior days on which this source was detected.")
    recent_count_7d: int
    first_seen: date | None = None
    last_seen_before_event: date | None = None
    persistence_ratio: float = Field(
        description="distinct_days divided by days in the observed window; 1.0 means every day."
    )
    nearby_density: int = Field(description="Detections within the density radius on the same day.")
    is_persistent: bool
    window_days: int
    radius_km: float
    history_available: bool = Field(
        description="False when no history is loaded, in which case counts are not evidence."
    )


# ---------------------------------------------------------------------------
# Model output
# ---------------------------------------------------------------------------
class Factor(BaseModel):
    """One human-readable line of the explanation."""

    direction: Literal["supports", "counters", "neutral"]
    text: str
    feature: str
    value: str | None = None
    importance: float | None = Field(
        default=None, description="Model global importance for this feature (0-1)."
    )


class Classification(BaseModel):
    label: str
    label_display: str
    description: str
    confidence: float = Field(
        description=(
            "Uncalibrated Random Forest vote share for the leading trained class; "
            "not a verified probability or a real-world correctness estimate."
        )
    )
    confidence_level: Literal["HIGH", "MEDIUM", "LOW"]
    abstained: bool = Field(
        description="True when the top probability fell below the abstention threshold."
    )
    top_trained_label: str = Field(
        description="Highest-probability trained class, kept visible even when abstaining."
    )


class PriorityResult(BaseModel):
    score: float
    level: Literal["HIGH", "MEDIUM", "LOW"]
    components: dict[str, float]
    weights: dict[str, float]


class Evidence(BaseModel):
    distance_to_nearest_facility_km: float | None
    nearest_facility: NearestFacility | None
    land_cover: LandCoverResult
    recurrence: RecurrenceResult
    thermal_intensity_k: float | None
    frp_mw: float | None
    firms_confidence: str | None
    day_night: str | None


class ModelInfo(BaseModel):
    name: str
    algorithm: str
    model_version: str
    training_data_version: str
    feature_version: str
    trained_at: str | None
    n_features: int
    classes: list[str]
    loaded: bool
    status_note: str


class ClassifiedEvent(BaseModel):
    """A hotspot plus everything FIRETRACE derived about it."""

    event: HotspotEvent
    classification: Classification
    probabilities: dict[str, float]
    evidence: Evidence
    factors: list[Factor]
    priority: PriorityResult
    model: ModelInfo
    disclaimer: str


# ---------------------------------------------------------------------------
# API envelopes
# ---------------------------------------------------------------------------
class DataSourceStatus(BaseModel):
    mode: Literal["live", "snapshot"]
    label: str
    firms_status: Literal["ok", "unavailable", "not_configured", "no_data"]
    firms_message: str
    firms_products_used: list[str]
    osm_status: Literal["ok", "cached", "unavailable", "snapshot"]
    osm_message: str
    land_cover_provider: str
    last_updated: datetime
    snapshot_note: str | None = None


class SummaryCounts(BaseModel):
    total_events: int
    industrial_related: int
    high_priority: int
    low_confidence: int
    persistent_sources: int
    by_class: dict[str, int]
    by_priority: dict[str, int]
    frp_total_mw: float
    date_range: dict[str, str | None]


class EventsResponse(BaseModel):
    status: DataSourceStatus
    summary: SummaryCounts
    events: list[ClassifiedEvent]
    returned: int
    total_matching: int


class ClassifyRequest(BaseModel):
    """Ad-hoc classification of a coordinate the user supplies."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    acquisition_date: date | None = None
    acquisition_time: str | None = Field(default=None, pattern=r"^\d{1,2}:?\d{2}$")
    brightness_k: float | None = Field(default=None, gt=0, lt=1000)
    frp_mw: float | None = Field(default=None, ge=0, le=100000)
    day_night: Literal["D", "N"] | None = None
    firms_confidence: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    model_loaded: bool
    firms_key_configured: bool
    store_ready: bool
    snapshot_available: bool
    checks: dict[str, Any]

"""Central configuration for FIRETRACE.

Every tunable number in the system lives here so that nothing important is
buried as a magic constant inside business logic. Values can be overridden
through environment variables or a .env file (see .env.example).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "app" / "data"
CACHE_DIR = DATA_DIR / "cache"
ML_DIR = BACKEND_DIR / "ml"
ARTIFACT_DIR = ML_DIR / "artifacts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    # ---------------------------------------------------------------- general
    app_name: str = "FIRETRACE"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ------------------------------------------------------------ NASA FIRMS
    # The MAP_KEY is a secret. It is read here, server-side only, and is never
    # serialised into any API response or sent to the browser.
    firms_map_key: str = Field(default="", alias="FIRMS_MAP_KEY")
    firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov"
    # FIRMS has announced that Suomi-NPP delivery ceases in November 2026;
    # NOAA-21 and NOAA-20 are the forward-looking 375 m VIIRS sources.
    # The first product is the interactive primary. Remaining products are
    # fallbacks, rather than three mandatory downloads for every map load.
    firms_sources: str = "VIIRS_NOAA21_NRT,VIIRS_NOAA20_NRT,MODIS_NRT"
    firms_timeout_seconds: float = 45.0
    # Hard limit imposed by the FIRMS area API itself: it rejects anything
    # outside [1..5] with HTTP 400 'Invalid day range'. Verified against the
    # live endpoint, not assumed.
    firms_max_day_range: int = 5
    # Default area of interest: India (west, south, east, north).
    firms_default_bbox: str = "68.0,6.5,97.5,36.0"
    # One day is fresh enough for the operations view and keeps its first
    # request bounded. Operators can intentionally expand it to five days.
    firms_default_day_range: int = 1

    # ------------------------------------------------------------------- OSM
    # Overpass mirrors are tried in order. Public instances are rate limited,
    # so results are cached on disk and reused.
    # Order matters: the main instance answers most reliably provided a real
    # User-Agent is sent (it returns HTTP 406 without one). The mirrors behind
    # it were observed returning HTTP 504 under load, which is exactly why the
    # client fails over rather than trusting any single host.
    overpass_endpoints: str = (
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter"
    )
    # Kept tight on purpose. A mirror that has not answered in 40s is
    # overloaded, and waiting longer just delays the failover to the next
    # one. Observed 504s and read timeouts are common under load.
    overpass_timeout_seconds: float = 40.0
    overpass_user_agent: str = "FIRETRACE/1.0 (SIH2026 prototype; thermal anomaly research)"
    overpass_cache_ttl_hours: int = 168  # one week
    # Overpass queries are snapped to a grid so nearby requests reuse one cache
    # entry instead of hammering the public API with near-identical bboxes.
    osm_tile_degrees: float = 1.0
    # Wall-clock budget for gathering OSM context during a LIVE dashboard
    # request. Overpass under load takes ~50s per tile (one mirror times out
    # before the next answers), and a dozen tiles would mean a request that
    # never returns. Once the budget is spent the remaining tiles are served
    # from disk cache only, so latency stays bounded and the response still
    # arrives -- with its osm_status saying what was actually available.
    # This budget is applied independently to facilities and land cover. Two
    # seconds keeps a cold live dashboard request responsive even when public
    # Overpass is unavailable; cached/snapshot context remains usable.
    osm_live_budget_seconds: float = 2.0

    # ------------------------------------------------------------- classifier
    # UNKNOWN is not a trained class. It is an abstention applied when the
    # model's top probability falls below this threshold.
    unknown_abstention_threshold: float = 0.45
    # A HIGHER bar applied when the discriminating evidence was not available.
    #
    # Two of the model's four strongest features are facility proximity and
    # land cover. When a detection has neither — no mapped facility inside the
    # search radius and no land-use polygon covering it — the forest is voting
    # mostly on latitude, longitude and radiative power, and it will still
    # return a confident-looking number.
    #
    # Measured on a live India-wide September query, 810 of 900 detections came
    # back as AGRICULTURAL_BURNING at a median confidence of 0.66, of which 800
    # had unknown land cover and 804 had no facility within 12 km — in a month
    # that is not a crop-residue burning season. The model had learned that
    # absence of evidence looks like cropland. Raising the bar where evidence is
    # thin turns most of those into an honest "unclassified".
    low_evidence_abstention_threshold: float = 0.72
    confidence_high_threshold: float = 0.75
    confidence_medium_threshold: float = 0.50

    # --------------------------------------------------------------- features
    # Radius used when searching OSM for the nearest industrial facility.
    facility_search_radius_km: float = 12.0
    # A hotspot closer than this to an industrial facility is treated as
    # "on-site" by the explanation layer.
    facility_onsite_km: float = 0.75
    # Recurrence: how far back to look, and the radius that counts as "the
    # same thermal source" when matching a hotspot against history.
    recurrence_radius_km: float = 1.0
    recurrence_lookback_days: int = 60
    density_radius_km: float = 5.0

    # --------------------------------------------------------- priority score
    # Transparent weighted sum; documented in README and exposed by the API.
    priority_weight_confidence: float = 0.20
    priority_weight_industrial_class: float = 0.25
    priority_weight_thermal: float = 0.20
    priority_weight_proximity: float = 0.15
    priority_weight_abnormality: float = 0.10
    priority_weight_recency: float = 0.10
    priority_high_threshold: float = 0.65
    priority_medium_threshold: float = 0.40
    # FRP (MW) value treated as the top of the normalisation scale.
    priority_frp_saturation_mw: float = 100.0

    # ------------------------------------------------------------------ store
    database_path: str = str(DATA_DIR / "firetrace.sqlite3")
    # Live fetches are cached for this long before FIRMS is queried again.
    live_cache_ttl_minutes: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def firms_source_list(self) -> list[str]:
        return [s.strip() for s in self.firms_sources.split(",") if s.strip()]

    @property
    def overpass_endpoint_list(self) -> list[str]:
        return [e.strip() for e in self.overpass_endpoints.split(",") if e.strip()]

    @property
    def has_firms_key(self) -> bool:
        return bool(self.firms_map_key and self.firms_map_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

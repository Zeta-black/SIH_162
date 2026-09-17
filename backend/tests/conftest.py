"""Shared fixtures.

Tests must never touch the network or the real database. Every fixture here
builds its objects in memory or in a tmp_path.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Facility, HotspotEvent, LandCoverResult, NearestFacility  # noqa: E402
from app.services.osm import LandusePolygon  # noqa: E402
from app.taxonomy import LC_CROPLAND, LC_INDUSTRIAL, LC_UNKNOWN  # noqa: E402


def make_event(
    event_id: str = "EVT-TEST000001",
    lat: float = 22.3,
    lon: float = 69.8,
    acq_date: date | None = None,
    acq_time: str = "07:48",
    brightness: float | None = 336.6,
    secondary: float | None = 298.3,
    frp: float | None = 12.5,
    confidence: str | None = "nominal",
    day_night: str | None = "D",
    product: str = "VIIRS_SNPP_SP",
    scan: float | None = 0.6,
    track: float | None = 0.53,
) -> HotspotEvent:
    acq_date = acq_date or date(2026, 3, 15)
    hh, mm = (int(x) for x in acq_time.split(":"))
    return HotspotEvent(
        event_id=event_id,
        latitude=lat,
        longitude=lon,
        acquisition_date=acq_date,
        acquisition_time=acq_time,
        acquired_at=datetime(acq_date.year, acq_date.month, acq_date.day, hh, mm, tzinfo=timezone.utc),
        brightness_k=brightness,
        brightness_secondary_k=secondary,
        frp_mw=frp,
        firms_confidence_raw="n",
        firms_confidence_level=confidence,
        satellite="N",
        instrument="VIIRS",
        day_night=day_night,
        scan=scan,
        track=track,
        version="2.0NRT",
        source_product=product,
        source_mode="snapshot",
        raw_source_reference="test fixture",
        ingested_at=datetime.now(timezone.utc),
        unavailable_fields=[],
    )


@pytest.fixture
def event() -> HotspotEvent:
    return make_event()


@pytest.fixture
def event_factory():
    return make_event


@pytest.fixture
def facility() -> Facility:
    return Facility(
        facility_id="W12345",
        name="Test Refinery",
        category="refinery",
        category_label="Oil / petrochemical refinery",
        latitude=22.3005,
        longitude=69.8005,
        osm_type="way",
        osm_id=12345,
        tags={"name": "Test Refinery", "industrial": "oil"},
    )


@pytest.fixture
def nearest_facility() -> NearestFacility:
    return NearestFacility(
        facility_id="W12345",
        name="Test Refinery",
        category="refinery",
        category_label="Oil / petrochemical refinery",
        latitude=22.3005,
        longitude=69.8005,
        distance_km=0.32,
    )


@pytest.fixture
def land_cover_industrial() -> LandCoverResult:
    return LandCoverResult(
        category=LC_INDUSTRIAL,
        label="Industrial / built-up",
        provider="osm_landuse",
        source_note="test",
        matched_osm_tag="landuse=industrial",
    )


@pytest.fixture
def land_cover_cropland() -> LandCoverResult:
    return LandCoverResult(
        category=LC_CROPLAND,
        label="Cropland / agriculture",
        provider="osm_landuse",
        source_note="test",
        matched_osm_tag="landuse=farmland",
    )


@pytest.fixture
def land_cover_unknown() -> LandCoverResult:
    return LandCoverResult(
        category=LC_UNKNOWN,
        label="Unknown",
        provider="unavailable",
        source_note="test",
        matched_osm_tag=None,
    )


@pytest.fixture
def square_polygon() -> LandusePolygon:
    """A 0.1 x 0.1 degree square with its lower-left corner at (22.0, 69.0)."""
    ring = [(22.0, 69.0), (22.0, 69.1), (22.1, 69.1), (22.1, 69.0), (22.0, 69.0)]
    return LandusePolygon(
        category=LC_INDUSTRIAL,
        tag="landuse=industrial",
        ring=ring,
        min_lat=22.0,
        min_lon=69.0,
        max_lat=22.1,
        max_lon=69.1,
        area_deg2=0.01,
    )


@pytest.fixture
def history_events():
    """A persistent source detected daily, plus one one-off nearby."""
    base = date(2026, 3, 15)
    events = [
        make_event(
            event_id=f"EVT-HIST{i:06d}",
            lat=22.3,
            lon=69.8,
            acq_date=base - timedelta(days=i),
        )
        for i in range(1, 11)
    ]
    events.append(
        make_event(event_id="EVT-FAR000001", lat=23.9, lon=70.9, acq_date=base - timedelta(days=2))
    )
    return events

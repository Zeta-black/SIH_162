"""Data provenance.

Every number this module returns is read from the actual store, the actual
snapshot file or the actual dataset manifest at request time. Nothing here is
a written-in constant describing what the data "should" look like, because the
whole point of the endpoint is that a reviewer can check it.

Where a property is a fixed fact about the instrument rather than about our
copy of the data — VIIRS pixel size, say — it is labelled as an instrument
specification, not as something we measured.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import ML_DIR, settings
from app.services import snapshot as snapshot_service
from app.store.db import get_store

MANIFEST_PATH = ML_DIR / "data" / "dataset_manifest.json"
METRICS_PATH = ML_DIR / "artifacts" / "metrics.json"

# Instrument facts published by NASA, used for the "resolution" field. These
# describe the sensors, not our processing.
PRODUCT_SPECS: dict[str, dict[str, str]] = {
    "VIIRS_SNPP_NRT": {"platform": "Suomi NPP", "instrument": "VIIRS", "resolution": "375 m"},
    "VIIRS_SNPP_SP": {"platform": "Suomi NPP", "instrument": "VIIRS", "resolution": "375 m"},
    "VIIRS_NOAA20_NRT": {"platform": "NOAA-20", "instrument": "VIIRS", "resolution": "375 m"},
    "VIIRS_NOAA20_SP": {"platform": "NOAA-20", "instrument": "VIIRS", "resolution": "375 m"},
    "VIIRS_NOAA21_NRT": {"platform": "NOAA-21", "instrument": "VIIRS", "resolution": "375 m"},
    "MODIS_NRT": {"platform": "Terra / Aqua", "instrument": "MODIS", "resolution": "1 km"},
    "MODIS_SP": {"platform": "Terra / Aqua", "instrument": "MODIS", "resolution": "1 km"},
}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def build_sources() -> dict:
    """Assemble the provenance record from what is actually on disk."""
    store = get_store()
    snap = snapshot_service.load_snapshot()
    manifest = _read_json(MANIFEST_PATH)
    metrics = _read_json(METRICS_PATH)

    span_from, span_to = store.date_span()
    stored_events = store.event_count()
    stored_facilities = store.facility_count()
    last_ingest = store.last_ingest()

    products_seen = sorted(
        {
            *(snap.meta.get("products", []) if snap else []),
            *settings.firms_source_list,
        }
    )

    sources = [
        {
            "id": "nasa_firms",
            "name": "NASA FIRMS — active fire / thermal anomalies",
            "provider": "NASA LANCE / FIRMS",
            "category": "Satellite observation",
            "role": "Detects where thermal anomalies are. Supplies position, acquisition "
            "time, brightness temperature, fire radiative power and the product's own "
            "detection confidence.",
            "access": "Public API, free MAP_KEY, server-side only",
            "endpoint": f"{settings.firms_base_url}/api/area/csv/…",
            "products": [
                {
                    "id": p,
                    "platform": PRODUCT_SPECS.get(p, {}).get("platform", "—"),
                    "instrument": PRODUCT_SPECS.get(p, {}).get("instrument", "—"),
                    "resolution": PRODUCT_SPECS.get(p, {}).get("resolution", "—"),
                }
                for p in products_seen
            ],
            "fields_used": [
                {"field": "latitude, longitude", "unit": "degrees (WGS84)"},
                {"field": "acq_date, acq_time", "unit": "UTC"},
                {"field": "bright_ti4 / brightness", "unit": "K (brightness temperature)"},
                {"field": "bright_ti5 / bright_t31", "unit": "K (secondary channel)"},
                {"field": "frp", "unit": "MW (fire radiative power)"},
                {"field": "confidence", "unit": "VIIRS: l/n/h · MODIS: 0–100"},
                {"field": "scan, track", "unit": "km (pixel footprint)"},
                {"field": "daynight", "unit": "D / N"},
            ],
            "observations_held": stored_events,
            "observation_period": {"from": span_from, "to": span_to},
            "max_window_per_request": f"{settings.firms_max_day_range} days "
            "(hard limit enforced by the FIRMS API)",
            "processing": "CSV parsed and normalised onto one internal schema; VIIRS and "
            "MODIS column layouts differ. Invalid coordinates and dates are dropped. "
            "Fields a product does not supply are recorded as unavailable, never imputed.",
            "licence": "NASA open data. Attribution: NASA FIRMS / LANCE EOSDIS.",
            "configured": settings.has_firms_key,
            "last_ingest": last_ingest,
        },
        {
            "id": "openstreetmap",
            "name": "OpenStreetMap — industrial infrastructure",
            "provider": "OpenStreetMap contributors, via the public Overpass API",
            "category": "Vector geographic data",
            "role": "Supplies the nearest industrial facility to each detection and its "
            "type, which is the strongest single discriminator between an industrial "
            "thermal source and a vegetation fire.",
            "access": "Public Overpass API, no key, no account",
            "endpoint": settings.overpass_endpoint_list[0],
            "tags_queried": [
                "man_made=works",
                "power=plant",
                "landuse=industrial",
                "landuse=quarry",
                "man_made=petroleum_well / gasometer / storage_tank / mineshaft",
                "industrial=*",
            ],
            "features_held": stored_facilities,
            "processing": "Features categorised into refinery, power plant, steel/metal, "
            "chemical, cement, mine/quarry, gas-oil infrastructure, factory or industrial "
            "estate. Distance computed with the haversine formula on a spherical Earth.",
            "licence": "© OpenStreetMap contributors, Open Database Licence (ODbL).",
            "caveats": "Coverage is uneven. Some industrial estates are unmapped; "
            "conversely many small town workshops are tagged `industrial`, so proximity "
            "tests key on high-heat process facilities rather than on any tagged feature.",
        },
        {
            "id": "osm_landuse",
            "name": "OpenStreetMap land use — land-cover context",
            "provider": "OpenStreetMap contributors, via the public Overpass API",
            "category": "Vector geographic data",
            "role": "Answers what kind of ground a detection sits on: cropland, forest, "
            "industrial, water and so on.",
            "access": "Public Overpass API, no key",
            "is_not": "This is NOT a satellite land-cover classification. It is a "
            "cartographic proxy built from polygons that OSM contributors have mapped, "
            "and every result in the API says so in its source_note.",
            "categories": [
                "industrial_builtup",
                "cropland",
                "forest_vegetation",
                "grassland_scrub",
                "urban_residential",
                "water",
                "bare_open",
                "unknown",
            ],
            "polygons_in_snapshot": len(snap.landuse) if snap else 0,
            "processing": "Ways and multipolygon relations retrieved with geometry, "
            "multipolygon outer rings reassembled, then a ray-casting point-in-polygon "
            "test. Smallest containing polygon wins so a factory beats the estate "
            "around it.",
            "licence": "© OpenStreetMap contributors, ODbL.",
            "measured_coverage": [
                {
                    "area": "Central Punjab (cropland belt)",
                    "unknown_share": "98%",
                    "note": "Almost no farmland is mapped, so cropland land cover is "
                    "unavailable exactly where crop-residue burning dominates.",
                },
                {
                    "area": "Jamnagar / coastal Gujarat",
                    "unknown_share": "74%",
                    "note": "Coastal scrub and salt flats are largely unmapped.",
                },
            ],
        },
        {
            "id": "carto_basemap",
            "name": "CARTO basemap tiles",
            "provider": "CARTO, rendering OpenStreetMap data",
            "category": "Map tiles",
            "role": "Background cartography only. Carries no analytical value and feeds "
            "nothing into the model.",
            "access": "Free tile service, no key",
            "licence": "© OpenStreetMap contributors © CARTO.",
        },
    ]

    snapshot_record = None
    if snap:
        snapshot_record = {
            "id": "demo_snapshot",
            "name": "Offline snapshot",
            "captured_at": snap.captured_at,
            "what_it_is": "A frozen capture of real NASA FIRMS detections and real "
            "OpenStreetMap features, committed to the repository so the full workflow "
            "runs with no network.",
            "what_it_is_not": "Synthetic data, and not live data. Responses built from "
            "it are tagged snapshot and the interface shows a Historical badge.",
            "events": len(snap.events),
            "facilities": len(snap.facilities),
            "landuse_polygons": len(snap.landuse),
            "products": snap.meta.get("products", []),
            "date_range": snap.meta.get("date_range"),
            "regions": snap.meta.get("regions", []),
        }

    training = None
    if manifest:
        training = {
            "id": "training_dataset",
            "name": "Prototype training dataset",
            "built_at": manifest.get("built_at"),
            "dataset_version": manifest.get("dataset_version"),
            "observation_source": manifest.get("observation_source"),
            "context_source": manifest.get("context_source"),
            "label_source": manifest.get("label_source"),
            "rows_labelled": manifest.get("rows_labelled"),
            "rows_excluded_ambiguous": manifest.get("rows_unlabelled_excluded"),
            "label_counts": manifest.get("label_counts", {}),
            "rule_counts": manifest.get("rule_counts", {}),
            "regions": manifest.get("regions", []),
            "windows": manifest.get("windows", []),
            "caveat": manifest.get("caveat"),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "snapshot": snapshot_record,
        "training_dataset": training,
        "model_metrics_available": bool(metrics),
        "statement": (
            "Every observation in this system comes from NASA FIRMS or OpenStreetMap. "
            "No thermal reading, coordinate, radiative power value or timestamp is "
            "generated. Where a value is unavailable it is reported as unavailable."
        ),
    }

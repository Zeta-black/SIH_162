"""GIS export: GeoJSON per layer and a GeoPackage of all layers.

PS-162 R4 asks for GIS-based storage and visualisation. Visualisation is the
map; this module is the "and give it to me in my own tools" half, which is what
a state pollution control board or a disaster-management cell would actually
need — they live in QGIS and ArcGIS, not in someone else's web page.

GeoPackage is written by hand rather than with GDAL/fiona.

That sounds like the wrong call, so the reasoning: GeoPackage *is* SQLite with
two metadata tables and a documented binary header (OGC 12-128r15). Python ships
sqlite3. Adding GDAL to make one file would add a ~100 MB wheel chain to a
project whose whole promise is `npm run demo` on a laptop with no internet, and
GDAL wheels on Windows are the single most common "it does not install" failure
in Python GIS. So the file is written directly and then **read back and
validated** by the test suite, which is the part that actually matters.
"""
from __future__ import annotations

import logging
import sqlite3
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("firetrace.gis")

WGS84 = 4326

# A GeoPackage geometry blob: "GP", version, flags, srs_id, envelope, then WKB.
_GP_MAGIC = b"GP"


def _wkb_point(lon: float, lat: float) -> bytes:
    """Little-endian WKB for a 2D point."""
    return struct.pack("<BIdd", 1, 1, lon, lat)


def _gpkg_point(lon: float, lat: float) -> bytes:
    """GeoPackage binary geometry for a point, with no envelope.

    flags bit layout (OGC 12-128r15 section 2.1.3): bit0 little-endian,
    bits1-3 envelope type (0 = none). 0b00000001 therefore means
    little-endian, no envelope — correct for a point, whose envelope is itself.
    """
    header = _GP_MAGIC + struct.pack("<BB", 0, 0b00000001) + struct.pack("<i", WGS84)
    return header + _wkb_point(lon, lat)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
def _feature(lon: float, lat: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": properties,
    }


def detections_geojson(sites: list[dict]) -> dict:
    """Every grouped site, with the fields an analyst would filter on."""
    return {
        "type": "FeatureCollection",
        "name": "firetrace_detections",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            _feature(
                s["lon"],
                s["lat"],
                {
                    "site_id": s["id"],
                    "title": s["title"],
                    "status": s["status"],
                    "status_label": s["status_label"],
                    "predicted_class": s["predicted_class"],
                    "model_score": s["model_score"],
                    "abstained": s["abstained"],
                    "operational_priority": s["operational_priority"],
                    "priority_score": s["priority_score"],
                    "abnormality_score": s.get("abnormality_score"),
                    "abnormality_status": s.get("abnormality_status"),
                    "persistent": s["persistent"],
                    "distinct_days": s["distinct_days"],
                    "detection_count": s["detection_count"],
                    "distinct_passes": s["distinct_passes"],
                    "frp_max_mw": s["frp_max_mw"],
                    "frp_total_mw": s["frp_total_mw"],
                    "brightness_max_k": s["brightness_max_k"],
                    "nearest_facility": s.get("nearest_facility_name"),
                    "nearest_facility_km": s.get("nearest_facility_km"),
                    "land_cover": s.get("land_cover"),
                    "observed_at": s["observed_at"],
                    "verdict": s["verdict"],
                },
            )
            for s in sites
        ],
    }


def persistent_geojson(sites: list[dict]) -> dict:
    """Only the persistent thermal sources — PS-162 R2's first-class concept."""
    persistent = [s for s in sites if s.get("persistent")]
    return {
        "type": "FeatureCollection",
        "name": "firetrace_persistent_sources",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            _feature(
                s["lon"],
                s["lat"],
                {
                    "site_id": s["id"],
                    "title": s["title"],
                    "days_active": s["distinct_days"],
                    "status": s["status"],
                    "abnormality_score": s.get("abnormality_score"),
                    "abnormality_status": s.get("abnormality_status"),
                    "baseline_min_mw": (s.get("baseline_range") or {}).get("min"),
                    "baseline_max_mw": (s.get("baseline_range") or {}).get("max"),
                    "frp_max_mw": s["frp_max_mw"],
                    "nearest_facility": s.get("nearest_facility_name"),
                    "observed_at": s["observed_at"],
                },
            )
            for s in persistent
        ],
    }


def facilities_geojson(facilities: list) -> dict:
    """Mapped industrial features, straight from OpenStreetMap."""
    return {
        "type": "FeatureCollection",
        "name": "firetrace_facilities",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            _feature(
                f.longitude,
                f.latitude,
                {
                    "facility_id": f.facility_id,
                    "name": f.name,
                    "category": f.category,
                    "category_label": f.category_label,
                    "osm_type": f.osm_type,
                    "osm_id": f.osm_id,
                },
            )
            for f in facilities
        ],
    }


def notifications_geojson(items: list[dict]) -> dict:
    """Alerts that carry a position, so a queue can be mapped in QGIS."""
    placed = [i for i in items if (i.get("meta") or {}).get("lat") is not None]
    return {
        "type": "FeatureCollection",
        "name": "firetrace_notifications",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            _feature(
                i["meta"]["lon"],
                i["meta"]["lat"],
                {
                    "notification_id": i["id"],
                    "reason_code": i["reason_code"],
                    "severity": i["severity"],
                    "title": i["title"],
                    "state": i["state"],
                    "site_id": i.get("site_id"),
                    "created_at": i["created_at"],
                    "policy_version": i.get("policy_version"),
                    "is_test": i.get("is_test"),
                },
            )
            for i in placed
        ],
    }


LAYERS = ("detections", "persistent_sources", "facilities", "notifications")


# ---------------------------------------------------------------------------
# GeoPackage
# ---------------------------------------------------------------------------
_SQL_TYPES = {
    str: "TEXT",
    int: "INTEGER",
    float: "REAL",
    bool: "INTEGER",
    type(None): "TEXT",
}


def _column_types(features: list[dict]) -> dict[str, str]:
    """Infer a column type per property from the values actually present."""
    types: dict[str, str] = {}
    for feature in features:
        for key, value in feature["properties"].items():
            sql = _SQL_TYPES.get(type(value), "TEXT")
            current = types.get(key)
            if current is None or current == "TEXT":
                types[key] = sql if current is None else current
            # A column that is sometimes int and sometimes float must be REAL.
            if current == "INTEGER" and sql == "REAL":
                types[key] = "REAL"
    return types or {}


def write_geopackage(path: Path, collections: dict[str, dict]) -> Path:
    """Write the layers to a real GeoPackage at `path`.

    Creates the two required metadata tables (gpkg_spatial_ref_sys,
    gpkg_contents), plus gpkg_geometry_columns, then one table per layer.
    """
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        # The GeoPackage application id, so the file identifies itself.
        conn.execute("PRAGMA application_id = 1196444487")  # 'GPKG'
        conn.execute("PRAGMA user_version = 10400")

        conn.executescript(
            """
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE gpkg_contents (
                table_name TEXT PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT UNIQUE,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL,
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
                srs_id INTEGER
            );
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                geometry_type_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL,
                z TINYINT NOT NULL,
                m TINYINT NOT NULL,
                CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name)
            );
            """
        )

        conn.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
            [
                (
                    "WGS 84 geodetic",
                    WGS84,
                    "EPSG",
                    WGS84,
                    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]',
                    "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid",
                ),
                ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian"),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic"),
            ],
        )

        now = datetime.now(timezone.utc).isoformat()

        for layer_name, collection in collections.items():
            features = collection.get("features", [])
            columns = _column_types(features)

            column_sql = ", ".join(f'"{name}" {sql}' for name, sql in columns.items())
            conn.execute(
                f'CREATE TABLE "{layer_name}" ('
                f"fid INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"geom BLOB"
                f"{', ' + column_sql if column_sql else ''})"
            )

            if features:
                names = list(columns)
                placeholders = ", ".join("?" for _ in range(len(names) + 1))
                quoted = ", ".join(f'"{n}"' for n in names)
                sql = (
                    f'INSERT INTO "{layer_name}" (geom{", " + quoted if quoted else ""}) '
                    f"VALUES ({placeholders})"
                )
                rows = []
                for feature in features:
                    lon, lat = feature["geometry"]["coordinates"]
                    properties = feature["properties"]
                    values = [
                        # SQLite has no bool; store 0/1 and keep lists as text.
                        int(properties[n])
                        if isinstance(properties.get(n), bool)
                        else properties.get(n)
                        for n in names
                    ]
                    rows.append([_gpkg_point(lon, lat), *values])
                conn.executemany(sql, rows)

            lons = [f["geometry"]["coordinates"][0] for f in features]
            lats = [f["geometry"]["coordinates"][1] for f in features]
            conn.execute(
                "INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    layer_name,
                    "features",
                    layer_name,
                    collection.get("name", layer_name),
                    now,
                    min(lons) if lons else None,
                    min(lats) if lats else None,
                    max(lons) if lons else None,
                    max(lats) if lats else None,
                    WGS84,
                ),
            )
            conn.execute(
                "INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
                (layer_name, "geom", "POINT", WGS84, 0, 0),
            )

        conn.commit()
    finally:
        conn.close()

    log.info("[GIS] wrote GeoPackage %s (%d layers)", path.name, len(collections))
    return path


def build_geopackage(collections: dict[str, dict]) -> Path:
    """Write to a temporary file and return its path, for streaming."""
    handle = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
    handle.close()
    return write_geopackage(Path(handle.name), collections)


def read_back(path: Path) -> dict:
    """Open a written GeoPackage and report what is in it.

    Used by the test suite and by the smoke gate: writing a file proves nothing,
    reading it back and finding the right features is the actual check.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        application_id = conn.execute("PRAGMA application_id").fetchone()[0]
        contents = conn.execute(
            "SELECT table_name, data_type, srs_id, min_x, min_y, max_x, max_y FROM gpkg_contents"
        ).fetchall()
        layers = {}
        for row in contents:
            count = conn.execute(f'SELECT COUNT(*) FROM "{row["table_name"]}"').fetchone()[0]
            sample = conn.execute(
                f'SELECT geom FROM "{row["table_name"]}" LIMIT 1'
            ).fetchone()
            geom_ok = bool(sample and sample["geom"] and sample["geom"][:2] == _GP_MAGIC)
            layers[row["table_name"]] = {
                "features": int(count),
                "srs_id": row["srs_id"],
                "geometry_header_valid": geom_ok,
                "bbox": [row["min_x"], row["min_y"], row["max_x"], row["max_y"]],
            }
        geometry_columns = conn.execute(
            "SELECT table_name, geometry_type_name, srs_id FROM gpkg_geometry_columns"
        ).fetchall()
    finally:
        conn.close()

    return {
        "application_id": application_id,
        "is_geopackage": application_id == 1196444487,
        "layers": layers,
        "geometry_columns": [dict(r) for r in geometry_columns],
    }

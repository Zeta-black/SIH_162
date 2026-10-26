"""GIS export, validated by reading the files back.

Writing a file proves nothing. A GeoPackage that opens in QGIS has a specific
application id, two required metadata tables, and geometry blobs with the "GP"
header — so every test here reads the artefact and checks those, rather than
asserting that bytes were produced.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services import gis


def site(**overrides) -> dict:
    base = {
        "id": "FE-2026-G1",
        "lat": 21.1,
        "lon": 72.64,
        "title": "Test Works",
        "status": "needs_attention",
        "status_label": "Needs attention",
        "verdict": "Heat on the site.",
        "predicted_class": "INDUSTRIAL_FIRE",
        "model_score": 0.91,
        "abstained": False,
        "operational_priority": "HIGH",
        "priority_score": 0.78,
        "abnormality_score": None,
        "abnormality_status": "insufficient_history",
        "persistent": False,
        "distinct_days": 0,
        "detection_count": 3,
        "distinct_passes": 2,
        "frp_max_mw": 12.5,
        "frp_total_mw": 30.0,
        "brightness_max_k": 341.2,
        "nearest_facility_name": "Test Works",
        "nearest_facility_km": 0.25,
        "land_cover": "Industrial / built-up",
        "observed_at": "2026-10-26T07:15:00+00:00",
        "baseline_range": None,
    }
    base.update(overrides)
    return base


class FakeFacility:
    facility_id = "W123"
    name = "Test Refinery"
    category = "refinery"
    category_label = "Oil / petrochemical refinery"
    osm_type = "way"
    osm_id = 123
    latitude = 21.2
    longitude = 72.7


# ------------------------------------------------------------- GeoJSON
class TestGeoJson:
    def test_detections_layer_is_valid_geojson(self):
        fc = gis.detections_geojson([site()])
        assert fc["type"] == "FeatureCollection"
        assert fc["features"][0]["geometry"]["type"] == "Point"
        lon, lat = fc["features"][0]["geometry"]["coordinates"]
        assert (lon, lat) == (72.64, 21.1), "GeoJSON is lon,lat — not lat,lon"
        # Round-trips through a JSON encoder without custom handling.
        assert json.loads(json.dumps(fc))

    def test_crs_is_declared_as_wgs84(self):
        fc = gis.detections_geojson([site()])
        assert "CRS84" in fc["crs"]["properties"]["name"]

    def test_persistent_layer_holds_only_persistent_sources(self):
        sites = [
            site(id="a", persistent=True, distinct_days=8),
            site(id="b", persistent=False),
        ]
        fc = gis.persistent_geojson(sites)
        assert len(fc["features"]) == 1
        assert fc["features"][0]["properties"]["site_id"] == "a"
        assert fc["features"][0]["properties"]["days_active"] == 8

    def test_abnormality_status_travels_with_the_export(self):
        """An export that dropped the status would let someone read a null score
        as zero, which is the Pass 1 defect leaking into a file."""
        fc = gis.persistent_geojson([site(persistent=True, abnormality_status="insufficient_history")])
        assert fc["features"][0]["properties"]["abnormality_status"] == "insufficient_history"
        assert fc["features"][0]["properties"]["abnormality_score"] is None

    def test_facilities_layer(self):
        fc = gis.facilities_geojson([FakeFacility()])
        assert fc["features"][0]["properties"]["name"] == "Test Refinery"

    def test_notifications_without_a_position_are_skipped(self):
        items = [
            {"id": "n1", "reason_code": "X", "severity": "high", "title": "t", "state": "created",
             "created_at": "2026-10-26T09:00:00+00:00", "meta": {"lat": 21.0, "lon": 72.0}},
            {"id": "n2", "reason_code": "SYSTEM_FEED_DELAYED", "severity": "low", "title": "t",
             "state": "created", "created_at": "2026-10-26T09:00:00+00:00", "meta": {}},
        ]
        fc = gis.notifications_geojson(items)
        assert len(fc["features"]) == 1
        assert fc["features"][0]["properties"]["notification_id"] == "n1"

    def test_empty_input_is_still_a_valid_collection(self):
        fc = gis.detections_geojson([])
        assert fc["type"] == "FeatureCollection"
        assert fc["features"] == []


# ---------------------------------------------------------- GeoPackage
@pytest.fixture
def written(tmp_path) -> Path:
    collections = {
        "detections": gis.detections_geojson([site(), site(id="FE-2026-G2", lon=73.0, lat=22.0)]),
        "persistent_sources": gis.persistent_geojson(
            [site(id="FE-2026-G3", persistent=True, distinct_days=9, lon=70.1, lat=22.4)]
        ),
        "facilities": gis.facilities_geojson([FakeFacility()]),
        "notifications": gis.notifications_geojson([]),
    }
    return gis.write_geopackage(tmp_path / "out.gpkg", collections)


class TestGeoPackage:
    def test_the_file_identifies_itself_as_a_geopackage(self, written):
        report = gis.read_back(written)
        assert report["is_geopackage"] is True
        assert report["application_id"] == 1196444487  # 'GPKG'

    def test_every_layer_is_registered_in_gpkg_contents(self, written):
        report = gis.read_back(written)
        assert set(report["layers"]) == {
            "detections",
            "persistent_sources",
            "facilities",
            "notifications",
        }

    def test_feature_counts_survive_the_round_trip(self, written):
        report = gis.read_back(written)
        assert report["layers"]["detections"]["features"] == 2
        assert report["layers"]["persistent_sources"]["features"] == 1
        assert report["layers"]["facilities"]["features"] == 1
        assert report["layers"]["notifications"]["features"] == 0

    def test_geometry_blobs_carry_the_gpkg_header(self, written):
        report = gis.read_back(written)
        assert report["layers"]["detections"]["geometry_header_valid"] is True

    def test_everything_is_wgs84(self, written):
        report = gis.read_back(written)
        for layer in report["layers"].values():
            assert layer["srs_id"] == 4326
        for column in report["geometry_columns"]:
            assert column["srs_id"] == 4326
            assert column["geometry_type_name"] == "POINT"

    def test_the_bounding_box_matches_the_data(self, written):
        report = gis.read_back(written)
        min_x, min_y, max_x, max_y = report["layers"]["detections"]["bbox"]
        assert min_x == pytest.approx(72.64)
        assert max_x == pytest.approx(73.0)
        assert min_y == pytest.approx(21.1)
        assert max_y == pytest.approx(22.0)

    def test_attributes_are_queryable_with_plain_sql(self, written):
        """The point of the format: an analyst can filter it like a table."""
        conn = sqlite3.connect(written)
        try:
            rows = conn.execute(
                "SELECT site_id, status, frp_max_mw FROM detections "
                "WHERE status = 'needs_attention' ORDER BY site_id"
            ).fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == ["FE-2026-G1", "FE-2026-G2"]
        assert rows[0][2] == pytest.approx(12.5)

    def test_required_metadata_tables_exist(self, written):
        conn = sqlite3.connect(written)
        try:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        assert {"gpkg_spatial_ref_sys", "gpkg_contents", "gpkg_geometry_columns"} <= names

    def test_rewriting_over_an_existing_file_works(self, tmp_path):
        path = tmp_path / "twice.gpkg"
        gis.write_geopackage(path, {"detections": gis.detections_geojson([site()])})
        gis.write_geopackage(path, {"detections": gis.detections_geojson([site(), site(id="b")])})
        assert gis.read_back(path)["layers"]["detections"]["features"] == 2

    def test_booleans_are_stored_as_integers(self, written):
        """SQLite has no boolean; storing a Python bool unconverted would make
        the column unreadable to some GIS clients."""
        conn = sqlite3.connect(written)
        try:
            value = conn.execute("SELECT persistent FROM detections LIMIT 1").fetchone()[0]
        finally:
            conn.close()
        assert value in (0, 1)


# ------------------------------------------------------------------ API
class TestExportApi:
    def test_each_layer_downloads_as_geojson(self, client):
        for layer in gis.LAYERS:
            response = client.get(
                f"/api/export/geojson/{layer}", params={"mode": "demo", "days": 1}
            )
            assert response.status_code == 200, layer
            assert response.headers["content-type"].startswith("application/geo+json")
            body = response.json()
            assert body["type"] == "FeatureCollection"

    def test_an_unknown_layer_is_404_and_lists_the_real_ones(self, client):
        response = client.get("/api/export/geojson/nope", params={"mode": "demo"})
        assert response.status_code == 404
        assert "detections" in response.json()["detail"]

    def test_the_geopackage_downloads_and_opens(self, client, tmp_path):
        response = client.get("/api/export/gpkg", params={"mode": "demo", "days": 1})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/geopackage+sqlite3"
        assert ".gpkg" in response.headers["content-disposition"]

        path = tmp_path / "downloaded.gpkg"
        path.write_bytes(response.content)
        report = gis.read_back(path)
        assert report["is_geopackage"] is True
        assert set(report["layers"]) == set(gis.LAYERS)


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.main import app
    from app.services import livecache, pipeline
    from app.services.firms import FirmsError
    from fastapi.testclient import TestClient

    monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 60)
    monkeypatch.setattr(pipeline, "MAX_EXPLAINED_EVENTS", 6)
    monkeypatch.setattr(
        "app.services.firms.FirmsClient.fetch_area",
        lambda *a, **k: (_ for _ in ()).throw(FirmsError("offline", kind="unavailable")),
    )
    monkeypatch.setattr("app.services.osm.fetch_facilities", lambda *a, **k: ([], "unavailable"))
    monkeypatch.setattr("app.services.osm.fetch_landuse", lambda *a, **k: ([], "unavailable"))

    with TestClient(app) as c:
        yield c

    pipeline.clear_cache()

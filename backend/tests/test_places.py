"""The place gazetteer, and that it has not drifted from the dataset regions.

`app/places.py` duplicates the bounding boxes in `ml/regions.py` on purpose — the
API layer does not import the training package. Duplication is only safe if a
drift fails loudly, which is what the first test here is for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import places

# ml/ is a sibling package of app/, not an import of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestNoDriftFromTheDataset:
    def test_every_area_matches_a_dataset_region(self):
        from ml.regions import REGIONS_BY_ID

        for area in places.AREAS:
            assert area.region_id in REGIONS_BY_ID, (
                f"{area.region_id} is not a dataset region — places.py has drifted"
            )

    def test_bounding_boxes_are_identical(self):
        from ml.regions import REGIONS_BY_ID

        for area in places.AREAS:
            assert area.bbox == REGIONS_BY_ID[area.region_id].bbox, (
                f"{area.region_id} bbox differs from ml/regions.py"
            )

    def test_every_dataset_region_has_a_place_name(self):
        """A region in the dataset with no gazetteer entry means detections there
        fall back to coordinates for no reason."""
        from ml.regions import REGIONS

        covered = {a.region_id for a in places.AREAS}
        missing = [r.id for r in REGIONS if r.id not in covered]
        assert missing == [], f"regions with no place name: {missing}"


class TestPlaceLookup:
    @pytest.mark.parametrize(
        "lat,lon,expected",
        [
            (21.105, 72.642, "Hazira, Gujarat"),
            (21.165, 72.671, "Hazira, Gujarat"),
            (22.40, 70.10, "Jamnagar, Gujarat"),
            (30.74, 75.82, "Central Punjab, Punjab"),
            (21.51, 86.70, "Similipal, Odisha"),
        ],
    )
    def test_known_points(self, lat, lon, expected):
        assert places.place_for(lat, lon) == expected

    def test_a_point_outside_every_area_gets_no_name(self):
        """Never guess. Naming a detection after an area it is not in would be a
        fabricated location."""
        assert places.place_for(12.97, 77.59) is None  # Bengaluru city centre
        assert places.place_for(0.0, 0.0) is None

    def test_every_label_names_a_state(self):
        for area in places.AREAS:
            assert ", " in area.label
            assert area.state and area.place

    def test_area_lookup_returns_the_area_itself(self):
        area = places.area_for(21.105, 72.642)
        assert area is not None and area.region_id == "hazira"


class TestTitlesOverTheApi:
    def test_no_site_title_is_bare_coordinates_inside_a_known_area(self, client):
        """The whole point: a queue row should read like a place, not a fix."""
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        offenders = []
        for site in body["sites"]:
            place = places.place_for(site["lat"], site["lon"])
            if place and "°" in site["title"]:
                offenders.append(site["title"])
        assert offenders == [], offenders[:5]

    def test_unnamed_features_are_qualified_by_place(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        generic = [s for s in body["sites"] if s["title"].startswith("Gas / oil infrastructure")]
        assert generic, "expected some unnamed gas/oil features in the archive"
        for site in generic:
            assert " · " in site["title"]

    def test_named_facilities_keep_their_own_name(self, client):
        body = client.get("/api/map", params={"mode": "demo", "days": 1}).json()
        named = [s for s in body["sites"] if "ArcelorMittal" in s["title"]]
        assert named
        for site in named:
            # A real name stands alone; it is not qualified with a place.
            assert site["title"] == "ArcelorMittal Nippon Steel India"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.main import app
    from app.services import livecache, pipeline
    from app.services.firms import FirmsError
    from fastapi.testclient import TestClient

    monkeypatch.setattr(livecache, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(livecache, "CACHE_DIR", tmp_path)
    pipeline.clear_cache()
    monkeypatch.setattr(pipeline, "MAX_ANALYSED_EVENTS", 80)
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

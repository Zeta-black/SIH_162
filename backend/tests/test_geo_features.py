"""Geospatial maths, feature engineering and recurrence.

The distance tests use published reference distances, because a distance
function that is subtly wrong would quietly corrupt the single most important
feature in the model.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.services.features import FEATURE_NAMES, build_feature_row, row_to_vector
from app.services.geo import (
    GridPoint,
    SpatialGrid,
    bbox_around,
    haversine_km,
    parse_bbox,
    snap_bbox_to_grid,
    valid_coordinate,
)
from app.services.osm import _stitch_rings, point_in_ring
from app.services.recurrence import HistoryIndex


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_km(22.3, 69.8, 22.3, 69.8) == pytest.approx(0.0, abs=1e-9)

    def test_known_distance_delhi_to_mumbai(self):
        # Published great-circle distance is ~1150 km.
        d = haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
        assert d == pytest.approx(1150, rel=0.02)

    def test_one_degree_of_latitude(self):
        # A degree of latitude is ~111 km everywhere.
        assert haversine_km(22.0, 69.0, 23.0, 69.0) == pytest.approx(111.2, rel=0.01)

    def test_longitude_degree_shrinks_with_latitude(self):
        at_equator = haversine_km(0.0, 69.0, 0.0, 70.0)
        at_60 = haversine_km(60.0, 69.0, 60.0, 70.0)
        # cos(60°) = 0.5, so the same degree spans about half the distance.
        assert at_60 == pytest.approx(at_equator * 0.5, rel=0.02)

    def test_is_not_naive_degree_subtraction(self):
        """Guards against the classic bug of treating degrees as kilometres."""
        naive = math.sqrt((23.0 - 22.0) ** 2 + (70.0 - 69.0) ** 2)
        real = haversine_km(22.0, 69.0, 23.0, 70.0)
        assert real > 100  # kilometres, not ~1.41
        assert abs(real - naive) > 100

    def test_symmetric(self):
        a = haversine_km(22.3, 69.8, 28.6, 77.2)
        b = haversine_km(28.6, 77.2, 22.3, 69.8)
        assert a == pytest.approx(b)


class TestValidCoordinate:
    @pytest.mark.parametrize("lat,lon", [(22.3, 69.8), (-89.9, 179.9), (0.0, 45.0)])
    def test_accepts_valid(self, lat, lon):
        assert valid_coordinate(lat, lon)

    @pytest.mark.parametrize(
        "lat,lon",
        [
            (None, 69.8),
            (22.3, None),
            (91.0, 69.8),
            (-91.0, 69.8),
            (22.3, 181.0),
            (22.3, -181.0),
            (float("nan"), 69.8),
            (float("inf"), 69.8),
            (0.0, 0.0),  # null island: a placeholder, not a real detection
        ],
    )
    def test_rejects_invalid(self, lat, lon):
        assert not valid_coordinate(lat, lon)


class TestBbox:
    def test_parses(self):
        assert parse_bbox("68.0,6.5,97.5,36.0") == (68.0, 6.5, 97.5, 36.0)

    @pytest.mark.parametrize(
        "value",
        ["68,6.5,97.5", "a,b,c,d", "97.5,6.5,68.0,36.0", "68.0,36.0,97.5,6.5", "200,6.5,297,36"],
    )
    def test_rejects_bad_input(self, value):
        with pytest.raises(ValueError):
            parse_bbox(value)

    def test_bbox_around_contains_centre(self):
        w, s, e, n = bbox_around(22.3, 69.8, 10.0)
        assert w < 69.8 < e
        assert s < 22.3 < n

    def test_bbox_around_is_wide_enough(self):
        w, s, e, n = bbox_around(22.3, 69.8, 10.0)
        assert haversine_km(22.3, 69.8, n, 69.8) >= 9.9

    def test_snapping_is_outward(self):
        snapped = snap_bbox_to_grid((69.15, 22.05, 70.35, 22.75), 0.5)
        assert snapped[0] <= 69.15 and snapped[1] <= 22.05
        assert snapped[2] >= 70.35 and snapped[3] >= 22.75


class TestSpatialGrid:
    def test_finds_nearest(self, facility):
        grid = SpatialGrid([GridPoint(facility.latitude, facility.longitude, facility)])
        point, distance = grid.nearest(22.3, 69.8, 12.0)
        assert point is not None
        assert distance == pytest.approx(0.07, abs=0.05)

    def test_respects_radius(self, facility):
        grid = SpatialGrid([GridPoint(facility.latitude, facility.longitude, facility)])
        point, distance = grid.nearest(30.0, 76.0, 12.0)
        assert point is None and distance is None

    def test_within_returns_sorted(self):
        points = [
            GridPoint(22.30, 69.80, "a"),
            GridPoint(22.35, 69.80, "b"),
            GridPoint(22.50, 69.80, "c"),
        ]
        grid = SpatialGrid(points)
        hits = grid.within(22.30, 69.80, 30.0)
        distances = [d for _, d in hits]
        assert distances == sorted(distances)

    def test_empty_grid(self):
        grid = SpatialGrid([])
        assert len(grid) == 0
        assert grid.nearest(22.3, 69.8, 10.0) == (None, None)

    def test_skips_invalid_points(self):
        grid = SpatialGrid([GridPoint(999.0, 69.8, "bad"), GridPoint(22.3, 69.8, "good")])
        assert len(grid) == 1


class TestPointInPolygon:
    def test_inside(self, square_polygon):
        assert point_in_ring(22.05, 69.05, square_polygon.ring)

    @pytest.mark.parametrize("lat,lon", [(21.9, 69.05), (22.2, 69.05), (22.05, 68.9), (22.05, 69.2)])
    def test_outside(self, lat, lon, square_polygon):
        assert not point_in_ring(lat, lon, square_polygon.ring)

    def test_concave_polygon(self):
        # An L shape; the notch must read as outside.
        ring = [
            (0.0, 0.0), (0.0, 2.0), (1.0, 2.0), (1.0, 1.0),
            (2.0, 1.0), (2.0, 0.0), (0.0, 0.0),
        ]
        assert point_in_ring(0.5, 0.5, ring)
        assert not point_in_ring(1.5, 1.5, ring)


class TestRingStitching:
    def test_already_closed_ring_passes_through(self):
        ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        assert _stitch_rings([ring]) == [ring]

    def test_two_open_segments_are_joined(self):
        a = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        b = [(1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
        rings = _stitch_rings([a, b])
        assert len(rings) == 1
        assert rings[0][0] == rings[0][-1]

    def test_reversed_segment_is_flipped(self):
        a = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        b = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]  # runs the other way
        rings = _stitch_rings([a, b])
        assert len(rings) == 1
        assert rings[0][0] == rings[0][-1]

    def test_unclosable_fragments_do_not_hang(self):
        rings = _stitch_rings([[(0.0, 0.0), (0.0, 1.0)], [(5.0, 5.0), (5.0, 6.0)]])
        assert isinstance(rings, list)


class TestRecurrence:
    def test_no_history_is_reported_not_faked(self, event):
        result = HistoryIndex([]).compute(event)
        assert result.history_available is False
        assert result.recurrence_count == 0
        assert result.is_persistent is False

    def test_counts_prior_detections_at_same_spot(self, event, history_events):
        result = HistoryIndex(history_events).compute(event)
        assert result.recurrence_count == 10
        assert result.distinct_days == 10

    def test_persistent_source_is_flagged(self, event, history_events):
        assert HistoryIndex(history_events).compute(event).is_persistent is True

    def test_ignores_detections_outside_the_radius(self, event, history_events):
        result = HistoryIndex(history_events).compute(event, radius_km=1.0)
        # The far-away event at (23.9, 70.9) is ~180 km off and must not count.
        assert result.recurrence_count == 10

    def test_no_leakage_from_the_future(self, event_factory):
        """Detections after the event must never be counted as its history."""
        target = event_factory(event_id="EVT-TARGET", acq_date=date(2026, 3, 10))
        future = [
            event_factory(event_id=f"EVT-FUT{i}", acq_date=date(2026, 3, 10) + timedelta(days=i))
            for i in range(1, 6)
        ]
        result = HistoryIndex(future).compute(target)
        assert result.recurrence_count == 0
        assert result.distinct_days == 0

    def test_same_day_codetections_counted_as_density_not_history(self, event_factory):
        target = event_factory(event_id="EVT-T", acq_time="12:00")
        same_pass = [
            event_factory(event_id=f"EVT-S{i}", lat=22.31, lon=69.81, acq_time="11:00")
            for i in range(3)
        ]
        result = HistoryIndex([target, *same_pass]).compute(target)
        assert result.recurrence_count == 0  # same day is not "prior"
        assert result.nearby_density >= 1

    def test_window_excludes_very_old_detections(self, event, event_factory):
        ancient = [
            event_factory(event_id="EVT-OLD", acq_date=date(2025, 1, 1)),
        ]
        result = HistoryIndex(ancient).compute(event, window_days=60)
        assert result.recurrence_count == 0

    def test_persistence_ratio_bounded(self, event, history_events):
        ratio = HistoryIndex(history_events).compute(event).persistence_ratio
        assert 0.0 <= ratio <= 1.0


class TestFeatures:
    def test_row_has_every_declared_feature(
        self, event, nearest_facility, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert set(FEATURE_NAMES).issubset(row.keys())

    def test_vector_length_matches_feature_names(
        self, event, nearest_facility, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert len(row_to_vector(row)) == len(FEATURE_NAMES)

    def test_one_hot_is_exclusive(self, event, nearest_facility, land_cover_industrial):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        landcover_flags = [v for k, v in row.items() if k.startswith("landcover__")]
        facility_flags = [v for k, v in row.items() if k.startswith("facility_cat__")]
        assert sum(landcover_flags) == 1.0
        assert sum(facility_flags) == 1.0

    def test_missing_frp_sets_indicator_and_nan(
        self, event_factory, nearest_facility, land_cover_industrial
    ):
        event = event_factory(frp=None)
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert row["frp_missing"] == 1.0
        assert math.isnan(row["frp_mw"])

    def test_absent_facility_uses_search_radius_not_zero(
        self, event, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, None, land_cover_industrial, rec)
        assert row["facility_found"] == 0.0
        assert row["facility_cat__none"] == 1.0
        # Distance must read "at least this far", never 0, which would mean
        # "on top of a facility".
        assert row["distance_to_facility_km"] > 1.0

    def test_brightness_delta_computed(self, event, nearest_facility, land_cover_industrial):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert row["brightness_delta_k"] == pytest.approx(336.6 - 298.3, abs=0.2)

    def test_season_encoding_is_circular(
        self, event_factory, nearest_facility, land_cover_industrial
    ):
        rec_dec = HistoryIndex([]).compute(event_factory(acq_date=date(2026, 12, 31)))
        dec = build_feature_row(
            event_factory(acq_date=date(2026, 12, 31)), nearest_facility, land_cover_industrial, rec_dec
        )
        jan = build_feature_row(
            event_factory(acq_date=date(2026, 1, 1)), nearest_facility, land_cover_industrial, rec_dec
        )
        # 31 Dec and 1 Jan must sit next to each other on the circle.
        distance = math.hypot(
            dec["season_sin"] - jan["season_sin"], dec["season_cos"] - jan["season_cos"]
        )
        assert distance < 0.05

    def test_onsite_flag_matches_distance(
        self, event, nearest_facility, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        row = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert row["facility_onsite"] == 1.0  # fixture is 0.32 km away

    def test_identical_inputs_give_identical_rows(
        self, event, nearest_facility, land_cover_industrial
    ):
        rec = HistoryIndex([]).compute(event)
        a = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        b = build_feature_row(event, nearest_facility, land_cover_industrial, rec)
        assert a == b

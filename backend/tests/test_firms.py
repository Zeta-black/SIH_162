"""FIRMS normalization tests.

These cover the cases that actually bit during development: VIIRS and MODIS do
not share a column layout, confidence is a letter in one product and a number
in the other, and acq_time arrives without a leading zero.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services.firms import (
    FirmsClient,
    FirmsError,
    _normalize_time,
    make_event_id,
    normalize_confidence,
    normalize_rows,
    parse_csv,
)


class _Response:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _Client:
    def get(self, _url: str) -> _Response:
        return _Response(400, "Invalid MAP_KEY.")


class _SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url: str) -> _Response:
        self.urls.append(url)
        return self.responses.pop(0)

VIIRS_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
21.10014,72.63404,336.61,0.6,0.53,2026-09-10,748,N21,VIIRS,n,2.0NRT,298.34,36.33,D
21.10247,72.64529,342.82,0.6,0.53,2026-09-10,748,N21,VIIRS,h,2.0NRT,295.75,9.05,N
"""

MODIS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
22.38048,69.33012,310.38,1,1,2026-09-10,1047,Aqua,MODIS,32,6.1NRT,296.35,5.76,D
"""


class TestParseCsv:
    def test_parses_viirs(self):
        rows = parse_csv(VIIRS_CSV)
        assert len(rows) == 2
        assert rows[0]["bright_ti4"] == "336.61"

    def test_empty_payload_is_not_an_error(self):
        assert parse_csv("") == []
        assert parse_csv("   ") == []

    def test_html_error_page_is_rejected(self):
        with pytest.raises(FirmsError):
            parse_csv("<html><body>Service unavailable</body></html>")

    def test_missing_required_columns_rejected(self):
        with pytest.raises(FirmsError, match="missing expected columns"):
            parse_csv("latitude,longitude\n1,2\n")

    def test_invalid_key_message_is_classified(self):
        with pytest.raises(FirmsError) as exc:
            parse_csv("Invalid MAP_KEY supplied.")
        assert exc.value.kind == "not_configured"

    def test_http_400_invalid_key_is_actionable(self):
        with pytest.raises(FirmsError) as exc:
            FirmsClient(client=_Client()).fetch_area((69.8, 22.25, 69.9, 22.4), products=["VIIRS_SNPP_NRT"])
        assert exc.value.kind == "not_configured"
        assert "replace" in str(exc.value).lower()


class TestNormalizeRows:
    def test_viirs_maps_bright_ti4_and_ti5(self):
        events, skipped = normalize_rows(parse_csv(VIIRS_CSV), "VIIRS_NOAA21_NRT")
        assert skipped == 0
        assert len(events) == 2
        first = events[0]
        assert first.brightness_k == pytest.approx(336.61)
        assert first.brightness_secondary_k == pytest.approx(298.34)
        assert first.frp_mw == pytest.approx(36.33)
        assert first.unavailable_fields == []

    def test_modis_maps_brightness_and_t31(self):
        events, _ = normalize_rows(parse_csv(MODIS_CSV), "MODIS_NRT")
        assert events[0].brightness_k == pytest.approx(310.38)
        assert events[0].brightness_secondary_k == pytest.approx(296.35)

    def test_day_night_is_preserved(self):
        events, _ = normalize_rows(parse_csv(VIIRS_CSV), "VIIRS_NOAA21_NRT")
        assert events[0].day_night == "D"
        assert events[1].day_night == "N"

    def test_acq_time_without_leading_zero(self):
        events, _ = normalize_rows(parse_csv(VIIRS_CSV), "VIIRS_NOAA21_NRT")
        assert events[0].acquisition_time == "07:48"
        assert events[0].acquired_at.hour == 7
        assert events[0].acquired_at.minute == 48

    def test_acquisition_date_parsed(self):
        events, _ = normalize_rows(parse_csv(VIIRS_CSV), "VIIRS_NOAA21_NRT")
        assert events[0].acquisition_date == date(2026, 9, 10)

    @pytest.mark.parametrize(
        "lat,lon",
        [("999", "72.6"), ("21.1", "999"), ("", "72.6"), ("abc", "72.6"), ("0", "0")],
    )
    def test_invalid_coordinates_are_skipped_not_guessed(self, lat, lon):
        rows = [
            {
                "latitude": lat,
                "longitude": lon,
                "acq_date": "2026-09-10",
                "acq_time": "748",
                "frp": "5",
            }
        ]
        events, skipped = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        assert events == []
        assert skipped == 1

    def test_bad_date_is_skipped(self):
        rows = [
            {"latitude": "21.1", "longitude": "72.6", "acq_date": "not-a-date", "acq_time": "748"}
        ]
        events, skipped = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        assert events == []
        assert skipped == 1

    def test_missing_optional_fields_are_recorded_not_invented(self):
        rows = [
            {"latitude": "21.1", "longitude": "72.6", "acq_date": "2026-09-10", "acq_time": "748"}
        ]
        events, _ = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        event = events[0]
        assert event.frp_mw is None
        assert event.brightness_k is None
        assert event.day_night is None
        # The absence is reported rather than filled with a substitute value.
        assert "frp_mw" in event.unavailable_fields
        assert "brightness_k" in event.unavailable_fields
        assert "day_night" in event.unavailable_fields

    def test_header_case_and_whitespace_tolerated(self):
        rows = [
            {" Latitude ": "21.1", "LONGITUDE": "72.6", "Acq_Date": "2026-09-10", "acq_time": "748"}
        ]
        events, skipped = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        assert skipped == 0
        assert events[0].latitude == pytest.approx(21.1)


class TestConfidence:
    @pytest.mark.parametrize(
        "raw,expected",
        [("l", "low"), ("n", "nominal"), ("h", "high"), ("L", "low"), ("HIGH", "high")],
    )
    def test_viirs_letters(self, raw, expected):
        assert normalize_confidence(raw, "VIIRS")[1] == expected

    @pytest.mark.parametrize(
        "raw,expected", [("0", "low"), ("29", "low"), ("32", "nominal"), ("79", "nominal"), ("80", "high"), ("100", "high")]
    )
    def test_modis_percentages(self, raw, expected):
        assert normalize_confidence(raw, "MODIS")[1] == expected

    def test_missing_confidence(self):
        assert normalize_confidence(None, "VIIRS") == (None, None)
        assert normalize_confidence("", "VIIRS") == (None, None)


class TestTimeNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [("748", "07:48"), ("0748", "07:48"), ("1047", "10:47"), ("5", "00:05"), ("0", "00:00")],
    )
    def test_hhmm_forms(self, raw, expected):
        assert _normalize_time(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "abcd", "9999"])
    def test_unusable_times_fall_back_safely(self, raw):
        assert _normalize_time(raw) == "00:00"


class TestEventId:
    def test_is_deterministic(self):
        a = make_event_id(21.1, 72.6, "2026-09-10", "07:48", "VIIRS_NOAA21_NRT")
        b = make_event_id(21.1, 72.6, "2026-09-10", "07:48", "VIIRS_NOAA21_NRT")
        assert a == b

    def test_differs_by_product(self):
        a = make_event_id(21.1, 72.6, "2026-09-10", "07:48", "VIIRS_NOAA21_NRT")
        b = make_event_id(21.1, 72.6, "2026-09-10", "07:48", "MODIS_NRT")
        assert a != b

    def test_deduplication_works_across_a_repeated_ingest(self):
        rows = parse_csv(VIIRS_CSV)
        first, _ = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        second, _ = normalize_rows(rows, "VIIRS_NOAA21_NRT")
        assert {e.event_id for e in first} == {e.event_id for e in second}


class TestProductStrategy:
    def test_primary_success_does_not_download_secondary_products(self):
        client = _SequenceClient([_Response(200, VIIRS_CSV)])
        result = FirmsClient(client=client).fetch_area(
            (68.0, 6.5, 97.5, 36.0), products=["VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT"]
        )
        assert result.products_used == ["VIIRS_NOAA21_NRT"]
        assert len(client.urls) == 1

    def test_secondary_product_is_used_when_primary_fails(self):
        client = _SequenceClient([_Response(503, "busy"), _Response(200, VIIRS_CSV)])
        result = FirmsClient(client=client).fetch_area(
            (68.0, 6.5, 97.5, 36.0), products=["VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT"]
        )
        assert result.products_used == ["VIIRS_NOAA20_NRT"]
        assert len(result.events) == 2
        assert len(client.urls) == 2

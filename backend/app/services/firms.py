"""NASA FIRMS client and normalizer.

All NASA traffic goes through this module. Nothing else in the codebase knows
the MAP_KEY exists, and the key is scrubbed from every log line and error
message before it can escape.

Two FIRMS product families are supported, and they do NOT share a schema. The
column sets below were read off live responses rather than assumed:

    VIIRS: latitude, longitude, bright_ti4, scan, track, acq_date, acq_time,
           satellite, instrument, confidence, version, bright_ti5, frp, daynight
    MODIS: latitude, longitude, brightness,  scan, track, acq_date, acq_time,
           satellite, instrument, confidence, version, bright_t31,  frp, daynight

VIIRS reports confidence as a letter (l/n/h); MODIS reports it as 0-100. The
normalizer maps whatever is present and records anything the product did not
supply in `unavailable_fields` instead of inventing a number for it.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from app.config import settings
from app.schemas import HotspotEvent
from app.services.geo import valid_coordinate

log = logging.getLogger("firetrace.firms")

# Column name -> normalized field, per product family.
VIIRS_BRIGHTNESS = "bright_ti4"
VIIRS_SECONDARY = "bright_ti5"
MODIS_BRIGHTNESS = "brightness"
MODIS_SECONDARY = "bright_t31"

REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date", "acq_time"}


class FirmsError(Exception):
    """Raised when FIRMS cannot be used. Always carries a user-safe message."""

    def __init__(self, message: str, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind  # unavailable | not_configured | no_data


@dataclass
class FirmsFetchResult:
    events: list[HotspotEvent] = field(default_factory=list)
    products_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_invalid: int = 0
    duplicates_dropped: int = 0


def _redact(text: str) -> str:
    """Remove the MAP_KEY from anything that might be logged or returned."""
    key = settings.firms_map_key
    if key and key in text:
        text = text.replace(key, "***MAP_KEY***")
    return text


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value == "" or value.lower() in {"nan", "null", "none", "n/a"}:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


def normalize_confidence(raw: str | None, instrument: str | None) -> tuple[str | None, str | None]:
    """Map a product's confidence onto (raw_text, low|nominal|high).

    VIIRS uses letters, MODIS uses a percentage. The MODIS cut points (<30 low,
    >=80 high) follow the bands NASA uses in its own product documentation.
    """
    if raw is None:
        return None, None
    raw = raw.strip()
    if raw == "":
        return None, None

    letter = raw.lower()
    if letter in {"l", "low"}:
        return raw, "low"
    if letter in {"n", "nominal"}:
        return raw, "nominal"
    if letter in {"h", "high"}:
        return raw, "high"

    numeric = _parse_float(raw)
    if numeric is None:
        return raw, None
    if numeric < 30:
        return raw, "low"
    if numeric < 80:
        return raw, "nominal"
    return raw, "high"


def _normalize_time(raw: str | None) -> str:
    """FIRMS reports acq_time as HHMM without a leading zero (e.g. '748')."""
    if raw is None:
        return "00:00"
    digits = "".join(ch for ch in str(raw).strip() if ch.isdigit())
    if not digits:
        return "00:00"
    digits = digits.zfill(4)[:4]
    hh, mm = digits[:2], digits[2:]
    try:
        h, m = int(hh), int(mm)
    except ValueError:
        return "00:00"
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return "00:00"
    return f"{h:02d}:{m:02d}"


def make_event_id(lat: float, lon: float, acq_date: str, acq_time: str, product: str) -> str:
    """Stable ID so re-ingesting the same detection does not duplicate it."""
    seed = f"{lat:.5f}|{lon:.5f}|{acq_date}|{acq_time}|{product}"
    return "EVT-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()


def normalize_rows(
    rows: list[dict[str, str]],
    product: str,
    source_mode: str = "live",
    reference: str = "",
) -> tuple[list[HotspotEvent], int]:
    """Turn raw FIRMS CSV rows into normalized events.

    Returns (events, skipped_count). Rows with unusable coordinates or dates
    are dropped rather than guessed at.
    """
    events: list[HotspotEvent] = []
    skipped = 0
    now = datetime.now(timezone.utc)

    for row in rows:
        # Normalise header casing/whitespace once per row.
        r = {str(k).strip().lower(): (v if v is None else str(v).strip()) for k, v in row.items()}

        lat = _parse_float(r.get("latitude"))
        lon = _parse_float(r.get("longitude"))
        if not valid_coordinate(lat, lon):
            skipped += 1
            continue

        acq_date_raw = r.get("acq_date") or ""
        try:
            acq_date = date.fromisoformat(acq_date_raw[:10])
        except ValueError:
            skipped += 1
            continue

        acq_time = _normalize_time(r.get("acq_time"))
        hh, mm = (int(x) for x in acq_time.split(":"))
        acquired_at = datetime(
            acq_date.year, acq_date.month, acq_date.day, hh, mm, tzinfo=timezone.utc
        )

        unavailable: list[str] = []

        # Brightness: whichever channel this product publishes.
        brightness = _parse_float(r.get(VIIRS_BRIGHTNESS))
        secondary = _parse_float(r.get(VIIRS_SECONDARY))
        if brightness is None:
            brightness = _parse_float(r.get(MODIS_BRIGHTNESS))
            secondary = _parse_float(r.get(MODIS_SECONDARY))
        if brightness is None:
            unavailable.append("brightness_k")
        if secondary is None:
            unavailable.append("brightness_secondary_k")

        frp = _parse_float(r.get("frp"))
        if frp is None:
            unavailable.append("frp_mw")

        conf_raw, conf_level = normalize_confidence(r.get("confidence"), r.get("instrument"))
        if conf_raw is None:
            unavailable.append("firms_confidence")

        daynight = (r.get("daynight") or "").upper()[:1]
        if daynight not in {"D", "N"}:
            daynight = None
            unavailable.append("day_night")

        events.append(
            HotspotEvent(
                event_id=make_event_id(lat, lon, acq_date.isoformat(), acq_time, product),
                latitude=lat,
                longitude=lon,
                acquisition_date=acq_date,
                acquisition_time=acq_time,
                acquired_at=acquired_at,
                brightness_k=brightness,
                brightness_secondary_k=secondary,
                frp_mw=frp,
                firms_confidence_raw=conf_raw,
                firms_confidence_level=conf_level,
                satellite=r.get("satellite") or None,
                instrument=r.get("instrument") or None,
                day_night=daynight,
                scan=_parse_float(r.get("scan")),
                track=_parse_float(r.get("track")),
                version=r.get("version") or None,
                source_product=product,
                source_mode=source_mode,  # type: ignore[arg-type]
                raw_source_reference=reference or product,
                ingested_at=now,
                unavailable_fields=unavailable,
            )
        )

    return events, skipped


def parse_csv(text: str) -> list[dict[str, str]]:
    """Parse a FIRMS CSV payload, validating that it really is one.

    FIRMS answers some error conditions with a plain-text body and HTTP 200, so
    the header is checked rather than trusted.
    """
    text = (text or "").strip()
    if not text:
        return []
    lowered = text[:400].lower()
    if lowered.startswith("<") or "<html" in lowered:
        raise FirmsError("FIRMS returned an HTML page instead of CSV data.")
    if "invalid" in lowered and "map_key" in lowered.replace(" ", "_"):
        raise FirmsError("The configured NASA FIRMS key was rejected.", kind="not_configured")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    header = {str(h).strip().lower() for h in reader.fieldnames}
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise FirmsError(
            f"FIRMS response is missing expected columns: {', '.join(sorted(missing))}."
        )
    return [dict(row) for row in reader if row]


class FirmsClient:
    """Thin, defensive wrapper around the FIRMS area/CSV endpoint."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _get(self, url: str) -> httpx.Response:
        """GET with bounded retries on transient failures.

        Retried: read/connect timeouts, connection resets, and 5xx. Those are
        the failures a venue network produces, and a second attempt 0.6 s later
        usually succeeds.

        NOT retried: HTTP 429, a rejected MAP_KEY, and connection errors. None
        improves by asking again — retrying a rate limit actively makes it worse,
        and a connection error means there is no network, which will not change
        in 600 ms. Measured: retrying connection errors across three configured
        products turned a no-network request into a 21 s wait before the offline
        fallback engaged. These fall straight through so the fallback is immediate.
        """
        if self._client is not None:
            return self._client.get(url)

        attempts = max(1, settings.firms_retries + 1)
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                with httpx.Client(
                    timeout=settings.firms_timeout_seconds, follow_redirects=True
                ) as c:
                    resp = c.get(url)
                if resp.status_code >= 500 and attempt < attempts - 1:
                    log.warning(
                        "[FIRMS] HTTP %s, retrying (%d/%d)",
                        resp.status_code,
                        attempt + 1,
                        attempts - 1,
                    )
                else:
                    return resp
            except httpx.ConnectError:
                # No route to NASA at all. Fail fast so the offline fallback
                # engages now rather than after a round of pointless backoff.
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
                log.warning(
                    "[FIRMS] %s, retrying (%d/%d)",
                    type(exc).__name__,
                    attempt + 1,
                    attempts - 1,
                )

            time.sleep(settings.firms_retry_backoff_seconds * (2**attempt))

        if last_exc is not None:
            raise last_exc
        # Only reachable when the final attempt was a 5xx.
        return resp

    def map_key_status(self) -> dict[str, object]:
        """Report quota usage. Never returns the key itself."""
        if not settings.has_firms_key:
            return {"configured": False, "message": "FIRMS_MAP_KEY is not set."}
        url = (
            f"{settings.firms_base_url}/mapserver/mapkey_status/"
            f"?MAP_KEY={settings.firms_map_key}"
        )
        try:
            resp = self._get(url)
            resp.raise_for_status()
            payload = resp.json()
            return {
                "configured": True,
                "transaction_limit": payload.get("transaction_limit"),
                "current_transactions": payload.get("current_transactions"),
                "transaction_interval": payload.get("transaction_interval"),
            }
        except Exception as exc:  # noqa: BLE001 - surfaced as a safe message
            return {"configured": True, "error": _redact(f"{type(exc).__name__}: {exc}")[:200]}

    def fetch_area(
        self,
        bbox: tuple[float, float, float, float],
        day_range: int = 2,
        start_date: date | None = None,
        products: list[str] | None = None,
    ) -> FirmsFetchResult:
        """Fetch hotspots for a bbox across one or more FIRMS products.

        A failure on one product does not abort the others; the caller decides
        whether the partial result is good enough or the snapshot should be
        used instead.
        """
        result = FirmsFetchResult()

        if not settings.has_firms_key:
            raise FirmsError(
                "NASA FIRMS key is not configured on the server.", kind="not_configured"
            )

        west, south, east, north = bbox
        day_range = max(1, min(int(day_range), settings.firms_max_day_range))
        products = products or settings.firms_source_list
        seen: set[str] = set()
        key_rejected = False
        network_down = False

        # NOAA-21 is the primary NRT product.  Query a secondary product only
        # when the primary could not be obtained; downloading all products on
        # each interactive request tripled latency and quota use without
        # improving the first usable map.
        for product in products:
            path = (
                f"/api/area/csv/{settings.firms_map_key}/{product}/"
                f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}/{day_range}"
            )
            if start_date is not None:
                path += f"/{start_date.isoformat()}"
            url = settings.firms_base_url + path
            reference = f"FIRMS {product} bbox={west:.2f},{south:.2f},{east:.2f},{north:.2f} days={day_range}"

            log.info("[FIRMS] fetching %s days=%s bbox=%s", product, day_range, bbox)
            try:
                resp = self._get(url)
                if resp.status_code == 429:
                    result.errors.append(f"{product}: rate limited by FIRMS (HTTP 429)")
                    continue
                if resp.status_code >= 400:
                    # FIRMS returns an HTTP 400 with a plain-text "Invalid
                    # MAP_KEY." body for a revoked/incorrect key. Treating it
                    # as a generic outage hides the only actionable operator
                    # remedy: replace the server-side secret.
                    body = _redact(resp.text[:500])
                    invalid_key = "invalid map_key" in body.lower() or "invalid map key" in body.lower()
                    if invalid_key:
                        key_rejected = True
                        result.errors.append(
                            f"{product}: configured NASA FIRMS key was rejected (HTTP {resp.status_code})"
                        )
                    else:
                        result.errors.append(f"{product}: FIRMS returned HTTP {resp.status_code}")
                    continue
                rows = parse_csv(resp.text)
            except FirmsError as exc:
                result.errors.append(f"{product}: {exc}")
                continue
            except httpx.TimeoutException:
                # A timeout is about the network, not about this product. Trying
                # the next one costs another full timeout to learn the same
                # thing, so stop and let the caller fall back now. Measured: the
                # product loop turned a dead network into a ~20 s wait.
                result.errors.append(f"{product}: request to FIRMS timed out")
                network_down = True
                break
            except httpx.ConnectError:
                result.errors.append(f"{product}: could not reach FIRMS (no route)")
                network_down = True
                break
            except Exception as exc:  # noqa: BLE001
                result.errors.append(_redact(f"{product}: {type(exc).__name__}"))
                continue

            events, skipped = normalize_rows(rows, product, "live", reference)
            result.skipped_invalid += skipped

            for ev in events:
                if ev.event_id in seen:
                    result.duplicates_dropped += 1
                    continue
                seen.add(ev.event_id)
                result.events.append(ev)

            result.products_used.append(product)
            log.info("[FIRMS] response received %s rows=%d usable=%d", product, len(rows), len(events))

            # A successful, valid response (including a genuinely empty area)
            # is authoritative for the current source.  Do not issue needless
            # secondary downloads; failures above naturally advance to the
            # configured fallback product.
            break

        if not result.products_used:
            if network_down:
                raise FirmsError(
                    "Could not reach NASA FIRMS. " + "; ".join(result.errors[:2]),
                    kind="unavailable",
                )
            if key_rejected:
                raise FirmsError(
                    "NASA FIRMS rejected the configured MAP_KEY. Replace FIRMS_MAP_KEY on the server.",
                    kind="not_configured",
                )
            raise FirmsError(
                "No FIRMS product could be reached. " + "; ".join(result.errors[:3])
                if result.errors
                else "No FIRMS product could be reached."
            )
        return result


def default_start_date(day_range: int) -> date:
    """FIRMS NRT lags slightly; start one day back so the window is populated."""
    return (datetime.now(timezone.utc) - timedelta(days=day_range)).date()

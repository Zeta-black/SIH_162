# GIS storage and export

PS 26162 R4 asks for GIS-based data storage and visualisation. Visualisation is
the map. This is the other half: where the geometry lives, and how to get it out
into the tools a regulator or a disaster-management cell actually uses — which is
QGIS and ArcGIS, not someone else's web page.

---

## 1. What is stored where

| Store | Holds | Geometry | Lifetime |
|---|---|---|---|
| **SQLite** `backend/app/data/firetrace.sqlite3` | Ingested detections, facilities, classifications, ingest runs, notifications, delivery audit | Lat/lon columns with a composite index | Persists across restarts; gitignored |
| **Committed archive** `backend/app/data/demo_snapshot.json` | 716 real FIRMS detections, 1,482 real OSM facilities, 6,021 land-use polygons | GeoJSON-shaped records | Tracked in git — this is what makes the app work offline |
| **Live cache** `backend/app/data/cache/` | Last good live FIRMS fetch, with its timestamp | As ingested | 72 h expiry; gitignored |

### Why SQLite and not PostGIS

`docs/postgis_schema.sql` exists from round 1 and describes the schema a real
deployment would use. It is not what runs.

The honest reason: this has to start with `npm run demo` on a laptop with no
internet and no database server. A PostGIS dependency makes that impossible, and
the spatial work here — a radius query and a bounding-box filter — is served
adequately by an index on `(latitude, longitude)` plus a coarse in-memory grid
(`services/geo.py::SpatialGrid`). At 716 archived and a few thousand live
detections, that is not the bottleneck; the 20-minute analysis cache is what
makes the screen fast.

**SpatiaLite is not used either.** It would need a loadable extension that is not
present in the stock Windows Python build, which is the platform the demo runs
on.

If this became real, the migration is small: the store is behind one module
(`store/db.py`) and the schema already exists.

---

## 2. Layers

Four, each exported independently because they answer different questions.

| Layer | Geometry | One row is | Key attributes |
|---|---|---|---|
| `detections` | Point | One **grouped site** (not one raw pixel) | `status`, `predicted_class`, `model_score`, `abstained`, `operational_priority`, `priority_score`, `abnormality_score`, `abnormality_status`, `persistent`, `distinct_days`, `detection_count`, `distinct_passes`, `frp_max_mw`, `frp_total_mw`, `brightness_max_k`, `nearest_facility`, `nearest_facility_km`, `land_cover`, `observed_at`, `verdict` |
| `persistent_sources` | Point | A location with heat on ≥ 5 days | `days_active`, `baseline_min_mw`, `baseline_max_mw`, `abnormality_score`, `abnormality_status` |
| `facilities` | Point | A mapped OSM industrial feature | `facility_id`, `name`, `category`, `osm_type`, `osm_id` |
| `notifications` | Point | An alert that carries a position | `reason_code`, `severity`, `state`, `policy_version`, `is_test` |

Two deliberate choices:

- **`detections` holds sites, not pixels.** 716 raw detections group into 390
  sites. Exporting pixels would hand an analyst the same de-duplication problem
  the app exists to solve.
- **`abnormality_status` travels with `abnormality_score`.** An export that
  dropped the status would let a null score be read as a zero — "not unusual"
  instead of "we could not tell". That is the Pass 1 defect leaking into a file,
  and `test_abnormality_status_travels_with_the_export` exists to prevent it.

---

## 3. Endpoints

```
GET /api/export/geojson/{layer}?mode=demo&days=1[&range=<id>]
GET /api/export/gpkg?mode=demo&days=1[&range=<id>]
```

`{layer}` is one of `detections`, `persistent_sources`, `facilities`,
`notifications`. An unknown layer returns 404 and lists the real ones.

Both accept the same `mode` / `days` / `range` parameters as `/api/map`, so an
export matches exactly what is on screen — including a Past-data range.

In the interface: **Layers popover (bottom-right) → Download GIS data.**

### Earlier endpoints, still present

`/api/export/json`, `/api/export/csv` and `/api/export/geojson` (unsuffixed,
detection-level) are from round 1 and still work. The suffixed per-layer routes
and the GeoPackage are the Pass 2 additions.

---

## 4. GeoPackage

One `.gpkg` file, all four layers, **EPSG:4326 (WGS 84)**.

### Written with sqlite3, not GDAL

This looks like the wrong call, so the reasoning:

A GeoPackage **is** SQLite with two required metadata tables and a documented
binary geometry header (OGC 12-128r15). Python ships `sqlite3`. Adding GDAL to
produce one file would add a ~100 MB wheel chain to a project whose entire
promise is `npm run demo` on a laptop with no internet — and GDAL wheels on
Windows are the single most common "it will not install" failure in Python GIS.

So `services/gis.py` writes the format directly:

- `PRAGMA application_id = 1196444487` (`GPKG`), `user_version = 10400`
- `gpkg_spatial_ref_sys` with WGS 84 plus the two required undefined SRS rows
- `gpkg_contents` with per-layer bounding boxes and `srs_id`
- `gpkg_geometry_columns` declaring `POINT`, `z=0`, `m=0`
- one table per layer: `fid INTEGER PRIMARY KEY AUTOINCREMENT`, `geom BLOB`, then
  one column per attribute with types inferred from the values present
- each `geom` is `"GP"` + version + flags `0b00000001` (little-endian, no
  envelope — a point's envelope is itself) + little-endian WKB

Booleans are stored as 0/1, because SQLite has no boolean and some GIS clients
will not read a raw Python bool.

### Correctness is established by reading it back

Writing a file proves nothing. `gis.read_back()` reopens the artefact and
reports the application id, the registered layers, feature counts, SRS, bounding
boxes, and whether the geometry blobs carry the `GP` header.

`test_gis_export.py` (20 tests) asserts all of that, including that attributes
are queryable with plain SQL:

```sql
SELECT site_id, status, frp_max_mw FROM detections
WHERE status = 'needs_attention' ORDER BY site_id;
```

Smoke group 10 repeats the check end-to-end: it downloads over HTTP, writes the
bytes to disk, shells into Python and parses the result.

```
GeoPackage downloads — 328 KB
GeoPackage identifies itself as one
GeoPackage holds all four layers — detections, persistent_sources, facilities, notifications
GeoPackage geometry is WGS 84 with valid headers
```

### Not verified

**It has not been opened in QGIS or ArcGIS on this machine**, and `ogrinfo` is
not installed here. The format checks above are thorough and the file is valid
by construction and by read-back, but "opens in QGIS" is a claim nobody here has
tested. Treat it as very likely rather than verified, and open it once before
relying on it in front of an evaluator.

---

## 5. Coordinate conventions

- Everything is **WGS 84 / EPSG:4326**, no reprojection anywhere.
- GeoJSON coordinate order is **`[longitude, latitude]`**, per RFC 7946 —
  asserted by `test_detections_layer_is_valid_geojson`, because lon/lat
  transposition is the most common GIS bug there is.
- Coordinates are rounded to 6 decimal places (~11 cm), well below VIIRS's 375 m
  pixel, so the rounding carries no information loss that matters.
- The bundled `frontend/src/data/india-outline.json` (Natural Earth, public
  domain) is rounded to 3 decimals for the country and 2 for states. It is a
  **visual fallback only** and is never used for analysis.

---

## 6. Re-verifying

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/test_gis_export.py -q
npm run smoke -- --only gis
```

To inspect a downloaded file yourself:

```bash
curl -s "http://127.0.0.1:8000/api/export/gpkg?mode=demo&days=1" -o firetrace.gpkg
cd backend && .venv/Scripts/python.exe -c "import json;from pathlib import Path;from app.services import gis;print(json.dumps(gis.read_back(Path('../firetrace.gpkg')),indent=2))"
```

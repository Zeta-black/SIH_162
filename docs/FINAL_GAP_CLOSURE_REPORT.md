# FIRETRACE — final gap closure report

## FIRMS

**Root cause:** a direct, redacted request to the configured FIRMS area endpoint
returned HTTP 400 with `Invalid MAP_KEY.`. The safe key-status endpoint also
returned HTTP 403. The URL shape, products, bbox encoding, and one-day range
were exercised; this is a rejected server credential, not a fabricated-data or
map-coordinate issue.

**Fix:** the FIRMS client now recognises the documented plain-text invalid-key
response, raises `not_configured`, and tells the operator to replace the
server-side `FIRMS_MAP_KEY`. Automatic mode falls back to the historical
snapshot with that exact source status. The UI now shows `Source degraded`,
never `Live NASA FIRMS`, when upstream is unavailable or the key is rejected.

**Verification:** mocked HTTP-400 invalid-key test passes; live request returned
the redacted invalid-key response. No secret was logged or exposed.

**Remaining limitation:** a valid current NASA FIRMS MAP_KEY is required for
live ingestion and cannot be supplied or repaired from source code.

## Global map

**Data flow:** real historical API response → coordinate validation → React
Leaflet marker input → detail endpoint. The snapshot contains 716 records; a
live API check found no `[0,0]` coordinates. Hotspot detail returned industrial
context, decision factors, and correctly ordered detection timeline.

**Hardening:** MapView now rejects malformed/non-finite/out-of-range coordinates
before Leaflet receives them, preserves a global initial viewport, and displays
explicit loading, empty-result, and basemap-tile-degraded states. The tile URLs,
marker generation, popup data, filters, and API transformations are build/lint
verified.

**Rendering verification:** no visual-browser pass is claimed. Chrome could not
be launched/refreshed by this execution environment; Vite proxy and map APIs
were verified over HTTP instead.

## Historical data

**Coverage:** India-only because the committed genuine historical snapshot was
captured for Indian study regions, not because the API or canonical event model
hardcodes India. The map has a global viewport and the backend accepts valid
worldwide bboxes. No international records were invented.

**Architecture:** source mode, source timestamp, product, satellite and raw
source reference remain on each canonical event, so adding an authenticated
international FIRMS capture does not require a schema redesign.

## AI/ML

**Current methodology:** a trained Random Forest reproduces a documented
weak-supervision source-type policy using 48 thermal, recurrence, infrastructure
and land-cover features. It is ML over policy-derived labels, not a confirmed
fire detector.

**Evidence/features:** observed FIRMS thermal/confidence/satellite fields;
calculated recurrence and proximity; OSM/land-cover context; predicted class and
vote confidence; explicit abstention where evidence is thin. The UI/API retain
the distinction between observed evidence and inferred classification.

**Evaluation:** 2,279 train / 0 validation holdout / 1,235 region-grouped test;
four classes. The constructed 1.000 figures demonstrate circular policy
reproduction, not real-world accuracy. The model card, API metadata and UI
carry the circularity warning.

**Not proven:** per-detection ground-truth fire cause, calibrated probability,
temporal generalisation, and operational classification accuracy.

## Security

**Findings/fixes:** invalid-key response bodies are redacted and secret values
remain server-side. CORS is explicit, inputs use Pydantic validation, and error
responses do not return tracebacks.

**Final audit:** `pip check` passed and `npm audit --omit=dev --audit-level=high`
reported zero vulnerabilities. The live smoke test verified the configured key
value does not appear in five public responses.

## Performance

| Workload | Result | Note |
|---:|---:|---|
| 10 | 155.4 ms median | Measured pipeline benchmark |
| 100 | 434.3 ms median | Measured pipeline benchmark |
| 1,000 | 3,063.0 ms median | Measured pipeline benchmark |
| 10,000 | 20,959.9 ms once / 2.096 ms per record | Cycles 716 genuine snapshot records; throughput only, not a unique-event scalability claim |

The 10,000-record run identifies clustering (10,122.9 ms) as the dominant
single-process/SQLite bottleneck. It is evidence for throughput on this laptop,
not a production-scale certification.

## Regression

- Backend FIRMS/API/store/geospatial suite: 96 passed after credential handling change.
- Full backend suite (three executed groups): 275 passed.
- Frontend lint and production build: passed after MapView hardening.
- Live smoke workflow: 21 passed, including replay, alerts, deduplication,
  lifecycle transitions, source latency separation and secret exposure checks.

## Remaining technical gaps

1. A valid NASA FIRMS key is required for live source operation.
2. No browser-level visual/DevTools verification is available in this execution environment.
3. Historical snapshot geography is India-only.
4. No verified classification ground truth exists.
5. The 10,000-record clustering result uses repeated source records and needs
   real larger data before it can support scale claims.

## Final engineering assessment

FIRETRACE is a defensible local geospatial intelligence application with real
historical FIRMS data, traceable provenance, explicit degraded operation,
replay, priority and alert workflows. It is not an independently verified live
fire-confirmation or production-scale service. The remaining gaps are external
credentials, dataset coverage/ground truth, and unavailable browser automation;
they are visible rather than hidden by the application.

# FIRETRACE final read-only technical gap audit

Project: FIRETRACE — Satellite Fire Intelligence & Response  
Problem statement: SIH 2026 PS 162 / SIH26162 — AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data

## Audit boundary

This audit was performed without modifying source code, configuration, model
artifacts, datasets, databases, or the user interface. The repository was clean
after inspection (`git diff --exit-code` and `git status --short`).

## Verified strengths

- No tracked `.env`; only `.env.example` is tracked.
- NASA FIRMS key handling is server-side; the frontend does not contact FIRMS directly.
- `npm audit --omit=dev` reported no production dependency vulnerabilities.
- `pip check` reported no broken Python requirements.
- FIRMS normalization, OSM enrichment, snapshot fallback, recurrence, model abstention,
  replay, and incident lifecycle transitions are implemented.
- Existing smoke evidence records 21 passing HTTP checks. A live-server rerun was not
  performed during this read-only audit because no server was running.

## Verified gaps

| Severity | Gap | Evidence and impact |
|---|---|---|
| High | No authentication or authorization | Incident actions, replay execution, manual classification, exports, and cache refresh are unauthenticated. This is suitable only for a trusted local demonstration environment. |
| High | GET endpoints have side effects | Analysis GET requests can call external providers and write to SQLite; `/api/events` can also create or update incidents. This complicates safe caching, browser prefetching, monitoring, and deployment security. |
| High | No API rate limiting | Repeated requests can consume FIRMS/Overpass quota, execute costly analysis, and grow the local store. |
| High | Circular weak-supervision ML evaluation | The 1.000 scores measure agreement with labels created by rules over model-visible features, not real-world fire-classification accuracy. Logistic regression also scores 1.000; industrial-fire holdout support is only 8 rows. |
| High | Alerts can arise from unverified classification | A critical alert is evidence-based triage, not independent confirmation. It must not be interpreted as authority-ready automated dispatch. |
| Medium | No scheduled ingestion | Live retrieval is on demand. Recurrence history can depend on prior dashboard/API activity rather than a controlled national ingestion schedule. |
| Medium | No external notification delivery | Alerts persist in-dashboard only; no SMTP, SMS, webhook, retry queue, delivery receipt, or escalation recipient exists. |
| Medium | Cached live data lacks explicit cache state | The 20-minute in-memory cache does not expose a cache flag, source fetch timestamp, or cache age in `DataSourceStatus`. |
| Medium | Silent 900-record analysis cap | Analysis selects only the top 900 records; the response does not explicitly disclose omitted raw records beyond that cap. |
| Medium | No clustering or viewport-driven retrieval on the map | The map renders individual markers and panning does not request a new bounded FIRMS area. This limits national/global-scale responsiveness. |
| Medium | Explicit global selection remains expensive | A world bbox can still be requested without a dedicated global aggregation architecture. |
| Medium | SQLite and cache are single-process design | SQLite and a process-local memory cache do not provide multi-worker coordination or horizontal scale. |
| Medium | Manual classification source state is imperfect | `/api/classify` creates `MANUAL_INPUT` but labels its `source_mode` as `snapshot`, rather than a distinct manual state. |
| Medium | OSM association is incomplete by nature | OSM facility names, geometry, categories, and coverage can be incomplete or stale. Proximity is association, not proof of cause or ownership. |
| Medium | Python dependency reproducibility is weak | Broad requirement ranges permit scikit-learn versions other than the inspected artifact environment, which may affect Joblib compatibility. |
| Medium | No probability calibration | Random Forest `predict_proba()` values are vote shares, not Platt-, isotonic-, or otherwise calibrated probabilities. |
| Low | Error response exposes exception type | Stack traces are hidden, but the global error response includes `error_type`, which offers minor implementation detail. |
| Low | Unauthenticated exports | JSON, CSV, and GeoJSON endpoints expose event locations if deployed beyond a trusted environment. |
| Low | External basemap dependency | OSM/OpenTopoMap tile availability and privacy are external dependencies; tile failure is handled visibly but offline tiles are absent. |
| Low | No browser-level regression suite | Build/API/replay evidence exists, but no automated browser coverage validates map interaction, responsive layout, keyboard use, or visual regressions. |

## Documentation integrity gaps

- `docs/AUDIT.md` states that event clustering and alert workflow are absent, although
  both are present in the codebase.
- `docs/FINAL_READINESS_REPORT.md` claims lint passed, while no lint script is defined
  in `package.json`.
- Some historical reports describe an invalid FIRMS key and global default behavior
  that do not match the current India-default, NOAA-21-primary implementation.
- Historical smoke and benchmark files are evidence for their recorded run time, not
  proof of the current deployment state.

## Security assessment

No tracked secret was found. The main deployment security gaps are missing
authentication, missing rate limiting, state-changing GET endpoints,
unauthenticated exports/cache clearing, and absence of a production deployment
boundary with TLS, secret management, and roles.

## Scientific and ML assessment

The model is technically implemented but not independently validated as an
industrial-fire detector. Its defensible claim is:

> ML-assisted thermal-source triage using FIRMS observations, OSM context, and temporal persistence.

It must not claim independently verified industrial-fire accuracy, calibrated
real-world probability, confirmed incident status, or automatic authority dispatch.

## Final assessment

FIRETRACE is a defensible local SIH prototype for thermal-anomaly triage,
map-based investigation, replay, and in-dashboard incident workflow. It is not
yet a production authority system because of authentication, rate limiting,
scheduled ingestion, notification delivery, ML ground truth, cache provenance,
global-scale map architecture, and documentation consistency gaps.


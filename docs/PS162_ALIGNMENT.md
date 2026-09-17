# PS 162 solution alignment

This is the internal traceability map for SIH26162 / serial 162. It is written
from the implementation and data artifacts, not from presentation claims.

| PS 162 need | FIRETRACE implementation | Data and processing | User-visible output | Evidence | Current limitation |
|---|---|---|---|---|---|
| Distinguish thermal anomalies from their likely source | Normalised FIRMS event plus classifier and abstention gate | NASA FIRMS thermal fields, OSM context, recurrence features and Random Forest vote share | `Likely source`, RF vote score, evidence and `UNKNOWN` when the system abstains | `backend/tests`, model artifact and replay cases | No incident-level ground truth; this is a likelihood, not confirmation |
| Separate industrial, agricultural and natural thermal activity | Four source classes: industrial fire, industrial heat/flare, agricultural burning and natural fire | Weak-supervision rules train the model from real FIRMS/OSM observations | Class label and model explanation | `backend/ml/data/dataset_manifest.json`, `backend/ml/artifacts/metrics.json` | Labels are inferred rules, not independently verified causes |
| Monitor persistent thermal sources | Recurrence index and spatio-temporal event grouping | Prior detections within configured radius and lookback window | Distinct days, persistence indicator and recurrence ring | `backend/tests/test_events.py`, replay output | Persistence is limited to records in the local history window |
| Use industrial infrastructure context | OSM facility retrieval, cached fallback and nearest-facility calculation | Real OSM tags, coordinates and geodesic distance | Named facility when OSM provides one, category and distance | `backend/tests/test_geo_features.py` | OSM can be incomplete, stale or unavailable; association is not ownership or proof |
| GIS visualisation and storage | Leaflet map, SQLite event store, GeoJSON/CSV/JSON exports | Validated coordinates and server-side API filtering | Map markers, inspector, exports and incident list | Frontend build and API tests | Current live demo is India-default and bounded, not global-scale operation |
| Alert / action workflow | Clustered fire events create persisted incidents with validated state transitions | Priority rule and incident state machine | Alert queue, acknowledge, dispatch, monitor, resolve and dismiss actions | `backend/tests/test_incidents.py` and end-to-end tests | No SMTP, SMS or other external notification delivery is implemented; an alert is generated in-app only |

## Claim boundary

`Thermal anomaly detected` is a NASA FIRMS observation. `Potential industrial
fire` or `persistent industrial thermal source` is an evidence-based
classification. Neither is a confirmed fire. Confirmation requires independent
evidence such as an authority, operator or incident report.

## Live and demonstration boundary

`live` records are retrieved by the backend from NASA FIRMS at request time.
`snapshot` records come from the frozen historical dataset. Auto-mode fallback
is explicitly rendered as degraded historical fallback; it must never be
described as live.

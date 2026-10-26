# PS 26162 compliance

**SIH 2026 · Problem Statement SIH26162** — AI-Based Detection and Classification
of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM &
Satellite Data. Organisation: National Technical Research Organisation (NTRO).
Theme: Disaster Management. Category: Software.

> **The official problem-statement text is not in this repository.** There is no
> `docs/PROBLEM_STATEMENT.txt`. The five requirements below are reconstructed
> from the title and the brief, and should be treated as **unverified** until
> someone pastes the official wording in. If the official text differs, this
> table is what needs correcting first.

Rules for this table: **no row says Done without a passing test or a recorded
reproducible check.** Where something is partial, the limitation is stated rather
than rounded up.

Last verified 2026-10-26 on branch `sih-pass2`, `npm run smoke` → 81/81.

---

## Summary

| | Requirement | Status |
|---|---|---|
| R1 | Classify industrial fires apart from natural/agricultural fires | **Partial** |
| R2 | Detect and track persistent thermal sources, flag abnormal behaviour | **Partial** |
| R3 | Integrate thermal, industrial/land-use, land cover and satellite imagery | **Partial** |
| R4 | GIS-based storage and map visualisation | **Done** |
| R5 | Monitoring and alerting for decision-makers | **Done** |

Two rows are Done and three are Partial. The Partials are all limited by **data**
rather than by missing features, and each says exactly how.

---

## R1 — Classify/segregate industrial fires from natural and agricultural fires

**Status: Partial.** The classification works and is honest about what it is. It
has never been validated against a verified fire.

| | |
|---|---|
| **Feature** | Random Forest over 48 features, four trained classes (`INDUSTRIAL_FIRE`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`, `AGRICULTURAL_BURNING`, `NATURAL_FIRE`) plus `UNKNOWN` from an abstention gate at 0.45. Plain-language verdict and up to three "why" lines per site. |
| **Where a judge sees it** | Open the map → click any marker. The card gives the status, a one-sentence verdict, the class in plain words ("Classified as Industrial fire"), and the reasons. **2 clicks: marker → See evidence.** |
| **Tests** | `test_map_verdict.py` (35), `test_model_honesty.py`, `test_labeling_priority.py` (37). Smoke group 9 asserts no notification claims a fire is confirmed. |
| **Limitation — state it out loud** | Training labels are **weak supervision**: nine deterministic rules over the same features the model sees. Reported accuracy and macro-F1 are **1.0 and circular** — they measure faithful reproduction of the rule policy, not fire-classification skill, and a depth-3 decision tree scores comparably. `backend/ml/artifacts/metrics.json` carries `circularity_warning: true`. `INDUSTRIAL_FIRE` has 72 labelled rows and 8 in the test set. **No detection in this project has a verified cause.** |
| **What would close it** | Per-detection ground truth: incident reports from plant operators or a state pollution control board. The analyst labelling control (R1 addendum below) is the path to collecting it. |

### R1 addendum — honest validation surfaces

Because the headline metric is meaningless as a capability claim, three things
exist so the project does not lead with it:

- **No screen, slide or doc leads with 1.0.** `docs/MODEL_AUDIT.md` opens by
  saying the metric is circular; `JUDGE_QA.md` Q3 answers it directly; the
  claims register marks "validated real-world accuracy" as **never claim this**.
- **"About this data"** (the ⓘ button, top right) states the sources, the
  near-real-time caveat and the coverage limit in plain words — and now carries
  the consistency checks below, under their own caveat.
- **Consistency checks on real detections** (`MODEL_AUDIT.md` §6), measured by
  `python -m ml.proxy_checks` and titled *consistency checks, not ground truth*:

  | Check | Result |
  |---|---|
  | Recurring heat inside mapped industrial sites reads industrial | 92/98 (93.9%), 0 disagreements |
  | Single-day heat over vegetation far from industry reads agricultural or natural | 100/100 |
  | Agreement with the FIRMS static-source flag | **unavailable** — the `type` field is not retained |
  | Ablation without map context | abstention 8.3% → **74.6%**, median score 0.79 → 0.48 |

  The ablation is the useful one: stripped of facility and land-cover context the
  model abstains nine times more often rather than inventing confidence. **None
  of these is accuracy** — they compare the classifier against map context, not
  against verified incidents.

---

## R2 — Detect and track persistent thermal sources, separately from incidents

**Status: Partial.** The separation is implemented and visible. The abnormality
half is honest but thin.

| | |
|---|---|
| **Feature** | A location with heat on ≥ 5 separate days at ≥ 0.25 persistence ratio is a **persistent source**. Persistent sources render as **rings**; new heat renders as **filled discs**. The card badges it: "Persistent source · seen on 8 days" or "New heat". The heat band draws the location's own measured radiative-power range. |
| **Where a judge sees it** | The rings and discs are visible on the map without explanation. Click one → the badge and the day count are on the card. **1 click.** The persistent layer can also be toggled alone in the Layers popover. |
| **Tests** | `test_abnormality_baseline.py` (21), `test_events.py`, `test_gis_export.py::test_persistent_layer_holds_only_persistent_sources`. Smoke group 10 exports the persistent layer separately. |
| **Limitation — state it out loud** | Abnormality can only be **assessed for 16 of 390 sites (4%)**. 325 sites have zero prior detection days in the archive, so "unusual for this location" has nothing to be unusual against; those sites report **"not assessed — too little history here"** rather than a number. This was Pass 1's worst defect (a fabricated 1.0 on 70% of detections) and is now correct rather than impressive. |
| **What would close it** | A denser archive. `MIN_DAYS_FOR_BASELINE` is 2; most sites do not reach it because the archive samples ten 5-day windows rather than running continuously. This is data collection, not code — see "Not done" below. |

---

## R3 — Integrate thermal data, industrial/land-use context, land cover, imagery

**Status: Partial.** Three of four integrated. Land cover is partial by
availability; optical imagery is basemap-only.

| Source | State | Where |
|---|---|---|
| **NASA FIRMS thermal** | **Done.** VIIRS + MODIS, normalised across incompatible product schemas, with each product's missing fields recorded rather than back-filled. | Everywhere. `provenance.source`, and the per-site products in the evidence drawer. |
| **OpenStreetMap industrial + land use** | **Done.** 1,482 real facilities with OSM ids; nearest-facility distance is a model feature and a "why" line. | Card subtitle, evidence drawer → Place, Facilities layer, GIS export. |
| **Land cover** | **Partial.** Taken from OSM landuse/natural polygons, not a spectral raster — and named accordingly so nothing implies a satellite classification. Unavailable for roughly half the detections, where it reports "not mapped" and never guesses. | Evidence drawer → Place → "Surroundings: …". |
| **Satellite imagery** | **Partial.** A Map / Satellite switch using Esri World Imagery (verified keyless, real imagery). **There is no per-event optical check** — no Sentinel-2 scene lookup and no band-ratio test. The evidence drawer says "Optical check: not available" rather than implying one happened. | Bottom-right Map/Satellite control. **1 click.** |
| **Tests** | `test_geo_features.py`, `test_firms.py`, smoke group 7 asserts the tile host is keyless. |
| **Limitation** | Esri's terms for direct third-party tile access are **not unambiguous**. The layer is fully attributed and one constant in `CalmMap.jsx` disables it. A deployment would want either an Esri licence or a different provider. |

---

## R4 — GIS-based data storage and map visualisation

**Status: Done.**

| | |
|---|---|
| **Storage** | SQLite with spatial indices on date and lat/lon (`backend/app/store/db.py`), plus a committed JSON archive of real detections and OSM features. Detailed in `docs/GIS.md`. |
| **Visualisation** | A full-viewport Leaflet map with status-coloured, shape-differentiated markers, clustering, a layers popover, a Map/Satellite switch, and a replay timeline. |
| **Export** | **GeoJSON per layer** (`/api/export/geojson/{detections,persistent_sources,facilities,notifications}`) and a **single OGC GeoPackage** of all four layers in WGS 84 (`/api/export/gpkg`). |
| **Where a judge sees it** | Layers popover (bottom-right) → **Download GIS data**. **2 clicks.** |
| **Tests** | `test_gis_export.py` (20) writes a GeoPackage and **reads it back**, asserting the application id, the three required metadata tables, four layers, SRS 4326 and valid geometry headers. Smoke group 10 repeats this end-to-end over HTTP on the downloaded bytes. |
| **Note** | The GeoPackage is written with `sqlite3` rather than GDAL deliberately — a ~100 MB wheel chain would break the "runs on a laptop with no internet" promise. Correctness is established by reading the file back, not by trusting the writer. |

---

## R5 — Monitoring and alerting for decision-makers

**Status: Done.**

| | |
|---|---|
| **Feature** | Four triggers (`NEEDS_ATTENTION`, `ABNORMAL_PERSISTENT`, `NEW_HEAT_AT_FACILITY`, plus system notices), a stored state machine (created → seen → acknowledged → snoozed → resolved), and four channels: in-app centre, toast, opt-in browser notification, optional webhook. Full policy in `docs/NOTIFICATION_POLICY.md`. |
| **Where a judge sees it** | The bell, top right. **1 click** shows the queue grouped Needs attention / System, each with Open on map · Acknowledge · Snooze. A second click on the gear shows the policy version and "Send test alert". |
| **Monitoring** | A lightweight `/api/changes` poll every 45 s brings new items in without a reload, and the map never moves under the user's hands — a "N new" pill appears instead. |
| **Tests** | `test_notifications.py` (41): triggers, dedupe, cooldown, escalation, hysteresis, daily cap, state machine, webhook retry with audit rows, replay safety, and that no message can say "confirmed". Smoke group 9 adds 17 end-to-end checks. |
| **Limitation** | **No SMS or email is built in.** The webhook can be relayed to either by a free automation tool; we do not claim to send them. No escalation chains, on-call rotas or per-user routing — there are no user accounts, so acknowledgement is shared state. |
| **Alert fatigue** | Explicitly designed against: Normal, Watch and Not sure **never** notify, one bell per site per evaluation, and a quiet first run so a cold start does not alert on every pre-existing site at once. |

---

## Deliberately not done

Stated here rather than left for a judge to discover.

| Item | Why not |
|---|---|
| **Dense history backfill** (`scripts/backfill_history`) | Not written. It is the single highest-value next action — it takes R2's abnormality from 4% of sites to most of them — but it is a long-running data-collection job, not a demo feature, and FIRMS archive access for long windows needs a separate request to NASA. |
| **ESA WorldCover land-cover lookup** | Not integrated. Land cover stays OSM-derived and reports "not mapped" where absent. |
| **Sentinel-2 per-event optical check** | Not integrated. The satellite basemap switch ships instead, and the drawer says "Optical check: not available". |
| **Analyst labelling control** | The *schema* separates predicted class from any human label, but the popover and CSV export are not built. Mark reviewed records review, not a label. |
| **Dense history backfill** | Still not written. Unchanged from Pass 2 and still the highest-value next action. |
| **ESA WorldCover land cover** | Still not integrated. Land cover stays OSM-derived at ~53% coverage and reports "unavailable" where absent. |
| **Dark theme** | Built as a complete token set in `tokens.css` and it follows the system setting, but there is no manual toggle and it has had no design-QA pass. Light is the default and is what the demo should use. |

---

## How to re-verify this table

```bash
npm run smoke                 # 80 checks across all ten groups
cd backend && .venv/Scripts/python.exe -m pytest -q     # 428 tests
```

Per requirement:

```bash
# R1/R2 — classification, persistence, abnormality honesty
cd backend && .venv/Scripts/python.exe -m pytest tests/test_map_verdict.py tests/test_abnormality_baseline.py -q

# R4 — GIS export, including reading the GeoPackage back
cd backend && .venv/Scripts/python.exe -m pytest tests/test_gis_export.py -q

# R1 — the consistency checks
cd backend && .venv/Scripts/python.exe -m ml.proxy_checks

# R5 — notifications, including replay safety
cd backend && .venv/Scripts/python.exe -m pytest tests/test_notifications.py -q

# R3/R4/R5 end-to-end over HTTP
npm run smoke -- --only livepast
npm run smoke -- --only gis
```

# FIRETRACE

**AI-assisted detection and classification of industrial fires and persistent thermal sources
from NASA FIRMS, OpenStreetMap and land-use data.**

Smart India Hackathon 2026 · Problem Statement **26162** · National Technical Research
Organisation (NTRO) · Theme: Disaster Management · Team: **Classy Fires**

---

## The problem, and what FIRETRACE adds

NASA FIRMS tells you **where** a thermal anomaly is. It does not tell you **what** is causing
it. A refinery flare stack, a crop-residue fire, a forest fire and an actual industrial
accident can all surface as similar hotspots in the same feed.

FIRETRACE takes each FIRMS detection and assembles a chain of evidence around it:

```
  thermal detection          (NASA FIRMS: position, brightness, FRP, time)
      + geographic context   (OpenStreetMap: nearest industrial facility, type, distance)
      + land-cover context   (OpenStreetMap land-use polygons containing the point)
      + temporal behaviour   (how often this exact spot has burned before)
      ---------------------------------------------------------------
      = Random Forest        -> likely source + confidence + per-event explanation
                             -> transparent priority score
                             -> map, evidence panel, human verification
```

The output is always a **likelihood with its reasoning shown**, never a verdict.

---

## Contents

- [What is actually built](#what-is-actually-built)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Environment variables](#environment-variables)
- [Data sources](#data-sources)
- [The machine learning pipeline](#the-machine-learning-pipeline)
- [Explainability](#explainability)
- [FIRETRACE Priority Score](#firetrace-priority-score)
- [Demo mode and resilience](#demo-mode-and-resilience)
- [API reference](#api-reference)
- [Testing](#testing)
- [Scientific and prototype limitations](#scientific-and-prototype-limitations)
- [SIH demo script](#sih-demo-script)
- [Things learned by testing the real APIs](#things-learned-by-testing-the-real-apis)
- [Future work](#future-work)
- [QA and readiness report](docs/QA_REPORT.md)

**Phase 2.5 evidence** — produced by executing things, not by reading code:

| Document | What it contains |
|---|---|
| [Phase 2.5 result](docs/PHASE_2_5_RESULT.md) | Replay engine, latency, performance, duplicate-alert and workflow status |
| [Model card](docs/ML_MODEL_CARD.md) | Why the 1.000 score is a warning, not a result |
| [Test and replay cases](docs/TEST_CASES.md) | 30 real cases, each executed, with measured outcomes |
| [Smoke test](docs/SMOKE_TEST.md) | 21 checks against a live server, with evidence |
| [Performance results](docs/PERFORMANCE_RESULTS.md) | Measured at 10 / 100 / 1000 events |
| [Demo script](docs/DEMO_SCRIPT.md) | Seven-minute judge walkthrough |

---

## What is actually built

| Capability | Status |
|---|---|
| Live NASA FIRMS ingestion (VIIRS + MODIS, backend-only key) | Working |
| Normalized hotspot schema across differing FIRMS products | Working |
| OpenStreetMap industrial facility retrieval with mirror failover + disk cache | Working |
| Geodesic distance-to-facility feature | Working |
| Land-cover from OSM land-use polygons (ways **and** multipolygon relations) | Working |
| Recurrence / persistence features with strict no-leakage rule | Working |
| Random Forest classifier with UNKNOWN abstention | Working |
| Per-event explanation via decision-path decomposition | Working |
| Transparent priority score | Working |
| Interactive Leaflet dashboard with filters, table, inspector | Working |
| Demo / historical snapshot fallback (no network required) | Working |
| CSV + GeoJSON export | Working |
| Test suite | Working |
| PostGIS schema for production deployment | Documented (`docs/postgis_schema.sql`) |

---

## Quick start

Requires **Python 3.10+** and **Node 18+**. Everything used is free and open-source.

```bash
npm run setup     # creates the Python venv, installs backend + frontend deps
npm run dev       # starts the API and the dashboard together
```

Then open **<http://localhost:5173>**.

That is the whole thing. `npm run setup` is safe to re-run and skips anything already
done; `npm run dev` streams both processes into one terminal and Ctrl+C stops both.

> **No NASA key needed to run it.** FIRETRACE ships with a snapshot of real historical
> FIRMS and OpenStreetMap data, so the full workflow — map, classification, explanation,
> priority — works with no internet at all. The dashboard labels it **"Demo / Historical
> Data"** so it is never mistaken for a live feed.
>
> For live data, put a free key in `.env` (created for you by setup):
> `FIRMS_MAP_KEY=your_key` — get one at
> <https://firms.modaps.eosdis.nasa.gov/api/area/>.

### Other commands

| Command | What it does |
|---|---|
| `npm test` | Run the backend test suite (273 tests) |
| `npm run smoke` | End-to-end smoke test against a running server — needs `npm run dev` first |
| `npm run benchmark` | Benchmark the pipeline at 10 / 100 / 1000 events |
| `npm run build` | Production build of the dashboard |
| `npm run build-data` | Re-fetch NASA FIRMS + OSM and rebuild the labelled dataset |
| `npm run train` | Retrain the Random Forest and write fresh metrics |
| `npm run build-snapshot` | Refresh the offline demo snapshot |

### If code changes seem to have no effect

This project sits in a **OneDrive-synced folder**, and OneDrive's virtual-file layer
breaks the file watcher `uvicorn --reload` depends on. The server keeps serving the code
it started with, which looks exactly like "my edit did nothing".

Stop with Ctrl+C and run `npm run dev` again. The dev script also refuses to start when a
port is already held, so a half-dead previous instance is reported rather than silently
shadowing the new one.

### Running the halves separately

If you would rather run them in two terminals:

```bash
# terminal 1
cd backend && .venv/Scripts/activate     # Windows
# cd backend && source .venv/bin/activate  # macOS / Linux
uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev
```

API docs are at <http://127.0.0.1:8000/docs>, health at <http://127.0.0.1:8000/health>.

---

## The interface

Six screens, each answering one question a reviewer actually asks.

| Screen | Question it answers |
|---|---|
| **Operations** | What is happening right now: metric strip, priority worklist, evidence chain, classification mix. |
| **Explore** | Where is it happening? Map workspace: filters, layers, evidence inspector, detection table. |
| **Model** | How was the classifier built, and how do I know it works? Metrics, confusion matrix, feature importance, label provenance. |
| **Data** | Where did every value come from? Sources, fields, units, licences, measured coverage gaps. |
| **Method** | How does the system work end to end, and what does it refuse to do? |
| **Demo** | Does it actually work? Replay a real historical detection through the live pipeline, stage by stage, with measured timings. |

The shell is an **operations console**: a dark masthead, a persistent command bar (area,
window, source, export) that never scrolls away, and a telemetry status strip carrying
source, products, record count, window, geo status, model version and query latency.

Design is light, hairline-bordered and typographically dense — closer to SCADA and GIS
software than to a dashboard template. Every measurement is monospaced and right-aligned
so figures form scannable columns. Colour is reserved for data: chrome is steel grey and
the basemap is desaturated, so detections carry the only saturated hues on screen.

### The class palette was validated, not chosen by eye

The instinct is to make every fire class a shade of warm. Measured, that fails badly:
red/orange/amber scored a deuteranopia separation of **ΔE 1.1** (indistinguishable) and
**8.6 for normal vision**. Moving persistent industrial heat to violet — which is also
how the team's own proposal deck drew it — clears every check.

| Class | Colour | Code |
|---|---|---|
| Industrial fire | `#a51d12` | `IND` |
| Gas flare / persistent heat | `#8250df` | `FLR` |
| Agricultural burning | `#b8860b` | `AGR` |
| Natural / vegetation fire | `#1a7f4b` | `NAT` |
| Unclassified | `#6b7280` (neutral) | `UNK` |

Colour is never the only cue: every class carries a three-letter code and a text label,
in the legend, on the map popups and in the table.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  React + Leaflet dashboard          (frontend/, port 5173)   │
│  map · filters · event table · evidence inspector            │
└───────────────────────────┬──────────────────────────────────┘
                            │  HTTP / JSON  (never touches NASA directly)
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI backend                    (backend/app, port 8000) │
│                                                              │
│   api/routes.py      validation, filtering, export           │
│   services/pipeline  Detect → Analyse → Classify → Prioritise│
│     ├── firms.py      NASA FIRMS client + normalizer         │
│     ├── osm.py        Overpass facilities + land-use         │
│     ├── landcover.py  pluggable land-cover provider          │
│     ├── recurrence.py temporal/persistence features          │
│     ├── features.py   ONE feature pipeline (train + serve)   │
│     ├── classifier.py Random Forest + local explanation      │
│     ├── priority.py   transparent weighted score             │
│     └── snapshot.py   frozen real-data fallback              │
│   store/db.py        SQLite event store (PostGIS documented) │
└───────────────────────────┬──────────────────────────────────┘
                            │
        ┌───────────────────┼────────────────────┐
        ▼                   ▼                    ▼
   NASA FIRMS         Overpass / OSM      demo_snapshot.json
   (live, keyed)      (cached, mirrored)  (offline fallback)
```

**The key never reaches the browser.** The frontend only ever calls the FastAPI backend;
the backend holds `FIRMS_MAP_KEY` and scrubs it from every log line and error message.

---

## Project structure

```
SIH 26/
├── README.md
├── package.json                    npm run setup / npm run dev
├── scripts/                        dependency-free Node launchers
│   ├── common.mjs
│   ├── setup.mjs
│   ├── dev.mjs
│   └── run.mjs
├── .env.example                    template (no secrets)
├── .gitignore                      .env is never committed
├── docs/
│   ├── postgis_schema.sql          production database schema
│   └── QA_REPORT.md                what was verified, and what is still weak
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                 FastAPI app, logging, lifespan
│   │   ├── config.py               every tunable, one place
│   │   ├── schemas.py              Pydantic models / API contract
│   │   ├── taxonomy.py             classes, colours, vocabularies
│   │   ├── api/routes.py           HTTP endpoints
│   │   ├── api/provenance.py       data provenance, read live
│   │   ├── services/               the analysis chain (see architecture)
│   │   ├── store/db.py             SQLite event store
│   │   └── data/
│   │       ├── demo_snapshot.json  frozen REAL data for offline demo
│   │       └── cache/              Overpass response cache
│   ├── ml/
│   │   ├── regions.py              areas of interest
│   │   ├── windows.py              FIRMS request windows
│   │   ├── enrich.py               shared offline enrichment
│   │   ├── build_dataset.py        build the labelled dataset
│   │   ├── train.py                train + evaluate + persist
│   │   ├── build_snapshot.py       build the demo snapshot
│   │   ├── data/                   training_dataset.csv, manifest
│   │   └── artifacts/              firetrace_rf.joblib, metrics.json
│   └── tests/
└── frontend/
    ├── package.json
    ├── vite.config.js              dev proxy to the backend
    └── src/
        ├── App.jsx                 shell, routing, shared query state
        ├── api.js                  the only place that calls the backend
        ├── styles.css              light design system
        ├── pages/
        │   ├── Overview.jsx        what is happening
        │   ├── Explore.jsx         map workspace
        │   ├── Model.jsx           metrics, matrix, importance, labels
        │   ├── DataSources.jsx     provenance
        │   └── Method.jsx          pipeline and limits
        ├── components/
        │   ├── MapView.jsx         Leaflet workspace
        │   ├── Inspector.jsx       per-detection evidence panel
        │   └── ui.jsx              Panel, Provenance, ErrorState, BarRow …
        └── lib/
            ├── useApi.js           loading / error / empty / retry, debounce
            ├── useAnalysis.js      shared analysis query
            ├── classes.js          taxonomy from the API, never hardcoded
            └── format.js
```

---

## Environment variables

Names only — never commit values. Full list with comments in `.env.example`.

| Variable | Purpose |
|---|---|
| `FIRMS_MAP_KEY` | NASA FIRMS API key. **Backend only.** Optional: without it the app runs in snapshot mode. |
| `FIRMS_SOURCES` | Comma-separated FIRMS products to try, in order. |
| `FIRMS_DEFAULT_BBOX` | Default area of interest, `west,south,east,north`. |
| `LOG_LEVEL` | `INFO` by default. |
| `CORS_ORIGINS` | Allowed frontend origins. |
| `UNKNOWN_ABSTENTION_THRESHOLD` | Below this top probability, the model reports UNKNOWN. |
| `CONFIDENCE_HIGH_THRESHOLD` / `CONFIDENCE_MEDIUM_THRESHOLD` | Confidence band cut points. |
| `FACILITY_SEARCH_RADIUS_KM` | How far to look for an industrial facility. |
| `FACILITY_ONSITE_KM` | Distance treated as "on the facility footprint". |
| `RECURRENCE_RADIUS_KM` / `RECURRENCE_LOOKBACK_DAYS` | What counts as "the same thermal source". |
| `DENSITY_RADIUS_KM` | Radius for same-pass co-detection density. |
| `PRIORITY_WEIGHT_*` | The six priority-score weights. |

---

## Data sources

All free, no paid APIs, no paid map tiles.

### NASA FIRMS
Thermal anomaly detections. Two product families are supported and **they do not share a
schema** — this was verified against the live API rather than assumed:

| | VIIRS | MODIS |
|---|---|---|
| Brightness | `bright_ti4` | `brightness` |
| Secondary channel | `bright_ti5` | `bright_t31` |
| Confidence | letter `l`/`n`/`h` | number `0-100` |

`services/firms.py` maps both onto one normalized schema and records anything a product did
**not** supply in `unavailable_fields` rather than inventing a value for it.

### OpenStreetMap (Overpass API)
- **Industrial facilities**: refineries, power plants, works, chemical plants, cement,
  mines/quarries, gas and oil infrastructure, industrial estates.
- **Land-use polygons**: farmland, forest, scrub, industrial, residential, water and more.

Public Overpass instances are donated infrastructure, so FIRETRACE snaps requests to a tile
grid, caches every response on disk for a week, fails over across three mirrors, and spaces
its requests.

### Land cover — read this carefully
FIRETRACE does **not** classify land cover from satellite reflectance. It asks which
OpenStreetMap land-use polygon contains the hotspot. That is a **cartographic proxy, not a
spectral product**, and every land-cover result carries a `source_note` saying so. The
provider is pluggable (`OsmLanduseProvider`, `SnapshotLanduseProvider`, `UnavailableProvider`)
so a real raster source can be dropped in without touching anything else.

Where no polygon covers the point, the result is `unknown` — never a guess. **In rural India
this is common**, and it is a genuine limitation, not a bug. See
[limitations](#scientific-and-prototype-limitations).

---

## The machine learning pipeline

### Classes

| Class | Meaning |
|---|---|
| `INDUSTRIAL_FIRE` | On/beside industrial infrastructure, episodic — an abnormal event. |
| `GAS_FLARE_OR_INDUSTRIAL_HEAT` | On industrial infrastructure, repeats most days — routine. |
| `AGRICULTURAL_BURNING` | Over cropland, typically low FRP, seasonal. |
| `NATURAL_FIRE` | Over forest/scrub/grassland, away from industry. |
| `UNKNOWN` | **Not a trained class.** An abstention. |

`UNKNOWN` is applied when the model's top RF vote score falls below
`UNKNOWN_ABSTENTION_THRESHOLD` (default 0.45). The system says "I don't know" instead of
forcing a weak guess — and the strongest trained class stays visible in the UI so nothing
is hidden.

### Features (~60 columns, one pipeline)

`services/features.py` is the **single** implementation used by both training and inference.
There is deliberately no second code path, so the two cannot drift.

- **Thermal** — brightness, secondary channel, *channel separation* (a small very hot source
  like a flare separates the two channels far more than a broad cooler burn front), FRP,
  log FRP, FIRMS confidence.
- **Spatial** — latitude, longitude, geodesic distance to nearest industrial facility,
  inverse-distance proximity, on-site flag, facility category (one-hot), high-heat-process flag.
- **Land cover** — one-hot over eight categories.
- **Temporal** — recurrence count, distinct days, detections in last 7 days, persistence
  ratio, same-pass co-detection density, persistent flag.
- **Seasonality** — day-of-year on a circle (sin/cos), so 31 Dec and 1 Jan stay adjacent.
- **Missingness** — explicit `*_missing` indicators, so "FRP not reported" stays visible to
  the model instead of being silently imputed away.

Categorical values are one-hot encoded against **fixed vocabularies**, so column order is
guaranteed stable and an unseen category is impossible.

### Training labels — the most important caveat in this project

There is no public, per-detection ground-truth dataset that says *"this FIRMS pixel was a
refinery fire"*. So:

- **The observations are real.** Every coordinate, brightness value, FRP reading, timestamp
  and surrounding facility comes from NASA FIRMS and OpenStreetMap.
- **The labels are inferred, not verified.** They are produced by the explicit rule policy in
  `app/services/labeling.py` — a documented *labelling policy*, not field reports.
- **Therefore any metric printed by `ml.train` measures how well the Random Forest reproduces
  that policy on held-out detections.** It is *not* real-world fire-type accuracy, and that
  caveat is carried in the model metadata, the `/api/model/info` response and the UI.

Two things make this more than circular reasoning:

1. **The policy refuses to label ambiguous cases.** A large share of real detections fall
   through every rule and are written to `unlabelled_detections.csv` instead of being forced
   into a class. Training on confident examples beats training on coin flips.
2. **The policy makes hard threshold cuts on a handful of signals; the model sees ~60
   features.** The forest generalises across the smooth space between the policy's step
   functions rather than memorising a lookup table.

Every labelled row records the rule that produced it (`label_rule`) and a human-readable
`label_rationale`, so the dataset is auditable row by row.

### Splitting

The train/test split is **grouped by region** where there are enough regions. A random
row-wise split would put detections from the same refinery in both train and test, and the
model would score well by memorising locations rather than learning anything transferable.
Grouping forces it to generalise to industrial sites it has never seen — which produces
lower, more honest numbers.

### Results as actually measured — and why the score is a warning

From the shipped dataset: **10,804 real FIRMS detections** processed, **3,514 labelled**
(7,290 — 67.5% — left unlabelled because the evidence was ambiguous), split **2,279 train /
1,235 test, grouped over 11 regions**. The three test regions (`angul`, `punjab_central`,
`taloja`) appear in no training row.

| Metric | Value |
|---|---|
| Accuracy | 1.000 |
| Balanced accuracy | 1.000 |
| Macro F1 | 1.000 |
| OOB score | 0.999 |

Every class scores precision = recall = F1 = 1.00 (support: flare 998, agricultural 181,
natural 48, **industrial 8**).

**A perfect score is not a result. It is evidence of label circularity, and we are
reporting it as such.**

The labels come from a deterministic rule policy that decides using facility distance,
persistence, FRP and land cover — and the model is handed those same columns. So the task
is not "classify fires", it is "recover a rule set", which is easy. The baselines prove it:

| Model | Balanced acc. | Macro F1 |
|---|---|---|
| Majority class | 0.250 | 0.224 |
| Stratified random | 0.303 | 0.235 |
| One-rule stump | 0.497 | 0.331 |
| Depth-3 decision tree | **0.997** | 0.991 |
| Logistic regression | **1.000** | 1.000 |
| Random Forest (shipped) | **1.000** | 1.000 |

**Random-Forest lift over the best baseline: 0.000.** A three-question decision tree matches
it. A linear model matches it exactly. The ensemble buys nothing in accuracy terms.

Three further things we point at rather than hide:

1. **`INDUSTRIAL_FIRE` rests on 72 labelled rows and only 8 test rows.** Eight. Its 1.00
   per-class score has an enormous confidence interval and should be read as anecdote. This
   is the weakest number in the project.
2. **Across 12 resampled region-grouped splits the Random Forest is the *least* stable of
   the competitive models** — 0.969 ± 0.068, min **0.750**, against logistic regression's
   0.996 ± 0.004. The single-split 1.000 is a favourable draw, not a stable property.
3. **Leakage was audited separately and is CLEAN** — 0 shared feature rows, coordinates,
   regions or detection IDs across the split. One real leak *was* found and fixed: 18
   detections in the overlapping Punjab bounding-box strip were fetched twice under
   different region IDs, now deduplicated on `event_id`. Train and test do still share a
   48-day window, so this is spatial generalisation evidence only — **not** temporal.

`ml/train.py` refuses to let this travel without its caveat: at balanced accuracy ≥ 0.98 it
prints a blocking warning and writes `circularity_warning: true` into `metrics.json`.

The full disclosure, including what the model *is* genuinely worth (a probability that
drives the abstention gate, and coverage of the 67.5% of detections the policy will not
label), is in **[docs/ML_MODEL_CARD.md](docs/ML_MODEL_CARD.md)**.

### Reproducing

```bash
cd backend
python -m ml.build_dataset   # writes ml/data/training_dataset.csv + manifest
python -m ml.train           # writes ml/artifacts/firetrace_rf.joblib + metrics.json
```

Fixed random seed (42). `ml/data/dataset_manifest.json` records exactly which regions,
windows, products and rules produced the dataset.

---

## The evidence gate

The single most important correctness fix in this project, and it was found by running
the finished model against live data rather than by reading code.

**Symptom.** A live India-wide query in September — outside any crop-residue burning
season — returned **810 of 900 detections as agricultural burning**, at a median
confidence of 0.66.

**Diagnosis.** Of those 810, **800 had no land cover at all** and **804 had no mapped
industrial facility within 12 km**. Two of the model's four strongest features were
simply absent, so the forest was voting on latitude, longitude and radiative power — and
still returning a confident-looking number. It had learned that *absence of evidence
resembles cropland*, because the labelling rule that rescued the agricultural class from
OSM's missing farmland had permitted `unknown` land cover.

**Fix.** The abstention threshold now depends on whether the discriminating evidence was
available at all:

```
facility within radius OR land-use polygon present   ->  abstain below 45%
neither                                              ->  abstain below 72%
```

Detection history deliberately does **not** satisfy the gate. Recurrence separates a
persistent source from a one-off — which is what distinguishes a flare from an incident —
but it says nothing about whether the ground below is a wheat field or a forest. The
first version of the gate accepted history, and it passed almost every detection the gate
exists to catch.

**Result on the same query:** agricultural burning **810 → 164**, unclassified
**32 → 678**, of which 649 state the reason explicitly. In September, over rural India,
with no land cover and no facility nearby, "I don't know" is the truthful answer.

---

## Explainability

Global feature importance answers *"what does this model rely on in general?"*, which is a
different question from *"why did it say that about **this** hotspot?"*.

So the per-event explanation is genuinely **local**: for each prediction, every tree's
decision path is walked and the change in class probability at each split is attributed to
the feature that caused the split. Averaged over the forest, these contributions plus the
bias term sum to the predicted probability. (This is the standard tree-interpreter
decomposition, implemented directly in `services/classifier.py` so no extra dependency is
needed.)

One-hot columns are collapsed back into the concept a person thinks in ("Land cover", not
eight near-zero rows), and each factor is rendered as a sentence backed by the real measured
value:

```
Likely Source      Gas Flare / Persistent Industrial Heat
RF vote score      0.82  (HIGH; uncalibrated)

Factors influencing this prediction
  +  0.18 km — on the facility footprint of Reliance Jamnagar Refinery
  +  Detected on 19 separate days in the last 60 days
  +  Fire radiative power is 41.3 MW
  −  Land cover here is unknown
```

The wording is always *"factors influencing the model's output"*, never *"this caused the
fire"*.

---

## FIRETRACE Priority Score

A deliberately transparent weighted sum — not a second opaque model. Every component is a
named 0–1 number, every weight is configurable, and the API returns **both** alongside the
score so a user can see exactly how it was reached and disagree with it.

```
score = 0.20 · model_confidence
      + 0.25 · class_severity
      + 0.20 · thermal_severity        (log FRP, or brightness if FRP absent)
      + 0.15 · industrial_proximity    (1.0 on site → 0 at search radius)
      + 0.10 · abnormality             (1 − persistence)
      + 0.10 · recency                 (exponential decay, 3-day half-life)
```

The component worth demonstrating is **`abnormality`**. A flare stack that burns every single
day is *routine* and should sink down the queue; a strong detection at a plant that has never
lit up before is exactly what an emergency team wants at the top. So **persistence lowers
priority**. That is the difference between a fire-detection feed and a triage tool.

> This is a prototype triage aid defined by this project. It is **not** an official government
> risk rating and has not been validated against incident outcomes.

---

## Demo mode and resilience

### The snapshot
`app/data/demo_snapshot.json` is a **frozen capture of real NASA FIRMS detections and real
OpenStreetMap features**, built by `ml/build_snapshot.py`. It is not synthetic. It is,
however, historical — so every response built from it is tagged `mode: "snapshot"` and the
dashboard shows a persistent **"Demo / Historical Data"** banner. Presenting a frozen capture
as a live feed would be dishonest even though the observations are genuine.

It ships with curated scenarios, each pointing at a **real detection** in the file:

| Scenario | Shape |
|---|---|
| A | On an industrial facility, repeating across many days, strong signal |
| B | One-off strong detection near industry, no history of repeating |
| C | Vegetation fire well clear of any industrial facility |
| D | Ambiguous evidence → the model abstains (UNKNOWN / low confidence) |

If no detection genuinely fits a shape, that scenario is **omitted rather than fabricated**.

### Failure behaviour

| Failure | Behaviour |
|---|---|
| NASA key missing | Snapshot mode; banner explains why |
| NASA endpoint down / timeout / rate-limited | Automatic fallback to snapshot; user-facing message |
| One FIRMS product fails | Other products still used; partial result reported |
| Overpass mirror down | Fails over to next mirror, then disk cache, then stored facilities, then snapshot |
| Land-use unreachable | Land cover reported `unknown` — never guessed |
| Model artifact missing | Every event reported *Unclassified* with a note to run training; UI still works |
| Database unavailable | Analysis continues on freshly fetched data |
| Unhandled server error | Safe JSON message; stack trace goes to the log, never to the client |

The API test suite forces a **total NASA outage** and asserts the dashboard still returns a
usable response — the fallback path is tested, not just written.

---

## API reference

Interactive docs: `http://127.0.0.1:8000/docs`

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + model/store/snapshot/key status |
| `GET` | `/api/meta` | Classes, colours, thresholds, priority formula, disclaimer |
| `GET` | `/api/model/info` | Model version, metrics **with caveat**, label policy, top features, evidence gate |
| `GET` | `/api/sources` | Full data provenance, read from the live store at request time |
| `GET` | `/api/hotspots` | Classified events with server-side filters |
| `GET` | `/api/hotspots/{event_id}` | One event with its explanation computed |
| `GET` | `/api/dashboard/summary` | Headline counts, timeline, FRP by class |
| `GET` | `/api/facilities` | Facility layer for the current view |
| `GET` | `/api/facilities/nearby` | Facilities around a point, nearest first |
| `POST` | `/api/classify` | Classify an arbitrary coordinate |
| `GET` | `/api/scenarios` | Curated demo scenarios |
| `GET` | `/api/export/geojson` | GeoJSON FeatureCollection |
| `GET` | `/api/export/csv` | CSV export |
| `POST` | `/api/refresh` | Clear the analysis cache and re-query sources |

`/api/hotspots` filters: `bbox`, `days` (1–5), `mode` (`auto`/`live`/`demo`), `classification`,
`min_confidence`, `priority`, `max_facility_km`, `date_from`, `date_to`, `persistent_only`,
`limit`, `refresh`.

---

## Testing

```bash
npm test                     # whole suite, from the project root
```

or directly:

```bash
cd backend
.venv/Scripts/python -m pytest -q     # Windows
./.venv/bin/python -m pytest -q       # macOS / Linux
```

The suite covers the things that would actually be wrong if they broke:

- FIRMS normalization for **both** VIIRS and MODIS column layouts
- Confidence mapping (letters *and* percentages), `acq_time` without a leading zero
- Invalid coordinates and dates rejected rather than guessed; missing fields recorded
- Haversine correctness against published distances, plus an explicit guard that it is
  **not** naive degree subtraction
- Point-in-polygon including concave shapes; multipolygon ring stitching
- **No data leakage**: future detections must never count as an event's history
- Feature pipeline: one-hot exclusivity, missing-value indicators, circular seasonality,
  determinism
- Labelling policy including its refusal to label ambiguous evidence
- Priority score bounded, weights normalised, and **the published breakdown actually
  reproduces the score**
- Store round-trip, idempotent ingest, null preservation
- Classifier degrades safely when the model artifact is absent
- API validation, and **survival of a simulated total NASA outage**

Frontend build check:

```bash
npm run build
```

---

## Scientific and prototype limitations

Stated plainly, because overclaiming on a disaster-management tool is worse than
underclaiming.

1. **Satellite hotspots are not ground truth.** FIRMS reports a thermal anomaly, not a
   confirmed fire, and not its cause.
2. **The training labels are not verified.** They come from a documented rule policy, not
   field reports. Model metrics measure agreement with that policy — see
   [the ML section](#training-labels--the-most-important-caveat-in-this-project).
3. **Thermal signatures genuinely overlap.** A hot crop fire and a small industrial fire can
   look nearly identical to a 375 m sensor. This is the core difficulty of the problem
   statement, and no amount of modelling fully removes it. Abstention exists for this reason.
4. **OSM land-use coverage is thin, and it is measurable.** In central Punjab — the single
   most important region for crop-residue burning — **98% of detections fall inside no
   land-use polygon at all**, so land cover reads `unknown`. The cropland rules that depend
   on a farmland polygon therefore almost never fire there, and a separate rule keyed on the
   physical signature (many weak, short-lived fires co-detected in a harvest month, clear of
   industry) had to be added to recover the class. Coastal Gujarat is similar at ~74%
   unknown. This is a genuine data-availability limit, not a bug, and it weakens the
   agricultural/natural distinction specifically.
5. **OSM facility data can be incomplete, out of date, or *too* complete.** A missing factory
   means a real industrial fire may be classified as something else. The opposite also bites:
   OSM tags many small town workshops as `industrial`, so a naive "is it far from industry?"
   test disqualified nearly every genuine crop fire in well-mapped districts. The policy
   therefore tests proximity to *high-heat process* facilities, not to anything tagged.

6. **`INDUSTRIAL_FIRE` is the thinnest-evidenced class.** Only 72 labelled examples, and
   just 8 in the held-out set, so its per-class score is anecdote rather than measurement.
   Treat industrial-fire calls as candidates for review, and do not assume the absence of
   one means nothing happened.
7. **Clouds, satellite overpass timing and swath geometry cause missed detections.** Absence
   of a hotspot is not evidence of absence of fire.
8. **Recurrence needs history.** On a cold start the recurrence features are weak, and the
   system reports `history_available: false` rather than pretending a count of zero is
   meaningful evidence.
9. **The priority score is a prototype heuristic**, not a validated risk model.
10. **The land-cover layer is cartographic, not spectral.** It is OSM land use, not a satellite
    land-cover classification.
11. **This is a prototype.** It is not certified for operational emergency response. Every
    prediction requires human verification.

---

## SIH demo script

Two to three minutes, and it works with the network unplugged.

**0:00 — The gap.**
Open the dashboard. Point at the map: *"NASA FIRMS gives us these hotspots. It tells us
where the heat is. It does not tell us what is burning."*

**0:20 — The evidence chain.**
Click a **red** marker near an industrial cluster. The inspector fills in: nearest facility
and its type, distance in metres, land cover, how many separate days this exact spot has
burned. *"FIRETRACE assembles evidence around every detection."*

**0:50 — The classification and why.**
Read the verdict: *"Likely source: Gas flare / persistent industrial heat. RF vote score
82% — not a calibrated probability."* Then the factors. *"This is computed per event by decomposing the forest's decision
paths — these are the factors that moved this specific prediction."*

**1:20 — Flare versus fire.**
Compare an orange marker (persistent flare) with a red one (episodic fire near industry).
*"Same neighbourhood, same satellite, different behaviour over time. Persistence is what
separates routine flaring from an abnormal event."*

**1:45 — Priority, and the counter-intuitive bit.**
Open the priority breakdown. *"Transparent weighted sum, no hidden AI score. Note that
persistence **lowers** priority — a flare that burns every day is routine; a plant that has
never burned before suddenly lighting up is what you want at the top of the queue."*

**2:10 — Honesty.**
Filter to **Unclassified**. *"When the evidence is mixed, the model abstains instead of
guessing. Every screen says these are model-assisted likelihoods requiring verification."*

**2:30 — Resilience.**
Switch Mode to **Demo / historical snapshot** (or just note the banner). *"No NASA API, no
internet — the full Detect → Analyse → Classify → Visualise → Monitor workflow still runs on
a frozen capture of real data, clearly labelled as historical."*

**2:50 — Close.**
*"FIRMS answers where. FIRETRACE answers what is probably causing it, shows its working, and
tells you when it doesn't know."*

---

## Things learned by testing the real APIs

Documented because each one silently broke something before it was found, and each is the
kind of detail an assumed implementation gets wrong.

1. **FIRMS caps `day_range` at 5**, not 10 or 30. Anything else returns
   `HTTP 400 — "Invalid day range. Expects [1..5]."` Long observation periods have to be
   assembled from consecutive 5-day requests.
2. **VIIRS and MODIS do not share a CSV schema**, and confidence is a letter in one and a
   percentage in the other.
3. **`httpx` logs full request URLs at INFO level** — which would have printed the NASA
   MAP_KEY straight into the console. Third-party HTTP loggers are pinned to WARNING.
4. **Overpass `out tags geom` does not expand relation members.** Every large forest in India
   is mapped as a multipolygon *relation*, so the entire forest land-cover layer came back
   empty until this was switched to `out geom`.
5. **Overpass truncates at the element cap in arbitrary order.** One large query returned
   8000 polygons clustered in one corner and left the rest of the region with zero coverage —
   which looked exactly like "OSM has no data here". Land use is now fetched in small tiles.
6. **`overpass-api.de` returns HTTP 406 without a real `User-Agent`**, and mirrors return 504
   under load. Hence three mirrors with failover, tight timeouts and a disk cache.
7. **Real VIIRS FRP over India is small** — median around 4 MW, 95th percentile around 16 MW.
   An initial 15 MW threshold for "strong" sat above the 90th percentile and meant the
   industrial-fire rules almost never fired.
8. **CARTO's basemap tiles now require an API key, and they fail invisibly.** The request
   returns **HTTP 200 with a perfectly valid PNG** — the PNG is just a grey tile stamped
   "API KEY REQUIRED". No status check, no error handler and no test catches that; it is
   only visible by looking at the rendered map. OpenStreetMap's own tiles need no key, and
   are desaturated in CSS to keep the basemap recessive.
9. **A second `npm run dev` silently serves stale code.** The first server keeps the port,
   the second loses the bind race, and the browser talks to a process running old code —
   which looks exactly like "my edits do nothing". The dev script now checks both ports up
   front and refuses to start with instructions rather than racing.

---

## Future work

Genuinely useful next steps, in rough order of value:

1. **Real labels.** Partner with a state disaster-management authority or pollution control
   board for verified incident reports. This is the single change that would turn the metrics
   from "agreement with a policy" into real accuracy.
2. **A spectral land-cover raster** (ESA WorldCover or Bhuvan) behind the existing
   `LandCoverProvider` interface, replacing the OSM cartographic proxy.
3. **Sentinel-2 / Sentinel-5P confirmation** for high-priority events — visible-band imagery
   and SO₂/NO₂ plumes would corroborate an industrial signature.
4. **PostGIS deployment** using `docs/postgis_schema.sql`, pushing spatial work into the
   database.
5. **Scheduled ingestion** so recurrence history accumulates continuously rather than per query.
6. **Alerting** — webhook/email when a high-priority industrial candidate appears near a
   registered facility.
7. **Calibration** (isotonic/Platt) so the reported confidence is a properly calibrated
   probability rather than a forest vote share.

---

## Credits and licences

- **NASA FIRMS** — Fire Information for Resource Management System, NASA/LANCE EOSDIS.
- **OpenStreetMap** contributors — © OpenStreetMap, ODbL. Queried via public Overpass instances.
- **CARTO** dark basemap tiles.
- **scikit-learn**, **FastAPI**, **React**, **Leaflet**, **pandas**, **NumPy** — open source.

Built for Smart India Hackathon 2026, Problem Statement 26162, by **Team Classy Fires**.

> FIRETRACE provides AI-assisted likelihood classifications derived from satellite thermal
> detections and open geographic data. It is not a confirmed ground-truth fire diagnosis and
> requires human verification before any operational decision.
#
#   s i h h h h h h h h  
 #   S I H _ D E M O  
 
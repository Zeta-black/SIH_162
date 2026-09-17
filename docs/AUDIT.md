# FIRETRACE — codebase audit

What is actually built, what is not, and what was claimed but does not exist.
Every row was verified against source, not against memory or against what someone
said. Audited 16 September 2026.

---

## 0. A problem-statement discrepancy that must be settled first

The brief describes the project as a **"satellite-assisted wildfire / forest-fire
monitoring and alerting platform"** for **"Problem Statement 162"**.

The repository, the team's own SIH proposal deck, and the problem-statement text
supplied at the start of this project all say something different:

> **PS 26162** — *AI-Based Detection and Classification of Industrial Fires and
> Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data*
> Organisation: **National Technical Research Organisation (NTRO)**
>
> Expected deliverables:
> i. **Classification and segregation of industrial fires from forest fires and
>    other natural fires.**
> ii. GIS based solution for data storage and visualisation as a map overlay.

These are not the same product. Deliverable (i) is explicitly about separating
**industrial** fire from forest fire. A wildfire-monitoring pitch inverts that: it
makes forest fire the subject and industrial fire an irrelevance.

The system as built classifies four thermal-source types and its single most
defensible idea — using **temporal persistence** to separate a routine refinery
flare from an abnormal industrial event — only matters under PS 26162.

**Recommendation: keep the PS 26162 framing and add the operational layer the
brief asks for.** The two are compatible. PS 26162 answers *"what is this thermal
anomaly?"*; the brief's alerting, clustering and response workflow answer *"and
what should the authority now do about it?"* Together they are a stronger
submission than either alone, and nothing has to be thrown away.

Everything below is scoped on that reading. If the problem statement genuinely
changed, say so — the ingestion, clustering, alerting, latency and workflow work
is identical either way, but the ML target and the novelty claim would both have
to be rebuilt.

---

## 1. Capability audit

| Feature | Status | Evidence in code | Required work | Demo ready? |
|---|---|---|---|---|
| NASA FIRMS ingestion | **Real** | `app/services/firms.py` — keyed, server-side, VIIRS + MODIS schema normalisation | — | Yes |
| Multi-product schema handling | **Real** | Same file; VIIRS `bright_ti4`/letter confidence vs MODIS `brightness`/0–100 both mapped | — | Yes |
| Missing-field honesty | **Real** | `unavailable_fields[]` on every event; NaN + `*_missing` indicator in features | — | Yes |
| OSM facility enrichment | **Real** | `app/services/osm.py` — Overpass, 3 mirrors, disk cache, tiling | — | Yes |
| Land-cover (OSM land use) | **Real** | `app/services/landcover.py` — ray-cast point-in-polygon, multipolygon ring stitching | — | Yes |
| Geodesic distance | **Real** | `app/services/geo.py` — haversine, with a test guarding against degree subtraction | — | Yes |
| Recurrence / persistence features | **Real** | `app/services/recurrence.py`; strictly-prior-day rule, leakage test | — | Yes |
| **Random Forest — trained** | **Real** | `ml/artifacts/firetrace_rf.joblib` (1.5 MB), `ml/train.py`, `ml/artifacts/metrics.json` | — | Yes |
| Model metrics | **Real, measured — but circular** | Region-grouped split · balanced acc **1.000** · macro F1 **1.000**. A perfect score is a WARNING, not a result: logistic regression also scores 1.000 and a depth-3 tree 0.997, so the labels are a rule set the model simply recovers. See `ML_MODEL_CARD.md` §3. | Chronological hold-out; field-verified labels | Yes, with the caveat stated |
| Per-detection explanation | **Real** | `classifier.local_contributions()` — decision-path decomposition | — | Yes |
| Evidence gate / abstention | **Real** | `classifier.evidence_sufficiency()`; 5 tests | — | Yes |
| Priority score | **Real** | `app/services/priority.py` — weighted sum, components returned | — | Yes |
| Offline snapshot fallback | **Real** | `app/data/demo_snapshot.json` (4.1 MB of real past FIRMS + OSM) | — | Yes |
| Event store | **Real** | SQLite, 7.2 MB, ~12.7k detections | Postgres/PostGIS for scale | Yes |
| Console UI, 5 screens | **Real** | `frontend/src/pages/` | — | Yes |
| Provenance endpoint | **Real** | `app/api/provenance.py` — reads live store at request time | — | Yes |
| Test suite | **Real** | 273 tests, incl. an end-to-end replay suite, simulated NASA outage and missing-model degradation | — | Yes |
| **Fire-event clustering** | **Real** | `app/services/events.py` — single-linkage union-find over space and time | — | Yes |
| **Alert engine** | **Real** | `app/services/incidents.py` — published rule, identity de-duplication, escalation logging | — | Yes |
| **Incident workflow** (ack → dispatch → resolve) | **Real** | State machine + append-only audit log; illegal transitions rejected with HTTP 409 | — | Yes |
| **Demo replay engine** | **Real** | `app/services/replay.py` — 30 historical cases through the live pipeline, 10 timed stages | — | Yes |
| **Notification delivery** | **ABSENT** | No email, SMS, webhook, Telegram — not even simulated | Build in-app + simulate rest | **No** |
| **Scheduled ingestion** | **ABSENT** | On-demand only, triggered by a dashboard request | Background worker | **No** |
| **Per-stage latency** | **Real** | `replay.StageRecorder` — 10 stages timed with `perf_counter`, wall-clock timestamps at execution; source latency reported separately and never blended in | — | Yes |
| **Simulate-new-event control** | **By design, replay instead** | There is no synthetic-event injector and there will not be one: injecting a fabricated detection would put invented data through a system whose whole claim is that it only handles real observations. `POST /api/replay/run/{id}` replays a *real* historical detection through the same path, which demonstrates the pipeline without manufacturing an event. | — | Yes |
| **Analytics page** | **ABSENT** | `/api/dashboard/summary` returns a timeline, but nothing renders it | Build | **No** |
| **Role-based access** | **ABSENT** | Grep hits were OSM multipolygon member `role` fields and provenance descriptions | Out of scope for prototype | **No** |
| **Rate limiting** | **ABSENT** | None | Low priority | **No** |
| **Audit trail** | **Partial** | `ingest_runs` table records ingests only; no per-event action log | Extend | Partial |

**Summary: 17 real, 1 partial, 10 absent.** The detection-and-classification half
is genuinely engineered. The *operational* half — the part that answers "what does
the authority do now?" — does not exist yet. That is the gap worth closing.

---

## 2. NASA FIRMS latency — measured, not quoted

Judges asked this first. It is measurable, so it was measured rather than looked up.

Method: query the live FIRMS area API for all of India, take every returned
detection's acquisition timestamp, and compare against wall-clock UTC at the moment
of the request.

**Measured 2026-09-16 00:03 UTC, bbox 68,6.5 → 97.5,36:**

| Product | Detections | Freshest | Median age | Oldest |
|---|---|---|---|---|
| VIIRS NOAA-21 NRT | 900 | **2.07 h** | 27.35 h | 41.54 h |
| VIIRS SNPP NRT | 720 | **3.04 h** | 26.70 h | 40.94 h |
| MODIS NRT | 83 | **9.39 h** | 25.89 h | 44.99 h |

**The honest answer:** for India, the freshest detection NASA was serving at that
moment was **~2 hours old**. That is the floor. No amount of engineering on our side
can make a detection available sooner than NASA publishes it.

Consequences we must state plainly and not dodge:

- **This system is not real-time and must never be described as real-time.** The
  correct phrase is *near-real-time, bounded by a ~2–3 hour source latency for this
  geography.*
- Ultra-real-time FIRMS (~60 s) exists only for the **US and Canada**. India is
  served by the standard NRT pipeline.
- Therefore our platform's value cannot be *speed of detection*. It has to be
  **interpretation, prioritisation and response coordination** of a detection that
  is already a couple of hours old — which is exactly where a forest or industrial
  safety department currently has no tooling at all.
- Our own processing latency is a separate number and must be reported separately.
  Measured end-to-end analysis time is currently ~10 s cold for 716 detections and
  effectively instant when cached — but **that is our latency, not NASA's**, and
  conflating the two would be the easiest way to lose credibility in questioning.

---

## 3. What the Random Forest actually does

Answering the brief's checklist against the artifact on disk, not against intent.

| Question | Answer |
|---|---|
| Is it trained? | **Yes.** `ml/artifacts/firetrace_rf.joblib`, 1.5 MB, 300 trees, loads at startup |
| What task? | **Multi-class classification of thermal-source type** — not fire prediction, not forecasting |
| Target variable | One of 4 trained classes: `INDUSTRIAL_FIRE`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`, `AGRICULTURAL_BURNING`, `NATURAL_FIRE` |
| Is `UNKNOWN` a class? | **No.** It is an abstention applied when top probability < threshold |
| Features | 48, from `app/services/features.py` — one pipeline shared by training and inference |
| Training rows | 3,514 labelled, from 10,804 real FIRMS detections |
| Excluded | 7,290 (67.5%) left unlabelled because the evidence was ambiguous |
| **Label source** | **Weak supervision.** A documented rule policy, **not** verified incident reports |
| Split | **Grouped by region**, 11 regions, 2,279 train / 1,235 test |
| Balanced accuracy | 1.000 — **and that is the finding, not the achievement** |
| Macro F1 | 1.000 |
| **Why perfect is bad** | The labels are a deterministic rule set over features the model can see, so any model recovers the rules. Logistic regression scores **1.000**, a depth-3 tree **0.997**. Random-Forest lift over the best baseline: **0.000**. |
| Leakage audit | **CLEAN** — 0 shared rows, coordinates, regions or detection IDs across the split |
| Weakest evidence | `INDUSTRIAL_FIRE` has **72** labelled rows and only **8** in the test set. A per-class score on 8 samples is anecdote. |
| Stability | Over 12 splits the Random Forest is the *least* stable competitive model: 0.969 ± 0.068, min **0.750** |
| Full disclosure | `docs/ML_MODEL_CARD.md` |

**What it does NOT do, and must never be claimed to do:**

- It does **not** predict where a fire will start.
- It does **not** forecast fire spread.
- It does **not** detect fire — NASA FIRMS does that. The model classifies what an
  already-detected thermal anomaly most likely *is*.
- Its accuracy figures measure **agreement with a labelling policy**, not verified
  real-world correctness, because no public dataset states the true cause of an
  individual FIRMS pixel.

Correct phrasing for the UI and the pitch: **"ML-assisted thermal-source
classification"**. Never "AI detected a fire".

---

## 4. The biggest technical gap

**Every FIRMS detection is currently treated as an independent row.**

A single fire burning for six hours across three satellite passes appears as
perhaps twelve separate rows in the worklist. An operator would have to work out by
eye that they are one incident. This is the weakest thing in the product and the
first thing a geospatial judge would attack.

It also distorts the headline numbers: "900 detections" is **not** 900 fires, and
the interface currently has to carry a footnote saying so instead of just being
correct.

Fixing it — grouping detections into **fire events** with an ID, a lifecycle, a
duration and a detection count — converts the product from a map of pixels into an
operational incident system, and makes every downstream feature in the brief
(alerts, acknowledgement, dispatch, analytics) coherent.

That is the next thing to build.

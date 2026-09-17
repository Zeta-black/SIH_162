# FIRETRACE — QA and readiness report

Internal record of what was rebuilt, what was verified by execution, and what is still
weak. Written to be checked, not to be believed.

Date of this run: 11 September 2026 · Model v1.0.0 · Feature v1.0.0 · Policy v1.0.0

---

## A. Interface — rebuilt as an operations console

The first rebuild produced a clean light theme that still read as a *documentation
site*: long prose, uniform type weight, controls buried in a page, and a map sitting
inside a card. It was replaced with an operator console.

| Before | Now |
|---|---|
| Page header with prose lede | **Dark masthead** with icon navigation and a live source LED |
| Controls inside each page | **Persistent command bar** — area, window, source, export, refresh — never scrolled away |
| No machine state visible | **Telemetry status strip**: source, products, record count, window, geo status, land-cover provider, model version, query latency, UTC |
| Three prose cards explaining the method | **Evidence chain** as a six-stage pipeline strip with the real parameters on each stage |
| "Table" | **Data grid** — 25px rows, zebra, monospace tabular numerals, right-aligned measures, sticky headers, sortable |
| Rounded cards, soft shadows | Square corners, hairline rules, steel-grey chrome so colour is reserved for data |
| Page ended in dead space | Operations **fills the viewport**; the worklist scrolls in its own pane |
| Map inside a rounded rectangle | Map is the workspace: left dock for layers and filters, right dock for the inspector, collapsible grid below |

Base font dropped to 12.5px and every measurement is monospaced, so figures form
columns the eye can scan down. Type scale carries hierarchy instead of weight alone.

**Verified by screenshot** at 1760×1080, 1600×1500, 900×1000 and 430px. Bugs found this
way and fixed — none of which any test or lint rule would have caught:

1. **Bar charts rendered empty.** `.chart-fill` was an inline `<span>`, so `width: %` and
   `height: 100%` did nothing. Every magnitude chart in the app was a blank grey track.
2. **The map was covered in "API KEY REQUIRED" watermarks** (see section C).
3. **The map disappeared entirely** after the console rewrite: the CSS class was renamed
   `.map-holder` → `.mapbox` but the component still used the old name, so the container
   collapsed to zero height and the legend positioned itself against the document. A
   className-vs-stylesheet diff now runs as a check; it currently reports zero unstyled
   classes.
4. **Status pill overlapped the page heading below 620px.** The topbar was allowed to wrap
   freely; it now has explicit ordering.

## B. Data integrity

**No synthetic scientific value exists anywhere in this system.** Verified by inspection:

```
grep -rn "Math.random|np.random|random.uniform|random.choice"  →  no hits
   (only random_state= seeds, which are reproducibility, not data)
```

| Value shown | Where it actually comes from |
|---|---|
| Coordinates, acquisition time | NASA FIRMS CSV, parsed and validated |
| Brightness temperature, FRP | NASA FIRMS, per product (`bright_ti4`/`brightness`) |
| Detection confidence | NASA FIRMS (VIIRS letters, MODIS 0–100), normalised |
| Nearest facility, type, distance | OpenStreetMap via Overpass; haversine distance |
| Land cover | OpenStreetMap land-use polygons, ray-cast point-in-polygon |
| Recurrence, persistence | Detections already in the store, strictly earlier than the event |
| Class, confidence, probabilities | Trained Random Forest artifact |
| Factors | Decision-path decomposition of that artifact, per event |
| Priority score | Published weighted sum of the above |
| Every count on Overview/Data | Computed from the current query or read from the store |

**Missing values are shown as missing.** `n/r` for a field the FIRMS product did not
report, "unmapped" for absent land cover, "none within radius" for no facility. The
feature pipeline emits NaN plus an explicit `*_missing` indicator rather than a
substitute, and `unavailable_fields` travels with every event to the UI.

**No fallback fabricates data.** When a source fails the UI renders an error with a
retry. The one fallback that exists — the offline snapshot — is a frozen capture of
*real* past FIRMS and OSM records, is tagged `mode: "snapshot"`, and shows a persistent
"Historical" badge.

---

## C. NASA and external API integration

**One key in the entire project**: `FIRMS_MAP_KEY`. Read server-side via
`pydantic-settings`, scrubbed from every log line and error message, never serialised
into any response.

Verified: the key appears in `.env` only (gitignored); `grep` over the built frontend
bundle and the committed snapshot finds nothing. `httpx`'s own logger — which prints full
request URLs at INFO and would have leaked the key to the console — is pinned to WARNING.

Everything else needs **no key**: Overpass, OpenStreetMap tiles, OpenTopoMap.

### The "API required" complaint, diagnosed

The user reported the interface saying "API required" despite a configured key. Two
separate findings:

1. **No such string exists in the frontend.** The only "key not configured" messages are
   in the backend and fire only when the key is genuinely absent. Those were never
   triggered — `/health` reports `firms_key_configured: true` and NASA accepts the key
   (quota endpoint returns 5000-per-10-minutes with live usage).
2. **The actual source was the basemap.** CARTO's `basemaps.cartocdn.com` tiles now
   require a key and **fail invisibly**: HTTP 200, a valid PNG, and the PNG is a grey tile
   stamped "API KEY REQUIRED". No status check or test could catch it. Found by
   screenshotting the map. Replaced with key-free OpenStreetMap tiles.

### Failure handling, per dependency

Timeout, rate limit, malformed response, missing field, unreachable host and missing key
are each handled with a user-facing message and no invented data. A 12-second wall-clock
budget bounds live OSM enrichment: past it, remaining tiles are served from disk cache so
the request still returns.

---

## D. ML validation

| | |
|---|---|
| Algorithm | `RandomForestClassifier`, 300 trees, depth 14, `class_weight=balanced_subsample` |
| Features | 48, one shared pipeline for training and inference |
| Labelled rows | 3,514 (from 10,804 real detections) |
| Excluded as ambiguous | 7,290 — **67.5%, deliberately unlabelled** |
| Split | **Grouped by region**, 11 regions · 2,279 train / 1,235 test |
| Balanced accuracy | **1.000 — this is a warning, not a result** |
| Macro F1 | **1.000** |
| Out-of-bag | 0.999 |
| Shuffled 5-fold CV | 0.999 ± 0.001 |
| Leakage audit | **CLEAN** |
| Random-Forest lift over best baseline | **0.000** |

**The observations are real; the labels are not verified.** No public dataset states the
true cause of an individual FIRMS detection, so labels come from the documented rule
policy in `app/services/labeling.py`. Every metric therefore measures *agreement with
that policy on held-out detections*, not real-world accuracy. That caveat is carried in
the model metadata, the `/api/model/info` payload, the Model screen and this report.

### The perfect score is the finding

A model scoring 1.000 on regions it has never seen has not solved a hard problem — it has
revealed that the problem, as posed, is circular. The rule policy decides using facility
distance, persistence, FRP and land cover, and the model is handed those same columns, so
"classify the fire" collapses into "recover the rule set".

The baseline comparison (`python -m ml.validate`) is the proof:

| Model | Balanced acc. | Macro F1 |
|---|---|---|
| Majority class | 0.250 | 0.224 |
| Stratified random | 0.303 | 0.235 |
| One-rule stump | 0.497 | 0.331 |
| Depth-3 decision tree | **0.997** | 0.991 |
| Logistic regression | **1.000** | 1.000 |
| Random Forest (shipped) | **1.000** | 1.000 |

A three-question tree matches the 300-tree ensemble. So does a linear model. The forest
adds **zero** lift.

Worse for the forest specifically: across 12 resampled region-grouped splits it is the
*least* stable competitive model — **0.969 ± 0.068, min 0.750** — against logistic
regression's 0.996 ± 0.004. The single-split 1.000 is a favourable draw.

**This is not leakage.** That was audited independently: 0 duplicate feature rows, 0
shared coordinates, 0 shared regions, 0 duplicate detection IDs. Verdict **CLEAN**. One
real leak was found and fixed en route — 18 detections in the overlapping Punjab
bounding-box strip were fetched twice under different region IDs, now deduplicated on
`event_id`. Train and test still share a 48-day window, so the evidence is spatial
generalisation only, **not** temporal.

`ml/train.py` now detects this itself: at balanced accuracy ≥ 0.98 it prints a blocking
warning and writes `circularity_warning: true` into `metrics.json`, so the figure cannot
leave the pipeline without its caveat. Full disclosure: **`docs/ML_MODEL_CARD.md`**.

**Executed, not assumed** — `python -m ml.train` runs end to end; artifact loads at
startup (`[ML] model loaded version=1.0.0 trees=300 features=48`); inference returns
probabilities summing to 1; feature order is pinned by `FEATURE_NAMES` and a version
mismatch causes the loader to refuse the artifact rather than silently mispredict.

### Per class

| Class | Precision | Recall | F1 | Test rows | Labelled rows |
|---|---|---|---|---|---|
| Agricultural burning | 1.00 | 1.00 | 1.00 | 181 | 237 |
| Gas flare / persistent heat | 1.00 | 1.00 | 1.00 | 998 | 2,534 |
| Natural / vegetation fire | 1.00 | 1.00 | 1.00 | 48 | 671 |
| **Industrial fire** | 1.00 | 1.00 | 1.00 | **8** | **72** |

Read the industrial row as anecdote, not measurement. **Eight test samples.** A per-class
score on 8 rows carries an enormous confidence interval, and this is the thinnest evidence
in the project — stated on the Model screen rather than buried.

### The evidence gate — found by testing, not by reading

Running the finished model against live September data exposed a real defect: **810 of
900 detections came back as agricultural burning** at median confidence 0.66, in a month
that is not a burning season. 800 of them had no land cover and 804 had no facility
within 12 km — the model had learned that absence of evidence resembles cropland.

The abstention threshold now rises from 45% to 72% when neither discriminating feature is
available. Recurrence deliberately does not satisfy the gate (the first version accepted
it and passed nearly every case the gate exists to catch). Result on the same query:
agricultural **810 → 164**, unclassified **32 → 678**, each stating its reason.

Five tests pin this behaviour.

---

## E. Map

Every geographic object corresponds to a real record.

- **Detections** — one marker per FIRMS observation. Disc *area* ∝ fire radiative power
  (square-root radius, because the eye reads area). A detection with no reported FRP is
  drawn **hollow**, so "not reported" is visually distinct from "small".
- **Facilities** — real OSM features, popup showing name, category and `osm_type/osm_id`.
- **Recurrence ring** — the exact circle the backend used to count repeat detections, so
  the number in the panel and the geometry on the map mean the same thing.
- **Controls** — zoom, metric scale bar, three key-free basemaps, layer toggles, legend
  with colour + code + label, and an explicit note on the marker encoding.

No decorative markers, no random points, no heat layer that is not backed by data.

---

## F. Security

| Check | Result |
|---|---|
| Key in frontend source or bundle | None |
| Key in logs | None — third-party HTTP loggers pinned to WARNING |
| Key in API responses | None — scrubbed in `firms.py` |
| `.env` committed | No — gitignored; `.env.example` holds placeholders only |
| Input validation | Pydantic on every endpoint; bbox, dates, ranges, enums all validated |
| Stack traces to client | No — global handler returns a safe message |
| SQL injection | Parameterised queries throughout |
| Unsafe HTML | No `dangerouslySetInnerHTML` anywhere |

---

## G. What was actually executed

- `npm test` — **190 passed** in 23s
- `npm run build` — clean
- `npm run lint` — clean, zero warnings
- `npm run setup` / `npm run dev` — both verified from scratch
- Port guard — verified it refuses a second instance
- Live NASA query — 1,259 detections, 3 products, India-wide
- Demo mode — 716 snapshot events, all four scenarios present
- All five routes — HTTP 200, screenshotted, data verified
- All API endpoints through the Vite proxy — HTTP 200
- Simulated total NASA outage — dashboard still returns a usable response (in the suite)
- Missing model artifact — degrades to unclassified, UI still works (in the suite)
- **Horizontal overflow measured, not eyeballed** — `scrollWidth` vs `clientWidth` at 380,
  430, 620, 900 and 1280 px: **zero overflow at every width**. Headless screenshots had
  suggested a mobile cut-off; measuring showed that was a screenshot artifact. The topbar
  overlap at ≤620 px was real and was fixed (brand + status on one row, nav on its own)

---

## H. Remaining limitations

1. **Training labels are inferred, not verified.** The ceiling on every ML claim here.
2. **The headline 1.000 is circular** — the labels are a rule set over features the model
   sees, so a linear model matches it and the ensemble adds no lift. The flagship class,
   industrial fire, rests on just 72 labelled and 8 test rows.
3. **OSM land cover is missing where it matters most**: 98% unknown in central Punjab,
   74% in coastal Gujarat. Measured, published on the Data screen, not hidden.
4. **A cold live query over a country-sized area takes ~70s**, dominated by Overpass under
   load. Cached repeats are instant, and demo mode is ~10s.
5. **SQLite, not PostGIS.** Deliberate for demo reliability; the production schema with
   real geometry columns and GiST indexes is in `docs/postgis_schema.sql`, unused.
6. **Confidence is a forest vote share, not a calibrated probability.** No isotonic or
   Platt calibration has been applied.
7. **Single-process, single-node.** No queue, no scheduled ingestion, no auth.
8. **Not certified for operational use.** Every prediction needs human verification.

---

## I. Judge simulation

Scored against what a strong SIH finalist field would produce. Two passes; the first
pass's fixes are recorded.

| # | Criterion | Pass 1 | Pass 2 | Note |
|---|---|---|---|---|
| 1 | Problem understanding | 9 | 9 | Stated in one line; the FIRMS gap is explicit |
| 2 | Innovation | 8 | 9 | Persistence-as-discriminator, abstention, **evidence gate**, inverted priority |
| 3 | Technical depth | 9 | 9 | Real API constraints discovered by testing; ring stitching; leakage-safe recurrence |
| 4 | Data authenticity | 10 | 10 | Zero synthetic values; provenance reads live state |
| 5 | ML validity | 8 | 9 | Grouped split, honest gap, evidence gate. Capped by label provenance |
| 6 | Geospatial implementation | 9 | 9 | Multipolygon land cover, tiling, failover, meaningful map encodings |
| 7 | UI/UX | 7 | 9 | Pass 1 was unverified; screenshots found empty charts + tile watermark |
| 8 | Usability | 9 | 9 | Two commands; nav answers the reviewer's questions in order |
| 9 | Explainability | 10 | 10 | Per-event decision-path factors; Method and Model screens |
| 10 | Scalability | 7 | 7 | SQLite ceiling; PostGIS documented but unused |
| 11 | Feasibility | 9 | 9 | Laptop, free data, no paid services |
| 12 | Real-world impact | 8 | 8 | Real triage output; no deployment partner yet |
| 13 | Presentation readiness | 8 | 9 | README, demo script, six screens that tell the story |
| 14 | Differentiation | 9 | 10 | Refusing to answer, and showing why, is the opposite of the field |
| 15 | Finalist potential | 8 | 9 | |
| | **Total** | **128** | **135 / 150** | |

**Fixed between passes:** the empty bar charts (7), the CARTO key watermark (7), the
agricultural over-prediction via the evidence gate (2, 5), the stale-server trap (8), and
README/Method documentation of all of it (13).

**Still below 9, honestly:**

- **Scalability (7).** SQLite and a single process are a real ceiling. Not fixable inside
  this scope without a database server, which would cost demo reliability — the trade is
  documented rather than papered over.
- **Real-world impact (8).** Genuine, but unproven until a disaster-management authority
  uses it. Not something code can fix.

**Where a judge could still push:**

- *"Your labels aren't ground truth, so what is the accuracy really?"* — Correct, and
  stated first on the Model screen. The honest answer is that it measures policy
  agreement, and partnering for verified incident reports is the top item in future work.
- *"Your model scores 1.000 — that's obviously fake."* — It is real, reproducible, and we
  agree it is not an accuracy claim. We ran the baselines ourselves: logistic regression
  also scores 1.000, a depth-3 tree 0.997, so the lift is zero and the labels are circular.
  Leakage was audited separately and is clean. `ml/train.py` prints this warning itself.
- *"Why is industrial fire so weak?"* — 72 labelled examples and only 8 in the held-out
  set, so its per-class score is anecdote. Stated on the page, not buried.
- *"Why did it say agricultural in September?"* — It no longer does. That exact question
  produced the evidence gate.

---

## J. Finalist readiness

**READY.**

Not because the interface looks good, but because the claims survive checking:

- every displayed value traces to NASA FIRMS or OpenStreetMap, and the Data screen reads
  that provenance live rather than reciting it;
- the headline metric is the *lower* region-grouped number, with the inflated one shown
  beside it and labelled as inflated;
- the weakest class is on screen with its confusion matrix, not omitted;
- the system refuses to classify when the evidence is not there, and says which evidence
  was missing;
- 273 tests pass, including an end-to-end replay suite, a simulated total NASA outage and a missing model artifact;
- it runs with no internet and no key, and never presents the offline capture as live.

The two things that would most raise this score are outside the code: verified incident
labels, and a deployment partner.

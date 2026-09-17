# FIRETRACE — answers to technical questioning

Every number here was measured on this system, on the date shown. Where we do not
have something, that is stated rather than covered. A judge who catches one
exaggeration will discount everything else, so nothing here is rounded in our
favour.

Measured 16 September 2026 · Model v1.0.0 · 273 tests passing · smoke test 21/21

---

## The 30-second answer

> NASA FIRMS tells you **where** a satellite saw heat. It does not tell you **what**
> is burning, and it gives you loose pixels rather than incidents.
>
> FIRETRACE groups those pixels into fire events, works out what each one most
> likely is — industrial fire, routine flare, crop burning, vegetation fire —
> shows the evidence behind that call, and ranks them so a control room knows
> which one to look at first.
>
> NASA detects. We interpret, group, prioritise and explain. A human verifies and
> responds.

---

## Data and latency

### 1. What is the latency of NASA FIRMS?

**Measured, not quoted.** We queried the live API for all of India and compared
every detection's acquisition time against wall-clock UTC.

| Product | Freshest detection | Median age |
|---|---|---|
| VIIRS NOAA-21 NRT | **2.07 h** | 27.4 h |
| VIIRS SNPP NRT | **3.04 h** | 26.7 h |
| MODIS NRT | **9.39 h** | 25.9 h |

For India the floor is roughly **2–3 hours** from satellite overpass to API
availability. Ultra-real-time FIRMS (~60 s) exists only for the **US and Canada**;
India is served by the standard NRT pipeline.

**Therefore this system is not real-time and we never call it real-time.** The
correct description is *near-real-time, bounded by a 2–3 hour source latency*.

### 2. Then what is *your* latency?

Separate number, separately measured, and we are careful never to conflate the two.

| Stage | Measured |
|---|---|
| Fetch from FIRMS (3 products, all-India) | ~6 s |
| Enrich 716 detections with OSM + history | 1.1 s |
| Classify all 716 (batch) | 0.19 s |
| Cluster into fire events | 0.16 s |
| Explain one detection | 0.11 s |
| **Full cold analysis** | **~10 s** |
| Cached repeat | instant |

If a detection were handed to us the moment NASA published it, our contribution to
the delay would be **seconds**. The hours are NASA's, and no engineering on our
side can remove them.

### 3. Is the dashboard data real-time or imported?

Neither word is accurate, so we use three explicit modes and the status strip
always says which is active:

- **Live** — queried from NASA FIRMS now, subject to the 2–3 h source latency.
- **Historical** — a committed snapshot of *real past* FIRMS and OSM records, used
  when the network or the API is unavailable. Labelled "Historical" in the
  masthead and on every affected screen.
- **Auto** — live, falling back to historical on failure, and it tells you when it
  falls back.

The snapshot is real observations, frozen. It is not synthetic and it is never
presented as live.

### 4. What if NASA FIRMS goes down?

Tested — the suite includes a simulated total outage and asserts the dashboard
still returns a usable response.

- One product fails → the others are still used, and the response says which were unavailable.
- All of FIRMS fails → automatic fallback to the historical snapshot, with the reason shown.
- Overpass (OSM) fails → three mirrors, then disk cache, then stored facilities.
- Land-use unreachable → land cover reported `unknown`, never guessed.
- Model artifact missing → every detection reported Unclassified; the interface keeps working.

**No failure path substitutes generated data.** A failed request produces a visible
error with a retry.

---

## The machine learning

### 5. Has the Random Forest actually been trained?

Yes. `backend/ml/artifacts/firetrace_rf.joblib`, 1.2 MB, 300 trees, 48 features.
It loads at startup and the log line proves it. The training script, the dataset
and the metrics file are all in the repository.

### 6. What exactly does it predict?

**The likely source type of a thermal anomaly that NASA has already detected.**
Four trained classes:

`INDUSTRIAL_FIRE` · `GAS_FLARE_OR_INDUSTRIAL_HEAT` · `AGRICULTURAL_BURNING` · `NATURAL_FIRE`

It does **not** predict where a fire will start, does **not** forecast spread, and
does **not** detect fire. NASA detects; the model classifies.

### 7. What are the features?

48, from one pipeline shared by training and inference so the two cannot drift.
Grouped:

- **Thermal** — brightness temperature, secondary channel, *channel separation*, FRP, log FRP, FIRMS confidence.
- **Spatial** — lat/lon, geodesic distance to nearest industrial facility, proximity score, on-site flag, facility category, high-heat-process flag.
- **Land cover** — one-hot over eight categories.
- **Temporal** — recurrence count, distinct days, detections in last 7 days, persistence ratio, same-pass co-detection density.
- **Seasonality** — day-of-year on a circle.
- **Missingness** — explicit `*_missing` indicators.

Channel separation is worth mentioning under questioning: a small very hot source
(a flare) separates the two VIIRS channels far more than a broad cooler burn front,
so it discriminates better than either channel alone.

### 8. Where did your labels come from? What is your accuracy?

**This is the honest weak point and we lead with it rather than hide it.**

There is no public dataset stating the true cause of an individual FIRMS pixel. So
labels come from a **documented weak-supervision rule policy**, not from verified
incident reports.

| Metric | Value |
|---|---|
| Balanced accuracy | **1.000 — and that is our finding, not our boast** |
| Macro F1 | **1.000** |
| Split | **Grouped by region**, 11 regions, 2,279 train / 1,235 test |
| Labelled rows | 3,514 from 10,804 real detections |
| Deliberately excluded as ambiguous | 7,290 (67.5%) |
| Random-Forest lift over best baseline | **0.000** |
| Leakage audit | **CLEAN** |

**These numbers measure agreement with the labelling policy on held-out
detections — not verified real-world accuracy.** That caveat is on the Model screen,
in the API payload and in the model metadata.

### 9. "You score 1.000. That is obviously fake."

It is real and reproducible — and you are right that it is not an accuracy claim. We
reached the same conclusion before you did, which is why `ml/train.py` prints a blocking
warning at balanced accuracy ≥ 0.98 and stamps `circularity_warning: true` into
`metrics.json`.

**The explanation is label circularity.** Our labels come from a deterministic rule
policy that decides using facility distance, persistence, FRP and land cover. The model
is handed those same columns. So the task is not "classify the fire", it is "recover the
rule set" — and that is easy.

We proved it by trying to beat ourselves with trivial models:

| Model | Balanced acc. | Macro F1 |
|---|---|---|
| Majority class | 0.250 | 0.224 |
| Stratified random | 0.303 | 0.235 |
| One-rule stump | 0.497 | 0.331 |
| **Depth-3 decision tree** | **0.997** | 0.991 |
| **Logistic regression** | **1.000** | 1.000 |
| Random Forest (shipped) | 1.000 | 1.000 |

A tree you could read aloud in three questions scores 0.997. A linear model ties us
exactly. **Our lift over the best baseline is 0.000.**

And across 12 resampled splits our forest is the *least* stable of the three:
0.969 ± 0.068 with a worst split of **0.750**, against logistic regression's
0.996 ± 0.004. The single-split 1.000 is a favourable draw, not a property.

### 10. "Then it is leaking."

Audited independently, and no:

| Check | Result |
|---|---|
| Identical feature rows across the split | 0 |
| Shared coordinates | 0 |
| Shared regions | 0 |
| Duplicate detection IDs | 0 |
| **Verdict** | **CLEAN** |

One real leak *was* found and fixed during that audit: our region bounding boxes overlap
on purpose, so 18 Punjab detections were fetched twice under different region IDs and
could land on both sides. Deduplicated on `event_id`; every figure above is post-fix.

The limitation we *do* accept: train and test share a 48-day window. Our split is
spatial, not temporal, so we claim generalisation to unseen **places**, not to unseen
**time**. A chronological hold-out is the next step.

### 11. "So why ship a model at all?"

Two reasons, neither of which is accuracy.

1. **It emits an uncalibrated RF vote score; rules emit only a verdict.** Our evidence gate abstains
   below 0.45, and below 0.72 when no facility *and* no land-cover polygon supports the
   point. A rule set cannot say "0.63 confident", so it cannot abstain in a principled way.
2. **It covers the 67.5% of detections the policy refuses to label.** On all 7,290 of
   those rows have a mean top RF vote score of **0.660** — the model is unsure exactly
   where the policy was unsure, rather than manufacturing certainty — and the gate
   withholds a verdict on **1,651 (22.6%)** of them. There is no ground truth there, so
   that is a statement about behaviour, not correctness.

Full disclosure, including every limitation: **`docs/ML_MODEL_CARD.md`**.

### 12. Per-class performance — and the number to distrust

| Class | Precision | Recall | F1 | Test rows | Labelled rows |
|---|---|---|---|---|---|
| Agricultural burning | 1.00 | 1.00 | 1.00 | 181 | 237 |
| Gas flare / persistent heat | 1.00 | 1.00 | 1.00 | 998 | 2,534 |
| Natural / vegetation fire | 1.00 | 1.00 | 1.00 | 48 | 671 |
| **Industrial fire** | 1.00 | 1.00 | 1.00 | **8** | **72** |

**Distrust the industrial row.** Eight test samples. That is the flagship class of the
problem statement and it is the thinnest evidence we have — a per-class score on 8 rows
is anecdote, not measurement. More labelled data is the fix, and partnering for verified
incident reports is the top item in our future work.

### 13. Why Random Forest and not deep learning?

- The input is ~48 tabular features, not imagery. Trees are the right family.
- 3,514 labelled rows would overfit almost any deep model.
- It is **inspectable**: we decompose each tree's decision path to explain a single
  prediction. Getting equivalent per-sample attribution from a neural net needs
  additional machinery we would then also have to defend.
- It trains in seconds on a laptop, which keeps the whole pipeline reproducible.

### 14. How do you reduce false alarms?

Four mechanisms, all implemented:

1. **Abstention.** Below 45% top probability the system reports *Unclassified*
   rather than asserting a weak guess.
2. **The evidence gate.** That bar rises to **72%** when the discriminating
   evidence is absent — no mapped facility within the search radius *and* no
   land-use polygon. Found by measuring: the ungated model called **810 of 900**
   September detections "agricultural burning" at median RF vote score 0.66, of which
   800 had no land cover at all. It had learned that absence of evidence resembles
   cropland. With the gate: 810 → 164.
3. **Event clustering.** A single uncorroborated pixel is visibly marked as such;
   an event confirmed across multiple passes and platforms is not the same thing.
4. **Labelling refusal.** 67% of detections were left unlabelled during training
   rather than forced into a class.

### 15. How do you cluster detections, and why not DBSCAN?

Two detections join the same fire event if they are within **1.5 km AND 12 hours**
of each other, and membership is **transitive** — so a creeping fire front stays one
event even when its ends are far apart. Single-linkage, implemented with union-find
over the spatial index. Measured cost: **161 ms for 716 detections**.

**Not DBSCAN** because its `eps` is a single distance in one metric space, and this
problem has two incommensurable axes — kilometres and hours. Combining them requires
inventing a km-per-hour conversion with no physical meaning. Two explicit thresholds
are more defensible and easier to state out loud.

Thresholds are justified by the instrument: a VIIRS pixel is 375 m and MODIS 1 km,
so adjacent pixels of one front sit well inside 1.5 km. Twelve hours keeps
consecutive overpasses together without merging fires that recur days apart — which
would destroy the persistence signal the model depends on.

**Measured effect on live all-India data: 900 detections → 372 fire events (2.42×),
largest event 36 detections over 24.3 hours spanning 3.0 km.**

### 16. How do you handle duplicate detections?

Each detection gets a deterministic ID hashed from position, acquisition time and
product. Re-ingesting an overlapping window is idempotent — `INSERT OR IGNORE` on
that key. The same applies across products, so the same fire seen by two satellites
produces two genuine records, not one duplicate, and clustering then groups them.

---

## The product

### 17. Who is the end user?

**Primary:** a control-room operator in a forest department, an industrial-safety
cell, or a district disaster-management authority — someone who must decide which of
today's hundreds of thermal detections deserves a phone call.

**Secondary:** field verification teams, and researchers studying persistent
thermal sources.

We did **not** build separate interfaces per role. One console, with the
information ordered the way an operator works: what is happening → which incidents
→ where → why.

### 18. Why not just use NASA FIRMS directly?

Because FIRMS answers one question and a control room has four.

| FIRMS gives you | FIRETRACE adds |
|---|---|
| Hot pixels | **Fire events** — 900 pixels resolved to 372 incidents |
| No cause | **Likely source** with confidence and per-event reasoning |
| No ranking | **Transparent priority score** with every component published |
| No context | Nearest industrial facility, land cover, detection history |
| No memory | Persistence — has this spot burned before, and how often |
| Everything asserted | **Abstention** — it says when it does not know, and why |

A forest officer opening FIRMS sees a map of dots. Opening FIRETRACE they see a
ranked queue of incidents with the evidence attached.

### 19. Does this require physical presence or hardware?

**No, for detection and interpretation.** Satellite → API → our server → analysis →
operator screen. No ground sensors, no cameras, no towers.

**Yes, for verification and response.** A satellite cannot confirm what is burning
or put it out. The architecture separates these deliberately:

```
DETECTION      satellite + our platform     no humans on site
VERIFICATION   field team or local staff    humans required
RESPONSE       firefighting                 humans required
```

We never claim the platform replaces ground verification. It tells you *where to
send people first*.

### 20. What is your novelty?

Not "NASA FIRMS plus a dashboard". Specifically:

1. **Persistence as the discriminator.** A refinery flare and an industrial
   accident sit on the same plant and look nearly identical in one frame. What
   separates them is whether that pixel burns on most days or only this once. That
   makes detection *history* a first-class model input, not an afterthought.
2. **Per-event explanation from decision-path decomposition** — not global feature
   importance, which answers a different question.
3. **The evidence gate** — the abstention threshold rises when the discriminating
   features are missing. Found by measuring a real failure, not designed in advance.
4. **Spatio-temporal event clustering** with thresholds justified by pixel geometry.
5. **Honest metric reporting** — the region-grouped number as the headline with the
   inflated ones shown beside it and labelled inflated.

### 21. How does it scale from one forest to a country?

Already running national-scale: the default area is all of India, and a live query
returns ~900–1,300 detections across three products.

What is engineered for scale today:
- FIRMS queries are per-bounding-box; adding regions is adding boxes.
- OSM context is tiled, disk-cached and time-budgeted, so a slow Overpass degrades
  latency rather than breaking the request.
- Analysis results cached 20 minutes.
- Classification is batched — 716 detections in 0.19 s.

What would have to change for production, stated honestly:
- **SQLite → PostgreSQL + PostGIS.** The schema is written (`docs/postgis_schema.sql`)
  with real geometry columns and GiST indexes. It is not wired up, because a
  required database server is the most likely thing to break a live demo.
- **Scheduled ingestion worker** instead of on-demand. Not built yet.
- Horizontal scaling of the analysis service behind a queue.

### 22. What is your security posture?

- **One secret in the entire project**: the NASA FIRMS MAP_KEY. Read server-side
  via environment variable, never sent to the browser, scrubbed from every log and
  error message.
- Verified: `grep` over the built frontend bundle and the committed snapshot finds
  nothing. `httpx`'s own logger — which prints full request URLs at INFO and *would*
  have leaked it — is pinned to WARNING.
- `.env` is gitignored; `.env.example` holds placeholders only.
- Pydantic validation on every endpoint; parameterised SQL throughout; no
  `dangerouslySetInnerHTML`; a global handler that never returns a stack trace.
- **Not implemented:** authentication, role-based access, rate limiting. Out of
  scope for a prototype and we say so rather than claiming them.

---

## What we have NOT built

Stating this plainly is cheaper than being caught.

| Capability | Status |
|---|---|
| Alert generation engine | **Not built** |
| Acknowledge → dispatch → resolve workflow | **Not built** |
| Email / SMS / webhook delivery | **Not built**, not simulated |
| Scheduled background ingestion | **Not built** — analysis is on-demand |
| "Simulate new event" demo control | **Not built** |
| Historical analytics page | **Not built** — the endpoint exists, nothing renders it |
| Authentication / RBAC / rate limiting | **Not built** |
| PostGIS deployment | Schema written, not wired up |

These are the next increment, not things we will claim on stage.

---

## Questions we would ask ourselves

**"Your labels aren't ground truth, so is any of this real?"**
The *observations* are entirely real — every coordinate, brightness value, FRP
reading and facility comes from NASA and OpenStreetMap, and the Data screen reads
that provenance live. The *labels* are inferred, which caps what the accuracy figure
means. Partnering with a state forest department or pollution control board for
verified incident reports is the single change that would lift this most, and it is
the top item in future scope.

**"You said 900 detections — is that 900 fires?"**
No, and the interface now says so rather than needing a footnote. It is 372 fire
events. A detection is a hot pixel; one fire seen across several overpasses produces
several of them.

**"Why did it say agricultural burning in September, outside the burning season?"**
It no longer does. That exact question produced the evidence gate — the measurement
is in the Method screen and in this document, section 12.

# Model card — FIRETRACE Random Forest v1.0.0

Generated from `backend/ml/artifacts/metrics.json` and `validation.json`.
Trained 16 September 2026. Reproduce with `python -m ml.train` and
`python -m ml.validate` from `backend/`.

> **Read this section before quoting any number below.**
> The held-out score is **1.000**. That is not a success. It is the signature of
> **label circularity**, and this card exists to say so in the same place the
> number appears. Section 3 is the evidence. Section 4 is what the model is
> actually worth. A judge who reads only the headline figure will be misled, and
> that would be our fault, not theirs.

---

## 1. What this model is

| | |
|---|---|
| Name | FIRETRACE Random Forest |
| Version | 1.0.0 (feature v1.0.0, label policy v1.0.0) |
| Type | `RandomForestClassifier`, 300 trees, max_depth 14, min_samples_leaf 3, `class_weight="balanced_subsample"` |
| Input | 48 engineered features per FIRMS detection |
| Output | One of 4 policy-derived classes plus an uncalibrated RF vote-share vector |
| Artefact | `backend/ml/artifacts/firetrace_rf.joblib` (1.5 MB) |
| Training time | 3.92 s |

**Classes:** `INDUSTRIAL_FIRE`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`,
`AGRICULTURAL_BURNING`, `NATURAL_FIRE`.

**Intended use.** Triage of NASA FIRMS thermal anomalies over Indian industrial
regions, to separate industrial fire from vegetation and agricultural fire
(PS 26162 deliverable i). It is a *decision-support* component inside a pipeline
that also runs a deterministic rule policy, an evidence gate and a human incident
workflow. It is not an authority on what is burning.

**Out of scope.** Not a wildfire predictor. Not a detector — FIRMS detects, this
classifies what FIRMS already found. Not validated outside the 11 Indian regions
listed in section 2. Not usable as evidence of regulatory non-compliance.

---

## 2. Training data

Real NASA FIRMS detections (VIIRS NOAA-21/SNPP, MODIS) with real OpenStreetMap
context. **No synthetic rows.** No fabricated incidents.

| | Rows | Share |
|---|---:|---:|
| Detections processed | 10,804 | 100% |
| **Labelled** (policy committed to a class) | **3,514** | 32.5% |
| **Unlabelled** (policy refused to commit) | **7,290** | 67.5% |

That 67.5% abstention rate is deliberate and is the single most important number
about the dataset. The labelling policy (`app/services/labeling.py`, rules
R1–R7) only labels a detection when the evidence is unambiguous. Everything else
is excluded rather than forced into a class, because a forced label would be a
fabricated one.

**Class balance of the labelled set:**

| Class | Rows | Share |
|---|---:|---:|
| `GAS_FLARE_OR_INDUSTRIAL_HEAT` | 2,534 | 72.1% |
| `NATURAL_FIRE` | 671 | 19.1% |
| `AGRICULTURAL_BURNING` | 237 | 6.7% |
| `INDUSTRIAL_FIRE` | **72** | **2.0%** |

`INDUSTRIAL_FIRE` — the class the problem statement is actually about — is the
rarest, at 72 rows. This is a real constraint, discussed in section 5.

### Labels are not ground truth

Labels come from a documented **weak-supervision rule policy**, not from verified
incident reports. Nobody visited these sites. There is no fire-department record
behind any row. Consequently **every metric in this card measures agreement with
that policy**, not real-world correctness. This is stated in the dataset
manifest, the model metadata, the API response and the UI, so the figure cannot
travel without its caveat.

---

## 3. The circularity finding

### 3.1 The headline numbers

Split: `GroupShuffleSplit` by `region_id`, test_size 0.25, seed 42.
Train 2,279 rows / 8 regions. Test 1,235 rows / 3 regions.
Test regions (`angul`, `punjab_central`, `taloja`) appear in **no** training row.

| Metric | Value |
|---|---:|
| Accuracy | 1.000 |
| Balanced accuracy | 1.000 |
| Macro F1 | 1.000 |
| OOB score | 0.999 |
| 5-fold CV balanced accuracy | 0.999 ± 0.001 |

Per class, precision = recall = F1 = 1.00 for all four
(support: flare 998, agricultural 181, natural 48, **industrial 8**).

### 3.2 Why this is a warning, not a result

A perfect score on unseen regions should be impossible for a hard problem. It is
achievable here because **the labels are a deterministic function of features the
model can see**. The rule policy decides using facility distance, persistence,
FRP and land cover; the model receives those same columns. The task therefore
collapses from "classify fires" to "recover a rule set" — which is easy.

The baseline comparison proves it. If the problem were genuinely hard, simple
models would fail and the Random Forest would pull ahead. Instead:

| Model | Balanced acc. | Macro F1 | Industrial recall |
|---|---:|---:|---:|
| Majority class | 0.250 | 0.224 | 0.00 |
| Stratified random | 0.303 | 0.235 | 0.13 |
| One-rule stump (1 feature, 1 threshold) | 0.497 | 0.331 | 0.00 |
| **Depth-3 decision tree** | **0.997** | 0.991 | 1.00 |
| **Logistic regression** (linear) | **1.000** | 1.000 | 1.00 |
| **Random Forest (shipped)** | **1.000** | 1.000 | 1.00 |

**Lift of the Random Forest over the best baseline: 0.000.**

A depth-3 tree — three yes/no questions, readable aloud — scores 0.997. A linear
model scores 1.000. The 300-tree ensemble adds nothing in accuracy terms. That is
the definition of a circular target.

### 3.3 The forest is the *least stable* of the three

Across **12 independent region-grouped splits**:

| Model | Balanced acc. (mean ± std) | Min | Max |
|---|---:|---:|---:|
| Majority class | 0.229 ± 0.069 | 0.000 | 0.250 |
| Stratified random | 0.236 ± 0.060 | 0.049 | 0.298 |
| One-rule stump | 0.478 ± 0.045 | 0.333 | 0.500 |
| Depth-3 tree | 0.992 ± 0.011 | 0.961 | 1.000 |
| Logistic regression | **0.996 ± 0.004** | 0.986 | 1.000 |
| Random Forest | 0.969 ± **0.068** | **0.750** | 1.000 |

The Random Forest has the **highest variance and the worst single split (0.750)**
of the three competitive models. The single-split 1.000 is a favourable draw, not
a stable property. Anyone quoting 1.000 without this table is quoting a lucky
seed.

### 3.4 Data-leakage audit — verdict CLEAN

The perfect score is *not* caused by leakage. That was checked separately and
independently:

| Check | Result |
|---|---|
| Identical feature rows across the split | **0** |
| Shared coordinates between train and test | **0** |
| Shared regions between train and test | **0** |
| Duplicate detection IDs anywhere | **0** |
| Split axis | region (spatial), not time |
| **Verdict** | **CLEAN** |

One real leak *was* found and fixed during this audit: region bounding boxes
overlap on purpose (`punjab_central` 75.05–76.05° E against `punjab_malwa`
74.35–75.35° E), so 18 detections in the shared strip were fetched twice under
different `region_id`s and could land on both sides of the split. Fixed by
deduplicating on `event_id` in `ml/build_dataset.py`. The figures in this card
are all post-fix.

**Known limitation:** train and test share a 48-day date range. The split is
spatial, not temporal, so this card cannot claim the model generalises *forward
in time*. That would need a chronological hold-out, which is future work.

### 3.5 What the training script now does about it

`ml/train.py` detects its own implausible result. At balanced accuracy ≥ 0.98 it
prints a blocking warning and writes `circularity_warning: true` plus an
explanatory note into `metrics.json`. The number cannot be exported from the
pipeline without the caveat attached to it.

---

## 4. So what *is* the model worth?

If rules already reproduce the labels, why ship a classifier at all? Two honest
reasons — neither of which is accuracy.

**(a) It emits an uncalibrated vote score; rules emit only a verdict.**
The system's evidence gate abstains at 0.45 (hard floor) and 0.72 (raised
threshold when no facility *and* no land-cover polygon supports the point). A
rule set has no notion of "0.63 confident" and so cannot express degrees of
doubt. The probability is what makes principled abstention possible.

**(b) It covers the 67.5% of detections the policy refuses to label.**
This is the only place the model can add information the rules do not already
contain. Measured on all 7,290 policy-abstained rows:

| | |
|---|---:|
| Rows | 7,290 |
| Mean top-class probability | 0.660 |
| Below 0.45 (hard floor) | 15.6% |
| Below 0.72 (raised threshold) | 63.1% |
| Thin-evidence rows | 689 (9.5%) |
| **Abstained under the gate** | **1,651 (22.6%)** |

Predicted spread: agricultural 3,037, flare/heat 2,984, industrial 983,
natural 286.

The mean confidence of 0.660 is the point. On rows the policy called ambiguous,
the model is *also* unsure — it does not manufacture false certainty — and the
gate withholds a verdict on 1,651 of them. **There is no ground truth for these
rows, so this measures behaviour and gate coverage, not correctness.** It is
reported as behaviour and must not be cited as accuracy.

---

## 5. Limitations

1. **The 1.000 score measures policy agreement, not fire-classification skill.**
   Nothing in this repository establishes real-world accuracy, because no
   verified ground truth exists for any row.
2. **`INDUSTRIAL_FIRE` rests on 72 labelled rows, and only 8 in the test set.**
   Eight. A per-class score on 8 samples has an enormous confidence interval and
   should be treated as anecdote. This is the weakest number in the project.
3. **Labels are rules.** Any systematic error in the rule policy is inherited by
   the model, invisibly, and will never appear as a metric.
4. **No temporal generalisation evidence** (section 3.4).
5. **Geographic scope is 11 Indian regions.** Behaviour elsewhere is unknown.
6. **OSM coverage is the ceiling on context.** An unmapped facility cannot be
   used as evidence; the gate abstains instead of guessing, which is correct but
   means coverage gaps become abstentions.
7. **Feature importance is not causation.** `landcover__forest_vegetation`
   (0.124) ranks first largely because rule R6 keys on vegetation clearance.
8. **The Random Forest is the least stable competitive model** (section 3.3).
   Logistic regression would be a defensible swap on stability grounds; the
   forest is kept for its probability spread and per-sample decision-path
   attribution.

### Top features (Gini importance)

| Feature | Importance |
|---|---:|
| `landcover__forest_vegetation` | 0.124 |
| `distance_to_facility_km` | 0.106 |
| `facility_proximity_score` | 0.104 |
| `is_persistent` | 0.084 |
| `distinct_days` | 0.080 |
| `recurrence_count` | 0.063 |
| `longitude` | 0.047 |
| `facility_onsite` | 0.046 |

`longitude` at rank 7 is a mild geographic-memorisation signal and is called out
rather than hidden.

---

## 6. Performance

| Operation | Measured |
|---|---:|
| Single prediction (cold) | 258 ms |
| Batch of 1,235 rows | 438 ms total |
| Per row, batched | **0.35 ms** |
| Full training run | 3.92 s |

Measured on the development machine, single process. These are model-inference
figures only and exclude FIRMS and Overpass network time, which dominates
end-to-end latency.

---

## 7. How to reproduce

```bash
cd backend
python -m ml.build_dataset    # fetches FIRMS + OSM, applies the label policy
python -m ml.train            # trains; prints the circularity warning
python -m ml.validate         # leakage audit, baselines, 12-split stability
```

`ml/validate.py` is written as a hostile review of our own model: it tries to
find leakage, tries to beat the model with trivial baselines, and tests whether
the headline score survives resampling. It found the circularity documented
here. That is what it is for.

---

## 8. One-paragraph summary for a judge

> Our classifier scores 1.000 on held-out regions. **We do not present that as an
> accuracy claim.** We ran the baselines: a depth-3 decision tree scores 0.997 and
> logistic regression scores 1.000, so our Random Forest adds exactly zero lift.
> That proves the labels are circular — they come from a rule policy over the same
> features the model sees, so any model recovers the rules. We audited for leakage
> separately and it is clean. What the model actually contributes is a probability
> the rules cannot express, which drives an abstention gate that withholds a
> verdict on 23% of ambiguous detections, and coverage of the 67.5% of detections
> our policy refuses to label. The honest statement of our ML maturity is: a
> verified pipeline on real NASA data with a rule-derived target, not a
> field-validated fire classifier.

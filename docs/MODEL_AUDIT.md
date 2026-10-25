# Model audit

What the classifier actually is, what its metrics do and do not mean, and what
was changed. Audited 2026-10-25 on branch `sih-final`.

Short version: **the model works as designed, and its headline metric is
meaningless as a capability claim.** Both of those are true at once, and the
second is the more important one to say out loud.

---

## 1. What it is

| | |
|---|---|
| Algorithm | `RandomForestClassifier` (scikit-learn), 300 trees |
| Features | 48 |
| Trained classes | `AGRICULTURAL_BURNING`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`, `INDUSTRIAL_FIRE`, `NATURAL_FIRE` |
| Fifth output | `UNKNOWN` — **not a trained class.** An abstention applied at inference when the top vote share falls below 0.45 |
| Artefact | `backend/ml/artifacts/firetrace_rf.joblib`, version 1.0.0, committed |

Verify: `GET /api/model/info`.

---

## 2. Label provenance — the thing that governs everything else

Labels are **weak supervision**: nine deterministic rules (`R0`–`R7`) applied to
real FIRMS + OSM observations.

```
rows labelled                3,514
rows left unlabelled         7,290   (rule R0 — ambiguous; excluded entirely)
duplicate detections removed    18
```

Per class:

| Class | Labelled rows | Test-set support |
|---|---:|---:|
| `GAS_FLARE_OR_INDUSTRIAL_HEAT` | 2,534 | 998 |
| `NATURAL_FIRE` | 671 | 48 |
| `AGRICULTURAL_BURNING` | 237 | 181 |
| **`INDUSTRIAL_FIRE`** | **72** | **8** |

Source: `backend/ml/data/dataset_manifest.json`, which states
`label_source: "weak supervision rules (NOT verified ground truth)"`.

**No detection in this project has a verified cause.** Nobody went to a plant and
confirmed a fire. That is the ceiling on every claim below.

---

## 3. The metrics, and why they do not mean what they look like

From `backend/ml/artifacts/metrics.json`:

```
accuracy                   1.0
balanced_accuracy          1.0
macro_f1                   1.0
oob_score                  0.9991
cv_balanced_accuracy       0.9992 ± 0.001
train / test rows          2,279 / 1,235
split                      grouped by region (11 regions)
confusion matrix           perfectly diagonal
```

**These are circular.** The labelling rules operate on the same features the
model sees, so a high score measures how faithfully the forest reproduces the
rule policy — not whether it classifies fires correctly.

Three things establish that, rather than just asserting it:

1. The artefact says so itself. `metrics.json` carries
   `"circularity_warning": true` and an `interpretation` field stating the
   figures are not verified real-world accuracy.
2. `backend/ml/validate.py` fits a **depth-3 decision tree** and a **logistic
   regression** on the same split. They score comparably. A problem that a
   depth-3 tree solves perfectly is a lookup table, not a learned
   generalisation.
3. The split is grouped by region, which rules out *spatial* leakage — and the
   score is still 1.0. If the task were genuinely hard, grouping would hurt.

**Credit where it is due: the original authors documented this honestly before I
audited it.** My change is not the discovery; it is making sure no surface ever
renders 1.0 as "accuracy".

### What may and may not be said

| Claim | Allowed? |
|---|---|
| "Reproduces a documented labelling policy on held-out regions" | Yes |
| "Abstains rather than guessing when evidence is thin" | Yes — measurable, see §5 |
| "100% accurate" / "99% accurate" | **No** |
| "Validated against real fire outcomes" | **No** |
| "The score is a probability" | **No** — uncalibrated vote share |

---

## 4. Defects found, and what was done

### D1 — Abnormality was manufactured from missing history · **FIXED**

The original code:

```python
def abnormality(recurrence):
    if not recurrence.history_available:
        return 0.5
    return _clamp(1.0 - recurrence.persistence_ratio)
```

`history_available` is a *global* flag — "is any history loaded at all" — not a
per-location one. A location with zero prior detections therefore got
`persistence_ratio = 0.0` → **`abnormality = 1.0`, "maximally unusual"**.

Measured before the fix: **351 of 500 detections (70%) carried exactly 1.0**,
every one of them with no prior detection at its location.

This conflated two different statements:

- *"we watched this place and it never lit up"* → genuinely unusual;
- *"we have no coverage of this place"* → unknown, and **not** unusual.

In this archive it is overwhelmingly the second. The capture spans 2025-11-11 to
2026-09-10 but is built from ten 5-day windows (Oct–Nov 2025, Mar 2026), so a
September 2026 event has an empty 60-day lookback *because the archive contains
no September data* — not because the site is quiet.

**The fix:** `abnormality()` now returns `(value | None, status)`. Below
`MIN_DAYS_FOR_BASELINE = 2` distinct prior days at that location it returns
`None` with status `insufficient_history`, and `compute_priority` **renormalises
the remaining weights** rather than letting a fabricated value into the sum.

### D5 — Absent evidence was listed as supporting evidence · **FIXED**

Factors such as `"Land cover here is unknown"` were emitted with
`direction: "supports"`. Absence of evidence supports nothing. The verdict layer
now keeps `missing[]` strictly separate and the evidence drawer renders it under
its own warning icon.

### Grammar and consistency defects · **FIXED**

- 54 of 390 sites rendered `"4 satellite detections over 0 min"`.
- Four `INDUSTRIAL_FIRE` sites (all Reliance Refinery) asserted an "episodic
  signature, rather than routine operation" directly above an evidence line
  reading "detected on 3 separate days".

### Not changed, deliberately

- **Training labels.** Not touched. Changing the policy would invalidate the
  artefact and every metric alongside it, and the policy is at least documented
  and inspectable.
- **The abstention threshold (0.45).** Left where validation put it. Tuning it
  to improve a demo is exactly the thing not to do.
- **The model itself.** Not retrained. The defects were in the scoring and
  presentation layers, not the estimator.

---

## 5. Before / after, measured

Re-run with the identical protocol — demo archive, India bbox, `days=1`.
**Reported as measured, including where the numbers got worse-looking.**

### Site level (390 sites)

| | Before | After |
|---|---|---|
| Needs attention | 11 | **8** |
| Watch | 14 | 17 |
| Normal | 254 | 254 |
| Not sure | 111 | 111 |
| HIGH priority | 11 | **8** |
| MEDIUM priority | 248 | **131** |
| LOW priority | 131 | **251** |
| Mean priority score | 0.4403 | **0.3868** |

### Detection level (500 analysed)

| | Before | After |
|---|---|---|
| HIGH | 36 | 31 |
| MEDIUM | 465 | 296 |
| LOW | 215 | 389 |
| Abnormality assessed | 500 (all fabricated where absent) | **121** |

**Interpretation.** Scores fell across the board and three sites left "needs
attention". That is the correct direction: those three were ranked highly in part
because of an invented novelty claim. The queue is shorter and every remaining
entry is supported by something measured.

### The limitation this exposes

Only **16 of 390 sites (4%)** have enough per-location history for abnormality to
be assessed at all:

```
distinct prior detection days:  0 → 325 sites      3 → 5
                                1 →  47            4 → 1
                                2 →   9            5 → 2
                                                   8 → 1
```

**FIRETRACE cannot currently compute a real per-facility "normal range" for most
sites.** It can for a handful — the ArcelorMittal Hazira flare has 8 prior days
and scores 11/100 abnormal, which is a genuine, defensible number. For the rest
the honest output is "not assessed", and that is what the interface now says.

This is why the UI makes **no** "N times the facility's usual range" claims. The
sentence would be unsupported for 96% of sites.

**What would fix it:** a denser archive — continuous daily FIRMS pulls over one
industrial region for 60+ days rather than ten sampled 5-day windows. That is a
data-collection job, not a modelling one, and it is the single highest-value
next step for this project.

---

## 6. Reproducing

```bash
cd backend
.venv/Scripts/python.exe -m ml.validate      # baselines + circularity check
.venv/Scripts/python.exe -m pytest -q        # 332 tests
```

Model metrics come from the committed artefact; retraining is
`.venv/Scripts/python.exe -m ml.train` and needs the dataset in
`backend/ml/data/`.

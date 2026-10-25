# Priority rules

How FIRETRACE decides what to show first. Written out as a table rather than
left in code, because an operator who disagrees with the ranking should be able
to see exactly what produced it.

**This is a prototype triage aid defined by this project. It is not an official
government risk rating and has not been validated against incident outcomes.**

Live version of everything below: `GET /api/meta` → `priority`.

---

## 1. Three separate questions, three separate fields

The most important rule here is what is *not* combined.

| Question | Field | Range |
|---|---|---|
| What is it? | `predicted_class` + `model_score` | 4 classes, or `UNKNOWN` |
| How unusual is it **for this location**? | `abnormality_score` | 0–100, or *not assessed* |
| How urgently should someone look? | `operational_priority` | HIGH / MEDIUM / LOW |

Merging these into one "risk number" is the standard temptation and it destroys
the information. A routine refinery flare can be enormous and uninteresting; a
small novel detection on a chemical plant can matter a lot. One number cannot
say both.

---

## 2. The priority score

A transparent weighted sum — deliberately not a second opaque model. Every
component is a named 0–1 value, every weight is configurable, and the API returns
both alongside the score.

| Component | Weight | What it measures |
|---|---:|---|
| `model_confidence` | 0.20 | Uncalibrated vote share for the leading trained class |
| `class_severity` | 0.25 | How much attention the predicted class warrants |
| `thermal_severity` | 0.20 | Radiative power on a log scale (FRP spans orders of magnitude) |
| `industrial_proximity` | 0.15 | 1.0 on a mapped facility footprint, decaying to 0 at the search radius |
| `abnormality` | 0.10 | 1 − persistence. **Only when assessable — see §3** |
| `recency` | 0.10 | Exponential decay on detection age, 3-day half-life |

Class severity:

| Class | Severity |
|---|---:|
| `INDUSTRIAL_FIRE` | 1.00 |
| `GAS_FLARE_OR_INDUSTRIAL_HEAT` | 0.55 |
| `UNKNOWN` | 0.45 |
| `NATURAL_FIRE` | 0.35 |
| `AGRICULTURAL_BURNING` | 0.20 |

`UNKNOWN` sits mid-range on purpose: an unresolved event is unresolved, not
harmless. It must not sink to the bottom of the queue just because the model
declined to name it.

Thresholds: **HIGH ≥ 0.65**, **MEDIUM ≥ 0.45**, otherwise LOW.

---

## 3. Components that cannot be assessed are removed, not guessed

This is the rule that matters most, and the one that was wrong until this audit.

When a component cannot be measured for an event, its **weight is removed from
the denominator** and the score is renormalised over what remains. A component we
cannot measure must not contribute a fabricated value — and equally must not
silently drag the score down by contributing zero.

Currently this applies to `abnormality`:

| Condition | `abnormality_status` | Effect |
|---|---|---|
| ≥ 2 distinct prior detection days at this location | `assessed` | Contributes `1 − persistence_ratio` |
| 0–1 prior days | `insufficient_history` | **Excluded.** Weight redistributed |
| No history window loaded at all | `no_history_loaded` | **Excluded.** Weight redistributed |

Why the bar exists: with fewer than two prior days there is no baseline for
"unusual" to be unusual *against*. The earlier code returned 1.0 — "maximally
unusual" — for exactly these cases, which inflated 70% of detections. See
`docs/MODEL_AUDIT.md` §4.

Honest consequence: **only 16 of 390 sites (4%) in the demo archive have an
assessable abnormality.** The interface reports "not assessed — too little
history here" for the rest, and makes no claim about the facility's normal range.

---

## 4. Display status — what the user actually reads

The score and class are mapped down to four words. Evaluated in this order; the
first match wins.

| Order | Condition | Status shown | Why |
|---:|---|---|---|
| 1 | Model abstained (`UNKNOWN`) | **Not sure** | If the model declined to name a class, the system must not then assert that the event needs attention. Abstention outranks priority |
| 2 | `operational_priority == HIGH` | **Needs attention** | Clearly unusual, or a likely industrial incident |
| 3 | `persistent == true` | **Normal** | A source detected on ≥ 5 distinct days at ≥ 0.25 of the window is this location's normal. A flare that burns daily is not an incident |
| 4 | Industrial class, episodic | **Watch** | On or near industry, not scoring high enough to call out |
| 5 | Agricultural / natural, MEDIUM, within 1 km of industry | **Watch** | Close enough to industry to be worth a glance |
| 6 | Anything else | **Normal** | Behaving as its class implies, away from industry |

A "Not sure" event still carries its priority score and still sorts near the top
of the queue, so admitting uncertainty never buries an event.

Implemented once, in `backend/app/services/verdict.py::display_status`, and
asserted by `backend/tests/test_map_verdict.py`.

---

## 5. Queue order

`/api/map` returns sites pre-sorted for triage:

1. **Needs attention** (descending priority score)
2. **Not sure** (descending priority score)
3. **Watch**
4. **Normal**

Unresolved events rank above watch and normal deliberately: an event nobody has
classified is a question outstanding, and the queue is a to-do list.

---

## 6. What this does not do

- It does not rank regulatory non-compliance. Persistence *lowers* priority here,
  which is right for incident triage and wrong for a compliance view — a
  regulator interested in chronic flaring would want the ranking inverted. That
  view is not built.
- It does not account for what is nearby — population, schools, other plants.
  A 20 MW event beside a residential area and one in an empty industrial zone
  score identically. Adding exposure weighting is an obvious next step and would
  need a population raster we do not ship.
- It is not calibrated against outcomes, because no outcome data exists for these
  detections.

---

## 7. Changing it

Every weight is an environment variable (`PRIORITY_WEIGHT_*` in `.env.example`);
they are normalised, so they need not sum to 1. The thresholds and the
`MIN_DAYS_FOR_BASELINE` constant live in
`backend/app/services/priority.py`.

If you change any of them, re-run `npm run smoke` and update the before/after
table in `docs/MODEL_AUDIT.md` §5 with the real figures.

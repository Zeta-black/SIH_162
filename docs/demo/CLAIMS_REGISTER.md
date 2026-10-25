# Claims register

Every factual claim we make on stage, in slides, or in the README, with the
evidence behind it and an honest status.

**Rule: if a row is not `Verified`, it does not get said on stage.**

Status meanings:
- **Verified** — measured or tested on this machine; the command is given and
  re-runnable.
- **Partly** — true with a stated caveat that must be said alongside it.
- **Not verified** — we believe it but have not established it. Do not assert.

All measurements taken 2026-10-25 on Windows 11 Pro 26100, Node v24.18.0,
Python 3.11.9, from branch `sih-final`.

---

## A. Data and provenance

| # | Claim | Evidence | Status |
|---|---|---|---|
| A1 | Detections are real NASA FIRMS records, not synthetic | `GET /api/map` returns `provenance.source: "NASA FIRMS"`; archive built by `ml/build_snapshot.py` from live FIRMS pulls; `dataset_manifest.json` records `observation_source: "NASA FIRMS (real detections)"` | **Verified** |
| A2 | Industrial facilities are real OpenStreetMap features | 1,482 facilities in `demo_snapshot.json` with real OSM ids and names (e.g. `W1395914408`); `context_source: "OpenStreetMap via Overpass (real features)"` | **Verified** |
| A3 | The archive holds 716 detections, 1,482 facilities, 6,021 land-use polygons | `GET /health` → `checks.snapshot` | **Verified** |
| A4 | The archive spans 2025-11-11 to 2026-09-10 across six regions | `GET /health` → `checks.snapshot.date_range`, `.regions` | **Verified** |
| A5 | The live feed works and returned 811 detections for India on 2026-10-25 | `GET /api/map?mode=live` → `counts.detections: 811`, `provenance.state: "live"` | **Verified** |
| A6 | A replay is never presented as live data | `tests/test_map_verdict.py::test_demo_mode_is_labelled_replay_never_live`; smoke group 7 asserts the chip text | **Verified** |
| A7 | Observation time and retrieval time are separate fields | `site.observed_at` vs `provenance.retrieved_at`; asserted in smoke group 4 | **Verified** |
| A8 | We do **not** have national coverage | Six regions only. **Must be said whenever coverage comes up.** | **Verified (as a limitation)** |

---

## B. The model

| # | Claim | Evidence | Status |
|---|---|---|---|
| B1 | Random Forest, 48 features, 4 trained classes plus an abstention | `GET /api/model/info`; `metrics.json` | **Verified** |
| B2 | Reported accuracy / macro-F1 = 1.0 | `backend/ml/artifacts/metrics.json` | **Verified as a number, meaningless as a capability claim — see B3** |
| B3 | Those metrics are circular and are **not** real-world accuracy | `metrics.json` carries `circularity_warning: true` and an `interpretation` field stating it; `ml/validate.py` shows a depth-3 tree and logistic regression scoring comparably | **Verified** |
| B4 | **We have validated real-world fire-classification accuracy** | — no per-detection ground truth exists in this project | **NOT VERIFIED — never claim this** |
| B5 | The model score is an uncalibrated vote share, not a probability | `schemas.py` `Classification.confidence` docstring; `model.score_note` in `/api/map`; asserted in smoke group 4 | **Verified** |
| B6 | Calibration has been checked | — not attempted | **NOT VERIFIED — never claim this** |
| B7 | Labels are rule-generated weak supervision, not ground truth | `dataset_manifest.json` → `label_source: "weak supervision rules (NOT verified ground truth)"`, 9 rules R0–R7 | **Verified** |
| B8 | Train/test split is grouped by region, with 18 duplicates removed | `metrics.json` `split_strategy`; `dataset_manifest.json` `duplicate_detections_removed: 18` | **Verified** |
| B9 | `INDUSTRIAL_FIRE` is severely under-represented (72 of 3,514 labels; 8 test rows) | `dataset_manifest.json` `label_counts`; `metrics.json` `per_class` support | **Verified (state as a limitation)** |
| B10 | The evidence gate cut September false agricultural calls from 810 to 164 | `GET /api/model/info` → `abstention.evidence_gate` | **Partly** — the figure is recorded in the artefact from an earlier measured run; I did not re-measure it this session. Say "measured on a September query, recorded in the model card". |

---

## C. Behaviour on screen

| # | Claim | Evidence | Status |
|---|---|---|---|
| C1 | 8 need attention, 17 watch, 254 normal, 111 not sure, from 390 sites | `GET /api/map?mode=demo` → `counts` | **Verified** |
| C2 | 716 detections group into 390 sites (1.84× compression) | `GET /api/events` → `summary.compression` | **Verified** |
| C3 | A real "Not sure" case exists and is visible | 111 sites; Block - B coal mine scores 0.4431 against a 0.45 threshold | **Verified** |
| C4 | Two detections at the same plant get opposite verdicts, and the "Normal" one is 8.7× hotter | ArcelorMittal Nippon Steel India: `FE-2026-43C5` 4.16 MW "Needs attention" vs `FE-2026-4BA6` 36.33 MW "Normal"; 230 m apart | **Verified** |
| C5 | Every "why" line traces to a backend field | `verdict.why_bullets` only ever returns strings from `FireEvent.risk_factors`; `tests/test_map_verdict.py::test_every_bullet_came_from_the_event` | **Verified** |
| C6 | Classification, model score and operational priority are separate fields | `/api/map` site schema; asserted in smoke group 4 | **Verified** |
| C7 | Proximity is presented as context, never as cause | "What this is not" section in the evidence drawer; asserted in smoke group 7 | **Verified** |
| C8 | The main screen shows at most five numbers | Three in the summary line plus one filter count. Cluster bubbles carry counts, as on any clustered map | **Partly** — true of the chrome; cluster bubbles are map content |
| C9 | Abnormality is reported as "not assessed" where there is too little history, not invented | `priority.abnormality()` returns `(None, status)`; 374 of 390 sites report `insufficient_history`; `tests/test_abnormality_baseline.py` (21 tests) | **Verified** |
| C10 | The ArcelorMittal flare scores 11/100 abnormal, from 8 days of real history | `GET /api/map?mode=demo` → site `FE-2026-4BA6` `abnormality_score: 11`, `abnormality_status: "assessed"`, `distinct_days: 8` | **Verified** |
| C11 | Only 16 of 390 sites (4%) have enough history for abnormality to be assessed | Measured; `docs/MODEL_AUDIT.md` section 5. **State this whenever a facility baseline is discussed** | **Verified (as a limitation)** |

---

## D. Reliability

| # | Claim | Evidence | Status |
|---|---|---|---|
| D1 | Works fully offline with no API key | `npm run demo:offline`; smoke group 5 "Demo mode works and is labelled Replay"; `test_demo_mode_never_contacts_the_network` | **Verified** |
| D2 | A rejected key still shows real data, labelled Offline | Smoke group 5: 811 cached detections, `is_live: false`; `test_rejected_key_falls_back_and_never_claims_live` | **Verified** |
| D3 | No network still shows real data, labelled Offline | Measured: 390 archive sites, `state: "offline"` against an unreachable FIRMS host | **Verified** |
| D4 | No failure mode produces a "Live" badge | `TestProvenanceIsNeverFlattering` — 3 failure kinds × 3 modes | **Verified** |
| D5 | The last good live fetch survives a restart, expiring at 72 h | `livecache.py`; `TestLiveDiskCache` (6 tests) | **Verified** |
| D6 | One command starts everything | `npm run demo` — measured ~20 s warm, including health wait and pre-warm | **Verified** |
| D7 | The basemap needs no API key | OpenStreetMap tiles; smoke group 7 asserts the tile host. CARTO was rejected after verifying it returns a 2,049-byte "API KEY REQUIRED" PNG at HTTP 200 | **Verified** |

---

## E. Performance (all measured, none estimated)

| # | Claim | Evidence | Status |
|---|---|---|---|
| E1 | App interactive in ~1.5 s | Smoke group 7: 1,510 ms | **Verified** |
| E2 | First contentful paint ~1.0 s | Smoke group 7: 1,072 ms | **Verified** |
| E3 | `/api/map` responds in ~210 ms warm | Smoke group 4: 211 ms | **Verified** |
| E4 | 11 of 13 API routes respond under 70 ms warm | Smoke group 4 timings | **Verified** |
| E5 | Zero console errors | Smoke group 7 | **Verified** |
| E6 | No critical or serious WCAG 2 A/AA violations | axe-core: 20 rules passed, 0 violations | **Verified** |
| E7 | "Lighthouse score of N" | — Lighthouse was not run | **NOT VERIFIED — never quote a Lighthouse score** |
| E8 | Cold live national fetch takes ~11 s | Measured 10.9 s after the timeout fix (was 34.4 s) | **Verified** |
| E9 | Cold archive analysis takes ~3 s, warm ~0.1 s | Measured 2.9 s cold / 0.105 s warm | **Verified** |
| E10 | Clustering 716 detections takes ~100 ms | `GET /api/events` → `timing_ms.clustering: 103.8` | **Verified** |

---

## F. Engineering

| # | Claim | Evidence | Status |
|---|---|---|---|
| F1 | 332 automated tests pass | `cd backend && .venv/Scripts/python.exe -m pytest -q` → `332 passed` in 172 s | **Verified** |
| F2 | The quality gate is 50/50 green | `npm run smoke` → `SMOKE PASS 50/50` | **Verified** |
| F3 | Production build succeeds, lint clean | Smoke group 2 | **Verified** |
| F4 | No secrets are committed | Smoke group 1 (4/4) | **Verified for the current tree.** A real key exists in commit `8d39ff8` on this local branch — see the note below |
| F5 | The NASA key never reaches the browser | Backend-only; smoke group 4 checks every route's response body for the key | **Verified** |
| F6 | Runs with only `FIRMS_MAP_KEY` | No other key is read anywhere; basemap and OSM need none | **Verified** |

---

## Outstanding, and said plainly

1. **The FIRMS key should be rotated.** It was pasted into the committed
   `.env.example` template in the working tree, and I then quoted it verbatim
   into `docs/BASELINE.md`, which committed it to local history (`8d39ff8`).
   Nothing has been pushed, so exposure is local only. The working tree is
   clean. Rotating the key closes it outright; rewriting the two local commits
   is the alternative and needs an explicit decision.
2. **B10's 810→164 figure** comes from a recorded earlier run, not from a
   measurement I took this session. Attribute it to the model card.
3. **Abnormality is now honest but still thin.** BASELINE D1 is fixed — a
   location with too little history reports "not assessed" instead of a
   fabricated 1.0 — but only 16 of 390 sites clear the bar. The UI therefore
   still makes no "N times the normal range" claims. Do not make them verbally
   either. Fixing it properly needs a denser archive, not more code
   (`docs/MODEL_AUDIT.md` section 5).
4. **No Lighthouse score exists.** If asked for one, say axe-core found zero
   serious violations and FCP was measured at 1,072 ms.

# Claims register

Every factual claim we make on stage, in slides, or in the README, with the
evidence behind it and an honest status.

**Rule: if a row is not `Verified`, it does not get said on stage.**

- **Verified** — measured or tested on this machine; the command is given and
  re-runnable. Where a figure varies between runs the range is given, not the
  best observation.
- **Partly** — true with a stated caveat that must be said alongside it.
- **Not verified** — we believe it but have not established it. Do not assert.

All measurements taken 2026-10-26 on Windows 11 Pro 26100, Node v24.18.0,
Python 3.11.9, branch `sih-pass2`, `npm run smoke` → **81/81**.

---

## A. Data and provenance

| # | Claim | Evidence | Status |
|---|---|---|---|
| A1 | Detections are real NASA FIRMS records, not synthetic | `provenance.source`; archive built by `ml/build_snapshot.py` from live FIRMS pulls; `dataset_manifest.json` → `observation_source: "NASA FIRMS (real detections)"` | **Verified** |
| A2 | Industrial facilities are real OpenStreetMap features | 1,482 facilities with real OSM ids and names in `demo_snapshot.json` | **Verified** |
| A3 | The archive holds 716 detections, 1,482 facilities, 6,021 land-use polygons | `GET /health` → `checks.snapshot` | **Verified** |
| A4 | Past-data periods are generated from data actually held, never hard-coded | `services/timeline.py` derives contiguous runs of ≥3 days; smoke group 9 asserts every listed range has `detections > 0` | **Verified** |
| A5 | A date range we do not hold is refused, not faked | `?range=1999-01-01:1999-01-05` → HTTP 404; smoke group 9 | **Verified** |
| A6 | Observation time and retrieval time are separate fields | `feed.observed_at` vs `feed.retrieved_at`; smoke group 9 | **Verified** |
| A7 | A replay is never presented as live | `provenance.surface === "past"`, `is_live: false`; `test_demo_mode_is_labelled_replay_never_live`; browser checks assert the pressed segment and the banner | **Verified** |
| A8 | We do **not** have national coverage | Six regions only. **Must be said whenever coverage comes up** | **Verified (as a limitation)** |
| A9 | The live feed works | Verified in Pass 1 at 811 detections for India. On 2026-10-26 the live query returned `state: "empty"` — genuinely no detections in the window, which the UI states plainly | **Verified (behaviour); the count varies by day** |

---

## B. The model

| # | Claim | Evidence | Status |
|---|---|---|---|
| B1 | Random Forest, 48 features, 4 trained classes plus an abstention | `GET /api/model/info` | **Verified** |
| B2 | Reported accuracy / macro-F1 = 1.0 | `metrics.json` | **Verified as a number, meaningless as a capability claim — see B3** |
| B3 | Those metrics are circular and are **not** real-world accuracy | `metrics.json` → `circularity_warning: true`; `ml/validate.py` shows a depth-3 tree scoring comparably | **Verified** |
| B4 | **We have validated real-world fire-classification accuracy** | — no per-detection ground truth exists here | **NOT VERIFIED — never claim this** |
| B5 | The model score is an uncalibrated vote share, not a probability | `schemas.py` docstring; `model.score_note` in `/api/map` | **Verified** |
| B6 | Calibration has been checked | — not attempted | **NOT VERIFIED — never claim this** |
| B7 | Labels are rule-generated weak supervision, not ground truth | `dataset_manifest.json` → `label_source: "weak supervision rules (NOT verified ground truth)"` | **Verified** |
| B8 | `INDUSTRIAL_FIRE` is severely under-represented (72 of 3,514 labels; 8 test rows) | `dataset_manifest.json`, `metrics.json` | **Verified (state as a limitation)** |
| B9 | The evidence gate cut September false agricultural calls from 810 to 164 | `GET /api/model/info` → `abstention.evidence_gate` | **Partly** — recorded in the artefact from an earlier measured run; not re-measured this session. Say "measured on a September query, recorded in the model card" |

---

## C. Behaviour on screen

| # | Claim | Evidence | Status |
|---|---|---|---|
| C1 | The 1-10 Sep 2026 archive period shows 7 need attention, 8 watch, 18 normal, 10 not sure, from 43 sites / 196 detections | `GET /api/map?range=2026-09-01:2026-09-10` → `counts` | **Verified** |
| C2 | The full archive is 390 sites from 716 detections (1.84× compression) | `GET /api/events` → `summary.compression` | **Verified** |
| C3 | A real "Not sure" case exists and is visible | 10 in the Sept period; `FE-2026-66C8` Block - B coal mine | **Verified** |
| C4 | Two detections at the same plant get opposite verdicts, and the "Normal" one is 8.7× hotter | ArcelorMittal: `FE-2026-43C5` 4.16 MW "Needs attention / New heat" vs `FE-2026-4BA6` 36.33 MW "Normal / Persistent source, 8 days"; 230 m apart | **Verified** |
| C5 | Persistent sources and new heat are visually distinct without explanation | Rings vs filled discs (`fc-marker-persistent`); card badges "Persistent source · seen on 8 days" / "New heat" | **Verified** |
| C6 | Every "why" line traces to a backend field | `verdict.why_bullets` only returns strings from `FireEvent.risk_factors`; `test_every_bullet_came_from_the_event` | **Verified** |
| C7 | Classification, model score, abnormality and priority are four separate fields | `/api/map` site schema; `test_abnormality_is_separate_from_priority_everywhere` | **Verified** |
| C8 | Proximity is presented as context, never as cause | "What this is not" in the evidence drawer; browser checks assert the phrase | **Verified** |
| C9 | Abnormality reports "not assessed" where there is too little history, rather than inventing a number | `priority.abnormality()` returns `(None, status)`; 374 of 390 sites report `insufficient_history`; `test_abnormality_baseline.py` (21 tests) | **Verified** |
| C10 | The ArcelorMittal flare scores 11/100 abnormal from 8 days of real history | `FE-2026-4BA6` → `abnormality_score: 11`, `abnormality_status: "assessed"`, `distinct_days: 8` | **Verified** |
| C11 | Only 16 of 390 sites (4%) have enough history for abnormality to be assessed | Measured; `docs/MODEL_AUDIT.md` §5. **State this whenever a baseline is discussed** | **Verified (as a limitation)** |
| C12 | The freshness line is computed from real timestamps and ticks | `LiveControl.jsx` re-renders on a 30 s interval and adds elapsed drift; smoke group 8 asserts the component holds no literal year | **Verified** |
| C13 | No UI copy says "try live", "real-time", "instant", "100% accurate" or "AI-powered", and no hard-coded date | Smoke group 8 greps every tracked frontend file | **Verified** |
| C14 | The main screen shows at most five numbers | Three in the summary plus the filter counts, which restate them. Cluster bubbles carry counts | **Partly** — true of the chrome; cluster bubbles are map content |

---

## D. Notifications

| # | Claim | Evidence | Status |
|---|---|---|---|
| D1 | A replay sends nothing — no toast, no browser notification, no webhook | Enforced at creation in `notifications.evaluate(suppress=True)`; `TestReplaySendsNothing` (4 tests) incl. one that fails if `httpx.post` is reached; smoke group 9 asserts the open count does not move | **Verified** |
| D2 | A replay still shows what *would* have fired | `notifications.preview` — 10 items for the Sept period; labelled "Would have alerted" in the panel | **Verified** |
| D3 | Normal, Watch and Not sure never notify | `test_non_qualifying_statuses_never_notify`; `policy.never_notifies_for` | **Verified** |
| D4 | "Above its normal range" requires an assessed baseline | `test_abnormal_persistent_requires_an_assessed_baseline` | **Verified** |
| D5 | No notification can say a fire is confirmed | `FORBIDDEN_WORDS` raises at construction; `TestLanguage` (4 tests); smoke group 9 scans stored items | **Verified** |
| D6 | Cooldown, hysteresis, escalation and a daily cap all work | `TestHygiene` (7 tests) | **Verified** |
| D7 | One site produces one notification per evaluation | `test_one_site_produces_one_notification_per_evaluation` | **Verified** |
| D8 | Test alerts are labelled TEST in the message and the stored row | `POST /api/notifications/test`; smoke group 9 | **Verified** |
| D9 | The webhook retries with backoff and audits every attempt | `TestWebhook` (5 tests) incl. row counts after failure | **Verified** |
| D10 | A webhook has been delivered to a real Slack/Teams endpoint | — never configured on this machine | **NOT VERIFIED — say "Slack-compatible payload", not "tested with Slack"** |
| D11 | We send SMS or email | — not built | **NOT VERIFIED — never claim this. Say the webhook can be relayed** |

---

## E. Reliability

| # | Claim | Evidence | Status |
|---|---|---|---|
| E1 | Works fully offline with no API key | `npm run demo:offline`; `test_demo_mode_never_contacts_the_network` | **Verified** |
| E2 | A rejected key still shows real data, never badged live | Smoke group 5: 811 cached detections, `is_live: false`, state `delayed` | **Verified** |
| E3 | No network still shows real data | 390 archive sites against an unreachable FIRMS host | **Verified** |
| E4 | No failure mode produces a "fresh" state | `TestProvenanceIsNeverFlattering` — 3 failure kinds × 3 modes | **Verified** |
| E5 | The last good live fetch survives a restart, expiring at 72 h | `livecache.py`; `TestLiveDiskCache` (6 tests) | **Verified** |
| E6 | One command starts everything, and ports auto-step if taken | `npm run demo`; verified with 8000 and 5173 both held → moved to 8001/5174, healthy | **Verified** |
| E7 | The basemap needs no API key | OpenStreetMap tiles; browser checks assert the host. CARTO was rejected after verifying it returns a 2,049-byte "API KEY REQUIRED" PNG at HTTP 200 | **Verified** |
| E8 | The map is never blank — boundaries show when tiles fail | Bundled Natural Earth outline renders under the tiles, plus a "Map tiles unavailable" note | **Partly** — the fallback layer and note are implemented and the outline loads; a full tile-blackout has not been simulated end-to-end in the gate |
| E9 | Satellite imagery is available and keyless | Esri World Imagery, verified HTTP 200 returning real 15.5 KB JPEG imagery of Gujarat at z8 | **Partly** — works and is attributed, but Esri's terms for direct third-party tile use are not unambiguous. Say "with attribution, licence to be confirmed for deployment" |

---

## F. Performance (measured, none estimated)

| # | Claim | Evidence | Status |
|---|---|---|---|
| F1 | First contentful paint **408 ms on the production build** | `npm run perf` — production build served by `vite preview`. On the Vite dev server the same measurement ranges 980-2,044 ms, which is a statement about on-demand transforms rather than about the product | **Verified** |
| F2 | App interactive in 2.0-6.7 s | Observed 1,510 / 1,980 / 2,005 / 2,280 / 2,862 / 6,694 ms across runs on the dev server. **Quote the range.** On the production build, map-ready wall clock (including the archive fetch) measured 5,949 ms | **Verified (as a range)** |
| F3 | `/api/map` responds in 210-425 ms warm | Smoke group 4 across runs | **Verified** |
| F4 | Cold archive analysis ~3 s, warm ~0.1 s | Measured 2.9 s / 0.105 s | **Verified** |
| F5 | Clustering 716 detections takes ~100 ms | `GET /api/events` → `timing_ms.clustering: 103.8` | **Verified** |
| F6 | Zero console errors | Browser checks at 1366×768, 1920×1080, 390×844; 12 design-QA screens | **Verified** |
| F7 | No critical or serious WCAG 2 A/AA violations | axe-core: 20 rules passed, 0 violations (1 serious found and fixed this pass — `aria-expanded` on a bare search input) | **Verified** |
| F8 | "Lighthouse score of N" | — Lighthouse was not run | **NOT VERIFIED — never quote a Lighthouse score** |
| F9 | Map sustains ≥50 fps during pan/zoom and replay | **Measured, and pan does not.** `npm run perf`, production build, two runs: pan 18-32 fps mean (p95 12-20), zoom 46-58 (p95 30-60), replay 4x 51-60 (p95 20-60). Zoom and replay reach ~50; **pan does not** | **Verified — and the ≥50 claim is false for panning. Do not make it** |
| F10 | Panning is slow because of marker count | — the same figure appears with four markers on screen, so the cost is Leaflet's tile repositioning, not our rendering | **Verified (as a diagnosis, not a fix)** |

---

## F2. Consistency checks (proxy, not ground truth)

Run with `cd backend && .venv/Scripts/python.exe -m ml.proxy_checks`, written to
`backend/ml/artifacts/proxy_checks.json`, documented in `docs/MODEL_AUDIT.md` §6.

**Say "consistency checks, not accuracy" every single time one of these is
quoted.** Agreement with map context is not correctness.

| # | Claim | Evidence | Status |
|---|---|---|---|
| P1 | Recurring heat inside mapped industrial sites reads industrial in 92 of 98 cases (93.9%) | `proxy_checks.json`; 6 abstained, 0 disagreed | **Verified (as consistency, not accuracy)** |
| P2 | Single-day heat over vegetation far from industry reads agricultural or natural in 100 of 100 cases | `proxy_checks.json` | **Verified (as consistency, not accuracy)** |
| P3 | Without map context the model abstains 9× more often — 74.6% vs 8.3% — and its median score falls from 0.79 to 0.48 | `proxy_checks.json` ablation, 180 vs 169 detections | **Verified** |
| P4 | Agreement with the FIRMS static-source flag | — the `type` field is not retained by our normalisation, so there is nothing to compare against | **NOT VERIFIED — unavailable, and the most valuable of these to add** |
| P5 | "Our classifier is 94% accurate" | — **this is the misreading P1 invites and it is false.** Agreement with map context where the map has an opinion | **NEVER SAY THIS** |

---

## G. Engineering

| # | Claim | Evidence | Status |
|---|---|---|---|
| G1 | 414 automated tests pass | `cd backend && .venv/Scripts/python.exe -m pytest -q` → `414 passed` | **Verified** |
| G2 | `npm run smoke` is green | 81/81 across ten groups | **Verified** |
| G7 | The app renders identically regardless of the OS colour preference | `scripts/checks/theme.mjs` — Live, Past and the card captured under both a light and a dark preference, pixel-identical, with `color-scheme: light`, white panels, dark ink and light clusters asserted by computed style | **Verified** |
| G8 | The boundary outline appears only when tiles fail | Browser checks block both tile hosts and assert the note, 1 country path, 36 states, `fill: none` and that markers still render; the converse is asserted with tiles working | **Verified** |
| G3 | No secret is tracked, and none remains in history | Smoke group 1 (6 checks) scans tracked files **and** git history. The one historical leak was scrubbed with `git filter-repo`; only `backup-before-scrub` retains it, and the gate reports that explicitly | **Verified** |
| G4 | The GeoPackage is a valid OGC GeoPackage | `test_gis_export.py` (20) and smoke group 10 download it, write it to disk and parse it back: application id, 4 layers, SRS 4326, valid geometry headers | **Verified** |
| G5 | The GeoPackage opens in QGIS or ArcGIS | — not opened in either on this machine; `ogrinfo` is not installed | **NOT VERIFIED — say "valid by format checks and read-back"** |
| G6 | Inter is self-hosted, so the app looks identical offline | Bundled from `node_modules`, 6 woff2 subsets emitted by the build; no CDN font request | **Verified** |

---

## Standing limitations to volunteer

Say these before a judge has to ask. They land as rigour, not as weakness.

1. **The 1.0 metric is circular.** Never lead with it.
2. **Abnormality is assessable for only 4% of sites.** Honest, and thin. The fix
   is a denser archive, not more code.
3. **Coverage is six industrial regions**, not India.
4. **No per-event optical check.** A satellite basemap is not a Sentinel-2
   band-ratio test, and the drawer says "not available".
5. **Land cover is missing for ~half of detections**, reported as "not mapped".
6. **No SMS or email.** A webhook that can be relayed is not an SMS gateway.
7. **The official PS text is not in the repo.** Our requirement table is a
   reconstruction and is marked unverified.
8. **Panning runs at 18-32 fps**, below a 50 fps target. Zoom and replay reach
   it. The cost is Leaflet's tile repositioning rather than our markers.
9. **The proxy checks are consistency, not accuracy.** Never quote 93.9% as a
   correctness rate.

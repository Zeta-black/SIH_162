# FIRETRACE — Baseline (Phase 0)

Recorded 2026-10-25 on the round-2 working branch `sih-final`, from commit
`ec79406` (tagged `pre-sih-final`). Every number below was measured on this
machine, not estimated. Commands are given so each one can be re-run.

Environment: Windows 11 Pro 26100, Node v24.18.0, npm 11.16.0, Python 3.11.9.

---

## 1. What the project actually is

A FastAPI backend (≈12.8k lines Python) plus a React 18 / Vite 5 / Leaflet 1.9
dashboard (≈5.4k lines). Pipeline: NASA FIRMS detections → normalisation → OSM
facility + land-use context → recurrence features → Random Forest classifier
with an abstention gate → transparent weighted priority score → SQLite store →
REST API → dashboard.

The ingestion → classification → map path works. **This is not a rewrite
candidate.** The backend is in better shape than the UI, and is noticeably more
honest than most hackathon code I have read: provenance, abstention and
"unavailable" states are already first-class in the schema.

### Repo layout that matters

| Path | Role |
|---|---|
| `backend/app/api/routes.py` (917 ln) | 26 HTTP routes |
| `backend/app/schemas.py` (256 ln) | Canonical pydantic schema — single source of truth |
| `backend/app/services/classifier.py` (683 ln) | RF load, abstention, factor generation |
| `backend/app/services/priority.py` (175 ln) | Transparent weighted priority sum |
| `backend/app/services/replay.py` (959 ln) | Historical replay engine |
| `backend/ml/artifacts/` | Committed model + metrics + validation |
| `backend/app/data/demo_snapshot.json` | Frozen real FIRMS + OSM capture |
| `frontend/src/App.jsx` (390 ln) | Shell: 7-tab nav, command bar, status strip |
| `frontend/src/pages/` (7 files, 2.9k ln) | Operations, Incidents, Explore, Replay, Model, DataSources, Method |

### PS-162 framing

`docs/PS162_ALIGNMENT.md` exists and maps six PS needs to implementation with
per-row limitations. It refers to the problem as **SIH26162 / serial 162**. I
did not find an official verbatim PS title in the repo, so I am working from
the stated scope: *classify/segregate industrial thermal events from natural and
other thermal sources, using industrial databases and satellite thermal data,
with GIS-based storage, monitoring and visualisation.* Treated as an
assumption, not an official title.

---

## 2. Fresh-clone install — what a new person hits

Nothing was installed when I started (no `backend/.venv`, no
`frontend/node_modules`). So this was a genuine cold start.

```
npm run setup      → 458 s (7 min 38 s), exit 0
```

Install issues found:

1. **npm blocked esbuild's postinstall.** `npm warn allow-scripts esbuild@0.21.5
   (postinstall: node install.js)`. I verified the binary works anyway
   (`./node_modules/.bin/esbuild --version` → `0.21.5`), so Vite is fine *on
   this npm config* — but on a stricter `allow-scripts` setting this is a
   plausible fresh-clone breakage. Noted, not yet mitigated.
2. **Port 5173 was already occupied** by a stale process, so Vite silently moved
   to 5174. `scripts/dev.mjs` *does* guard ports and refuses to start — but I
   ran Vite directly, which has no such guard.
3. No `.env` existed; setup created it from the template. See §6.

---

## 3. Startup and latency — measured

Backend cold start to first `HTTP 200 /health`: **15 s** (loads the RF model,
the 716-event snapshot, 1482 facilities and 6021 land-use polygons at import).

| Endpoint (demo mode) | Status | Time | Payload |
|---|---|---|---|
| `/api/meta` | 200 | 0.008 s | 3.7 KB |
| `/api/model/info` | 200 | 0.007 s | 5.5 KB |
| `/api/sources` | 200 | 0.043 s | 8.9 KB |
| `/api/scenarios` | 200 | 0.006 s | 1.8 KB |
| `/api/dashboard/summary` | 200 | 0.020 s | 2.4 KB |
| `/api/incidents` | 200 | 0.019 s | 16 KB |
| `/api/events` | 200 | 0.210 s | 193 KB |
| **`/api/hotspots` (cold)** | 200 | **5.016 s** | **1.46 MB** |
| `/api/hotspots` (warm) | 200 | 0.094 s | 1.46 MB |
| `/api/hotspots/{id}` detail | 200 | 0.198 s | — |
| `/api/replay/catalogue` (cold) | 200 | **5.680 s** | 33 KB |
| **`/api/hotspots?mode=live` (cold, real FIRMS)** | 200 | **34.450 s** | 1.39 MB |

Reproduce: `curl -s -o /dev/null -w "%{http_code} %{time_total}s %{size_download}B" "http://127.0.0.1:8000/api/hotspots?bbox=68.0,6.5,97.5,36.0&days=1&mode=demo"`

Three things follow from this table:

- The 20-minute server cache is effective (5.0 s → 0.094 s). **Pre-warming is
  not a nicety, it is the difference between a working demo and a dead one.**
- A **34 s** cold live fetch on venue Wi-Fi is a demo-killer. The UI must never
  block on it.
- 1.46 MB for 500 events is ~2.9 KB/event, and `model` (397 B) + `disclaimer`
  (244 B) are byte-identical on every single event — ~320 KB of pure
  duplication that belongs at the envelope level.

---

## 4. The model — what it actually is

From `backend/ml/artifacts/metrics.json` and `backend/ml/data/dataset_manifest.json`:

- **Algorithm:** Random Forest, 48 features, 4 trained classes
  (`AGRICULTURAL_BURNING`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`, `INDUSTRIAL_FIRE`,
  `NATURAL_FIRE`), plus `UNKNOWN` emitted by an abstention gate at 0.45.
- **Reported metrics:** accuracy 1.0, balanced accuracy 1.0, macro-F1 1.0,
  OOB 0.9991, CV balanced-accuracy 0.9992 ± 0.001. Train 2279 / test 1235,
  split grouped by region (11 regions).
- **Label provenance:** weak supervision. 9 deterministic rules (`R0`–`R7`)
  over the same features the model sees. 3514 rows labelled, 7290 left
  unlabelled and excluded, 18 duplicate detections removed.
- **Class balance is severe:** `GAS_FLARE_OR_INDUSTRIAL_HEAT` 2534 vs
  `INDUSTRIAL_FIRE` **72**. The test set contains **8** INDUSTRIAL_FIRE rows.

**The 1.0 metrics are circular and the repo already says so.** `metrics.json`
carries `circularity_warning: true` and states that the figures measure
faithful reproduction of the labelling policy, not fire-classification skill,
and that a depth-3 tree and logistic regression score comparably. Credit where
due — the juniors documented this properly.

But a sharp judge will see "100% accuracy" and stop listening. **Any surface
that prints 1.0 as "accuracy" is a liability regardless of the footnote.** It
must be relabelled as policy-reproduction fidelity, with the circularity stated
first, not in a footnote.

Measured on the demo snapshot (716 events, 500 returned):

```
INDUSTRIAL_FIRE 85 · GAS_FLARE_OR_INDUSTRIAL_HEAT 70 · AGRICULTURAL_BURNING 276
NATURAL_FIRE 123 · UNKNOWN 162            priority: HIGH 36 · MEDIUM 465 · LOW 215
```

**UNKNOWN is genuinely populated — 162 of 716.** A real "Not sure" case exists
and does not need to be manufactured.

---

## 5. Defects found

### D1 — Abnormality is manufactured from missing history *(integrity, high)* — **FIXED**

`backend/app/services/priority.py:83`

```python
def abnormality(recurrence):
    if not recurrence.history_available:
        return 0.5
    return _clamp(1.0 - recurrence.persistence_ratio)
```

`history_available` is a *global* flag (is any history loaded at all), not a
per-location one. A location with `recurrence_count: 0`, `distinct_days: 0`,
`first_seen: null` therefore gets `persistence_ratio = 0.0` →
**`abnormality = 1.0`, "maximally unusual"**.

Measured: **351 of 500 events (70%) carry abnormality exactly 1.0**, and all
351 have zero prior detections at their location.

This conflates *"we watched this place and it never lit up"* (abnormal — fair)
with *"we have no coverage of this place"* (unknown — not abnormal). In this
snapshot it is mostly the latter: the capture spans 2025-11-11 → 2026-09-10 but
is built from ten 5-day windows (Oct–Nov 2025, Mar 2026), so a September 2026
event has an empty 60-day lookback *because the archive has no September data*,
not because the site is quiet. It inflates priority across 70% of the map and
is exactly the "never manufacture a normal from insufficient data" rule being
broken.

**Fixed in Phase 3.** `abnormality()` now returns `(value | None, status)` and
`compute_priority` renormalises the remaining weights when it cannot be
assessed. Measured effect: "needs attention" 11 -> 8, mean priority score
0.4403 -> 0.3868, and only 16 of 390 sites (4%) turn out to have enough
per-location history to assess at all. See `docs/MODEL_AUDIT.md` sections 4-5.

### D2 — Bad FIRMS key yields an empty map labelled "Live" *(reliability, high)*

With `FIRMS_MAP_KEY=deadbeef…`, `/api/hotspots?mode=live` returns HTTP 200 in
9.6 s with `returned: 0`, `firms_status: "not_configured"`, message *"NASA FIRMS
rejected the configured MAP_KEY"* — but **`mode: "live"`, `label: "Live NASA
FIRMS"`** and **no fallback to the snapshot**. The honest message is there; the
automatic recovery is not. A judge would see an empty map.

**Fixed in Phase 2.** Every failure now degrades live -> cached -> archive and
the resolved mode says which rung it landed on. Verified with a wrong key: 811
real cached detections, `state: "offline"`, `is_live: false`.

### D3 — First paint is a spinner on blank grey *(judge-facing, high)*

`App.jsx:371` — `if (meta.loading || meta.error) return <Boot/>` gates the
entire application on `/api/meta`. At 1920×1080 the landing route took **31.4 s**
to settle. `docs/screens/before/overview-1366x768.png` is the literal first
impression: a spinner and "Connecting to the analysis backend…" on an empty
page.

**Fixed in Phase 1.** The map screen renders immediately with skeletons and no
longer gates on `/api/meta`; measured interactive at 1,510 ms.

### D4 — Six React duplicate-key console errors *(quality)*

`CONSOLE ERRORS @1920x1080: 6` — *"Encountered two children with the same key"*.
Zero console errors is a definition-of-done item.

**Fixed in Phase 1.** The new map screen reports zero console errors at all
three viewports, asserted by smoke group 7.

### D5 — Factor text quality *(honesty, medium)*

Sampled factors include `"Geographic position (21.107, 72.646)"` as a
`supports` bullet (explains nothing) and `"Land cover here is unknown"` also as
`supports` (absence of evidence marked as supporting evidence — it belongs in
*missing*). Also a grammar bug: `"Detected on 1 separate days"`.

### D6 — Demo-mode window label contradicts the request *(provenance, medium)*

A `days=1` request in demo mode returns `date_range 2025-11-11 → 2026-09-10`.
The command bar then shows a 10-month span next to a "1d" selector.

### D7 — Model score rendered as a percentage *(honesty, medium)*

The Overview worklist prints `RF SCORE 97%`. The column name is defensible but
the `%` reads as a probability. `schemas.py` is explicit that this is an
uncalibrated vote share. Render as a score, not a percent.

---

## 6. Secrets

**A live NASA FIRMS key was sitting in `.env.example` in the working tree.**

```
.env.example:7:FIRMS_MAP_KEY=<a real 32-hex MAP_KEY, redacted>
```

Verified **not** in git history — `git log --all -p -- .env.example` shows only
`FIRMS_MAP_KEY=your_nasa_firms_map_key_here`. It was an uncommitted local edit:
someone pasted the real key into the template instead of into `.env`. No history
rewrite needed and none performed.

Action taken: copied to `.env` (confirmed ignored — `git check-ignore -v .env` →
`.gitignore:3:*.env`), restored the placeholder in `.env.example`. Working tree
is now clean against `HEAD`. Repo-wide scan for 32-hex strings over tracked
files returns nothing else.

The key is real and live mode works with it (§7), so it is presumably still
valid. **It was exposed to whoever has had access to this working copy — rotating
it before demo day is cheap insurance.** Flagged for a human; not something I
can do.

---

## 7. Live mode — verified working, but a poor demo today

`/api/hotspots?mode=live` with the real key returned **1770 real detections**
for India on 2026-10-25 (900 matching after filters), product
`VIIRS_NOAA20_NRT`, one product unavailable. So live ingestion genuinely works.

The problem is *what* is live today:

```
AGRICULTURAL_BURNING 795 · UNKNOWN 104 · INDUSTRIAL_FIRE 1 · GAS_FLARE 0 · NATURAL_FIRE 0
```

Late October is Punjab stubble-burning season. A live national view right now is
a map of crop fires with a single industrial detection. It proves the feed is
real; it does not show the product discriminating. **The demo must open live for
credibility and then move to the labelled archive for the interesting cases** —
which is what the brief already mandates, now with a measured reason.

---

## 8. Tests

```
cd backend && .venv/Scripts/python.exe -m pytest -q
→ 279 passed, 1 warning in 81.17 s
```

Nine test files covering firms, geo features, events, incidents, labeling,
priority, store/API, model honesty, end-to-end. The one warning is an upstream
`anyio` deprecation in starlette's testclient, not ours. No frontend tests and
no browser test exist.

---

## 9. The UI problem, stated plainly

The mentor's feedback is correct and the screenshots make it objective.

The landing route is `/ops` — **there is no map on the first screen at all.**
It is a KPI wall of 6 tiles, a 30-row × 9-column table, two bar charts, an
acquisition block, a 6-step "evidence chain", a disclaimer and a 7-cell status
strip. Well over 200 numbers are visible at once; the budget is five.

On `/explore` (the actual map) the map is a grey rectangle occupying roughly a
third of the viewport, flanked by a left filter rail (5 class checkboxes, 3
priority checkboxes, a vote-score slider, a proximity dropdown, a persistence
checkbox, 2 layer checkboxes, 3 basemap buttons), a floating 8-line legend, a
right inspector, and a 9-column detections table below. ~30 competing controls.

Everything is dark "console" styling. Nothing about it reads as Google Maps.

**Conclusion: keep the backend, rebuild the shell.** The seven pages hold real
working functionality, so Phase 1 demotes them behind a single secondary link
rather than deleting them.

---

## 10. Unverified claims to resolve

- `README.md` is 43 KB and grep reports it as binary (encoding/BOM issue) — it
  could not be claim-scanned in this pass. Phase 5 rewrites it anyway.
- `docs/` holds 19 files including three overlapping "final report" documents
  (`FINAL_GAP_CLOSURE_REPORT`, `FINAL_READINESS_REPORT`,
  `FINAL_READ_ONLY_TECHNICAL_GAP_AUDIT`). Not yet audited for stale claims.
- `docs/ROADMAP_v2.md` **does not exist** in this repo. The brief treats it as
  the juniors' roadmap to mine for ideas; I could not read it. The ideas named
  in the brief (evidence-gated classification, UNKNOWN, facility baselines,
  separating score/abnormality/priority) are implemented or partly implemented
  already, so I am proceeding from the brief's summary of it.
- No Lighthouse or axe run yet — no accessibility or performance score should be
  quoted until Phase 4.

---

## 11. Before screenshots

`docs/screens/before/` — 14 files, both viewports:
`overview`, `alerts`, `map`, `replay`, `model`, `history`, `system` ×
`1366x768`, `1920x1080`.

# Phase 2.5 result

Closing the gaps that prevented the system from being technically demonstrable.
Completed 16 September 2026. Every figure below was produced by executing
something, not by reading code.

**Summary: all P0 and P1 items delivered.** 273 backend tests pass, the smoke
test passes 21/21 against a live server, and the pipeline benchmarks clean at
10, 100 and 1000 events.

---

## 1. Replay engine status

**Delivered.** `backend/app/services/replay.py`.

A replay takes one verified historical FIRMS detection and pushes it back
through the production code path, timing each stage. It calls the same functions
the live dashboard calls — there is no parallel "demo" implementation.

| Stage | Real function invoked |
|---|---|
| `INGEST` | `snapshot_service.load_snapshot()` |
| `VALIDATE` | `HotspotEvent.model_validate()` (the real Pydantic schema) |
| `DEDUPLICATE` | `event_id` identity |
| `ENRICH` | `SpatialGrid` / `landcover` / `HistoryIndex` |
| `FEATURES` | `features.build_feature_row()` |
| `ML_INFERENCE` | `classifier.predict_batch()` |
| `RISK_PRIORITY` | `priority.compute_priority()` |
| `CLUSTER` | `events.cluster()` |
| `ALERT` | `incidents.alert_for()` |
| `PERSIST` | `store.upsert_events()` / `incidents.sync()` |

**What was explicitly not done:** no precomputed alert is inserted, no alert is
hardcoded to `true`, and no stage is a timed animation. The alert level comes
from evaluating the rule on the clustered event.

**One design decision worth stating.** The brief lists clustering before feature
extraction. Our pipeline clusters *after* classification, because a fire event's
class is a confidence-weighted vote of its members' classes — the members must
be classified first. The replay reports the order the code actually runs rather
than a tidier one invented for a diagram.

API: `GET /api/replay/catalogue`, `GET /api/replay/case/{id}`,
`POST /api/replay/run/{id}`.

## 2. Number of replay cases

**30 cases across 12 scenarios**, all drawn from 716 real NASA FIRMS detections
captured between 2025-11-11 and 2026-09-10.

| Scenario | Cases |
|---|---:|
| Critical alert | 3 |
| Routine flare, suppressed | 3 |
| Evidence gate abstains | 3 |
| Repeated detections | 3 |
| High radiative power | 3 |
| Multi-detection event | 3 |
| High-priority outcome | 3 |
| Low-priority outcome | 2 |
| High-confidence detection | 2 |
| Low-confidence detection | 2 |
| Isolated detection | 2 |
| Duplicate-data test | 1 |

Each scenario is a **predicate over a genuinely computed outcome**, so a scenario
the data does not support simply does not appear. Every case carries full
provenance (event ID, date, time, lat, lon, source, satellite, confidence, FRP,
detection count) and every one reports **`GROUND TRUTH: UNKNOWN`**.

All 30 were executed to produce `TEST_CASES.md`: **30 completed all ten stages,
0 failed.** Median end-to-end 620 ms.

## 3. End-to-end test result

**`backend/tests/test_end_to_end.py` — 31 tests, all passing.**

It drives the real backend workflow, not the frontend. Tests that matter most:

- `test_alert_level_is_computed_not_asserted` — replays 12 cases and fails if
  they all return the same alert level.
- `test_timestamps_are_generated_not_hardcoded` — two runs must differ.
- `test_measured_durations_vary_between_runs` — same, for durations.
- `test_the_same_event_replayed_twice_raises_one_alert`.
- `test_re_alert_after_closure_is_logged_not_silent`.
- `test_new_to_resolved_persists_at_every_step` — re-reads from the API after
  each action, so in-memory-only state would fail.

Full suite: **273 passed**.

## 4. Latency measurements

Instrumented per stage with `perf_counter` (monotonic), wall-clock UTC
timestamps recorded at execution time.

Representative critical-case replay:

| Stage | Measured |
|---|---:|
| Ingestion | 1.4 ms |
| Validation + dedup | 0.3 ms |
| Enrichment | 21.0 ms |
| Feature extraction | 0.2 ms |
| **ML inference** | **101.0 ms** |
| Risk / priority | 0.8 ms |
| Clustering | 1.1 ms |
| Alert generation | 0.01 ms |
| **End-to-end platform** | **~600 ms** |

**Source latency is kept strictly separate and is not added to ours.** For
snapshot records the panel is flagged **NOT A LATENCY MEASUREMENT**: the
detection was observed months before we captured it, because the snapshot was
fetched in bulk. That gap measures when we ran the capture, not how fast NASA
published, and presenting it as an upper bound would have been technically true
and practically useless.

NASA does not publish a per-record "available at" timestamp in the area CSV API,
so true source latency is not measurable from this interface at all. We say so
rather than estimate it.

## 5. Performance results

Full detail in `PERFORMANCE_RESULTS.md`. Measured on Windows 11 (build
10.0.26100), 8 logical CPUs, 7.8 GB RAM, Python 3.11.9, scikit-learn 1.9.1,
SQLite.

| Events | Total | Per event | ML | Clustering | DB | Failures |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 322 ms | 32.2 ms | 236 ms | 4 ms | 8 ms | 0 |
| 100 | 1,122 ms | 11.2 ms | 231 ms | 62 ms | 10 ms | 0 |
| 1000 | 5,781 ms | 5.8 ms | 445 ms | 671 ms | 46 ms | 0 |

Peak RSS 202–209 MB. **1000 events was reached**, so no scale had to be
documented as unreachable.

Two honest notes carried in the report:

- **Enrichment dominates, not ML.** At 1000 events enrichment is 4.6 s of the
  5.8 s total. The interesting optimisation target is the geospatial lookup, not
  the model.
- **1000 exceeds the 716 real detections available**, so the benchmark cycles
  through the real set rather than fabricating rows. This makes the *clustering*
  figure optimistic — repeated detections share coordinates and collapse into
  the same events — and the report says so.

## 6. Duplicate-alert test

**Passing, at three levels.**

- Unit/E2E: `test_the_same_event_replayed_twice_raises_one_alert` — second run
  returns `created=0, updated=1`.
- Smoke test against a live server: same result.
- Visible in the UI: replaying twice shows *"Replayed again — no second alert."*

**Mechanism:** identity-based, keyed on the `event_id` derived from the event's
first detection time and position. A repeat observation resolves to the same id
and lands on the existing incident.

**On cooldown:** there is deliberately no timer, and the reason is now published
via `/api/incidents` → `alert_rule.cooldown`. A timed cooldown would be the wrong
mechanism — it would also suppress a genuinely new fire starting nearby inside
the window. Identity de-duplication does not have that failure mode.

**Gap found and closed during this phase.** A resolved incident whose event
alerted again was being silently `UPDATE`d, so a genuine re-ignition would have
been invisible. Now:

- re-alert after closure → written to the audit log, status **not** changed
  (reopening is an operator decision)
- alert level rising on an open incident → logged as an escalation

Both are counted in the sync result and published in the alert rule summary.

## 7. Alert workflow test

**Passing.** `NEW → ACKNOWLEDGED → ASSIGNED → MONITORING → RESOLVED`, persisted
in SQLite and re-read from the API after every action.

- Illegal transitions are rejected with HTTP 409 (verified live: `acknowledge`
  from `DISPATCHED` → 409).
- Re-running the analysis never resets an acknowledgement.
- Every action is appended to an immutable log with actor, from-status,
  to-status and note.
- The UI offers only the actions the server says are available, so it cannot
  request a transition the server would reject.

## 8. ML honesty status

**Unchanged and preserved, as instructed.** Nothing in this phase softened the
Phase 2 conclusions.

- `circularity_warning: true` still emitted by `ml/train.py` at balanced
  accuracy ≥ 0.98, with its explanatory note.
- The baseline comparison (depth-3 tree 0.997, logistic regression 1.000,
  Random-Forest lift **0.000**) is intact.
- The abstention analysis over 7,290 policy-abstained rows is intact.
- The Model page leads with a red panel stating the 1.000 is **a warning, not a
  result**.
- Eight new tests in `test_model_honesty.py` fail if the disclosure is removed,
  including one asserting the phrase "accuracy claim" always arrives negated.
- The smoke test fails if the API reports ≥ 0.98 without the warning flag.

Nowhere does the system say "100% accuracy". No marketing language was added.

## 9. UI status

**Delivered.** New **Demo** tab implementing the requested flow: select event →
view source record → replay → processing timeline → result → alert →
acknowledge/assign/resolve.

Consistent with the existing console language: no gradients, no glassmorphism,
no decorative cards, no fake metrics, no unverified percentages. Stage bars are
scaled from measured durations, and while a replay is running the panel says
plainly that timings appear when the run completes, because *there is nothing
truthful to show until then*.

Two real bugs fixed while in here:

- `<Note kind="danger">` on the Model page was not a valid kind, so the "no
  trained model loaded" warning — the loudest message on the page — rendered
  unstyled. Now `alarm`.
- The Model page's "inflated by location leakage" panel had become factually
  wrong: the grouped split now scores *higher* than the CV/OOB figures it
  labelled as inflated. Replaced with the circularity disclosure.

ML detail stays one level deeper on the Model page, not on the operational
dashboard, as instructed.

## 10. Smoke test

**PASS — 21 checks, 0 failures, 0 errors.** Executed against a live uvicorn, not
FastAPI's `TestClient`, because `TestClient` bypasses the network and the ASGI
server. Full evidence table in `SMOKE_TEST.md`. Run with `npm run smoke`.

**A real finding.** The first run reported `KEY LEAKED in ['/api/sources']`.
Investigated immediately: it was a false positive in the check itself — the
endpoint contains the literal word `MAP_KEY` inside the documentation string
`"Public API, free MAP_KEY, server-side only"`. The key value was never exposed.
The check now compares against the configured secret value rather than the word,
across five endpoints, and never prints the secret.

## 11. Remaining limitations

Unchanged from Phase 2 unless noted, and none of these are hidden in the UI.

1. **No ground truth exists for any detection.** Every classification is a model
   output. This is the ceiling on every ML claim in the project.
2. **The 1.000 score is circular** — see `ML_MODEL_CARD.md`. Industrial fire
   rests on 72 labelled and 8 test rows.
3. **No temporal validation.** Train and test share a 48-day window; the split
   is spatial. We claim generalisation to unseen *places*, not unseen *time*.
4. **Source latency is not measurable** from the FIRMS area CSV API, which
   publishes no per-record availability timestamp.
5. **Single process, single node, SQLite.** No queue, no worker pool, no
   scheduled ingestion, no authentication. The PostGIS schema exists in
   `postgis_schema.sql` but is not wired.
6. **Alerts are in-dashboard only.** No email, SMS or webhook delivery is
   implemented, and none is simulated.
7. **Replay runs on the snapshot, not the live feed.** That is deliberate — it
   makes the demo deterministic and network-independent — but it means replay
   does not exercise the FIRMS HTTP client.
8. **The 1000-event benchmark cycles real detections** because only 716 exist,
   which flatters the clustering figure specifically.
9. **OSM coverage bounds the context.** An unmapped facility cannot be used as
   evidence; the gate abstains rather than guessing.
10. **This remains a prototype.** Not certified for operational emergency
    response. Every prediction requires human verification.

---

## How to verify all of this yourself

```bash
npm run setup
npm run dev            # then open http://localhost:5173 → Demo tab
npm test               # 273 backend tests
npm run smoke          # 21 live-server checks (needs npm run dev running)
npm run benchmark      # regenerates PERFORMANCE_RESULTS.md
```

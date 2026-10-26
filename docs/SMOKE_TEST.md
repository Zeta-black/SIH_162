# Smoke test

**Verdict: PASS** — 21 passed, 0 failed, 0 errored.

Executed 26 October 2026, 05:21 UTC against a live server at `http://127.0.0.1:8099`.
Reproduce with `python scripts/smoke_test.py` from `backend/` while the
server is running.

This talks HTTP to a real uvicorn process rather than using FastAPI's
TestClient, because TestClient bypasses the network and the ASGI server —
a test that passes there can still describe a system nobody can reach.

| # | Check | Result | Evidence | Time |
|---:|---|---|---|---:|
| 1 | Server is reachable | **PASS** | HTTP 200, status=ok | 10 ms |
| 2 | NASA key is not exposed by any endpoint | **PASS** | configured key absent from all 5 endpoints checked | 232 ms |
| 3 | Model reports its circularity warning | **PASS** | balanced_accuracy=1.0, circularity_warning=True | 3 ms |
| 4 | Replay catalogue is available | **PASS** | 30 cases in 4 ms | 4 ms |
| 5 | Every case declares ground truth UNKNOWN | **PASS** | all 30 cases report UNKNOWN | 0 ms |
| 6 | Every case carries source provenance | **PASS** | 6 provenance fields present on every case | 0 ms |
| 7 | Replay executes the full pipeline | **PASS** | 10/10 stages ok in 319 ms (314 ms server-side) | 320 ms |
| 8 | Stage timings are measured, not zero | **PASS** | slowest stage ML_INFERENCE at 102.4 ms | 0 ms |
| 9 | Timestamps differ between two runs | **PASS** | 2026-10-26T05:21:58.086136+00:00 != 2026-10-26T05:21:58.407238+00:00 | 305 ms |
| 10 | Source latency is separated from platform latency | **PASS** | platform end-to-end 314.7 ms, source reported separately with caveat | 0 ms |
| 11 | Alert levels differ across cases | **PASS** | distribution across 10 cases: {'CRITICAL': 3, 'None': 7} | 3593 ms |
| 12 | Replaying the same event raises no second alert | **PASS** | created=0 updated=1 — one fire, one incident | 289 ms |
| 13 | Incident workflow persists across requests | **PASS** | MONITORING --dispatch--> DISPATCHED, log 8 -> 9 entries | 56 ms |
| 14 | Illegal transitions are rejected | **PASS** | 'acknowledge' from DISPATCHED rejected with HTTP 409 | 7 ms |
| 15 | Alert rule publishes dedup and cooldown policy | **PASS** | deduplication, cooldown and escalation policy all published | 6 ms |
| 16 | Meta endpoint responds | **PASS** | HTTP 200 in 2 ms | 2 ms |
| 17 | Sources endpoint responds | **PASS** | HTTP 200 in 6 ms | 6 ms |
| 18 | Events endpoint responds | **PASS** | HTTP 200 in 3136 ms | 3136 ms |
| 19 | Incidents endpoint responds | **PASS** | HTTP 200 in 13 ms | 13 ms |
| 20 | Dashboard summary responds | **PASS** | HTTP 200 in 8 ms | 8 ms |
| 21 | Unknown replay case returns 404, not 500 | **PASS** | HTTP 404 with a message, no stack trace | 2 ms |

## What this does and does not establish

It establishes that the server starts, that the replay pipeline executes all
ten stages on real historical data, that stage timings are measured rather
than hardcoded, that the alert rule produces different answers for different
inputs, that replaying one event twice does not raise two alerts, and that
the incident workflow persists across separate HTTP requests.

It does **not** establish that any classification is correct. No ground truth
exists for any FIRMS detection in this dataset. See `docs/ML_MODEL_CARD.md`.


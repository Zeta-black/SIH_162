# Smoke test

**Verdict: PASS** — 21 passed, 0 failed, 0 errored.

Executed 25 October 2026, 17:23 UTC against a live server at `http://127.0.0.1:8099`.
Reproduce with `python scripts/smoke_test.py` from `backend/` while the
server is running.

This talks HTTP to a real uvicorn process rather than using FastAPI's
TestClient, because TestClient bypasses the network and the ASGI server —
a test that passes there can still describe a system nobody can reach.

| # | Check | Result | Evidence | Time |
|---:|---|---|---|---:|
| 1 | Server is reachable | **PASS** | HTTP 200, status=ok | 36 ms |
| 2 | NASA key is not exposed by any endpoint | **PASS** | configured key absent from all 5 endpoints checked | 364 ms |
| 3 | Model reports its circularity warning | **PASS** | balanced_accuracy=1.0, circularity_warning=True | 4 ms |
| 4 | Replay catalogue is available | **PASS** | 30 cases in 5 ms | 5 ms |
| 5 | Every case declares ground truth UNKNOWN | **PASS** | all 30 cases report UNKNOWN | 0 ms |
| 6 | Every case carries source provenance | **PASS** | 6 provenance fields present on every case | 0 ms |
| 7 | Replay executes the full pipeline | **PASS** | 10/10 stages ok in 364 ms (360 ms server-side) | 364 ms |
| 8 | Stage timings are measured, not zero | **PASS** | slowest stage PERSIST at 111.2 ms | 0 ms |
| 9 | Timestamps differ between two runs | **PASS** | 2026-10-25T17:23:36.571143+00:00 != 2026-10-25T17:23:36.934464+00:00 | 186 ms |
| 10 | Source latency is separated from platform latency | **PASS** | platform end-to-end 360.3 ms, source reported separately with caveat | 0 ms |
| 11 | Alert levels differ across cases | **PASS** | distribution across 10 cases: {'CRITICAL': 3, 'None': 7} | 3886 ms |
| 12 | Replaying the same event raises no second alert | **PASS** | created=0 updated=1 — one fire, one incident | 245 ms |
| 13 | Incident workflow persists across requests | **PASS** | ACKNOWLEDGED --dispatch--> DISPATCHED, log 2 -> 3 entries | 22 ms |
| 14 | Illegal transitions are rejected | **PASS** | 'acknowledge' from DISPATCHED rejected with HTTP 409 | 8 ms |
| 15 | Alert rule publishes dedup and cooldown policy | **PASS** | deduplication, cooldown and escalation policy all published | 7 ms |
| 16 | Meta endpoint responds | **PASS** | HTTP 200 in 2 ms | 2 ms |
| 17 | Sources endpoint responds | **PASS** | HTTP 200 in 7 ms | 7 ms |
| 18 | Events endpoint responds | **PASS** | HTTP 200 in 2924 ms | 2924 ms |
| 19 | Incidents endpoint responds | **PASS** | HTTP 200 in 7 ms | 7 ms |
| 20 | Dashboard summary responds | **PASS** | HTTP 200 in 7 ms | 7 ms |
| 21 | Unknown replay case returns 404, not 500 | **PASS** | HTTP 404 with a message, no stack trace | 2 ms |

## What this does and does not establish

It establishes that the server starts, that the replay pipeline executes all
ten stages on real historical data, that stage timings are measured rather
than hardcoded, that the alert rule produces different answers for different
inputs, that replaying one event twice does not raise two alerts, and that
the incident workflow persists across separate HTTP requests.

It does **not** establish that any classification is correct. No ground truth
exists for any FIRMS detection in this dataset. See `docs/ML_MODEL_CARD.md`.


"""End-to-end smoke test against a RUNNING server.

Run:  python scripts/smoke_test.py                (from the backend/ directory)
      python scripts/smoke_test.py --base http://127.0.0.1:8000

Why a live server rather than FastAPI's TestClient: TestClient bypasses the
network, the ASGI server and the startup path. A smoke test that passes in
TestClient can still be a system nobody can actually reach. This one talks HTTP
to a real uvicorn, the way the browser does.

Every check reports PASS, FAIL or ERROR with the evidence it was decided on:

    PASS    the assertion held, and the observed value is printed
    FAIL    the server answered, but the answer was wrong
    ERROR   the check could not complete (server down, exception)

Exit code is 0 only if there are no FAILs and no ERRORs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "SMOKE_TEST.md"

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"


class Report:
    def __init__(self, base: str) -> None:
        self.base = base
        self.rows: list[dict] = []
        self.started = datetime.now(timezone.utc)

    def record(self, name: str, status: str, evidence: str, ms: float = 0.0) -> None:
        self.rows.append(
            {"name": name, "status": status, "evidence": evidence, "ms": round(ms, 1)}
        )
        mark = {PASS: "PASS ", FAIL: "FAIL ", ERROR: "ERROR"}[status]
        print(f"  [{mark}] {name:<52} {evidence}")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r["status"] in (FAIL, ERROR))

    def counts(self) -> dict[str, int]:
        return {
            s: sum(1 for r in self.rows if r["status"] == s) for s in (PASS, FAIL, ERROR)
        }


def check(report: Report, name: str):
    """Decorator-free helper: wraps a check so an exception becomes ERROR."""

    class _Ctx:
        def __enter__(self):
            self.t0 = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                ms = (time.perf_counter() - self.t0) * 1000
                report.record(name, ERROR, f"{exc_type.__name__}: {exc}", ms)
                return True  # swallow; the report carries the failure
            return False

        def ok(self, evidence: str) -> None:
            report.record(name, PASS, evidence, (time.perf_counter() - self.t0) * 1000)

        def bad(self, evidence: str) -> None:
            report.record(name, FAIL, evidence, (time.perf_counter() - self.t0) * 1000)

    return _Ctx()


def run(base: str) -> Report:
    report = Report(base)
    client = httpx.Client(base_url=base, timeout=180.0)

    print(f"\nFIRETRACE smoke test against {base}")
    print("=" * 78)

    # ---- reachability ------------------------------------------------------
    with check(report, "Server is reachable") as c:
        r = client.get("/health")
        if r.status_code == 200:
            c.ok(f"HTTP 200, status={r.json().get('status')}")
        else:
            c.bad(f"HTTP {r.status_code}")

    if report.failed:
        print("\nServer unreachable — the remaining checks cannot run.")
        client.close()
        return report

    # ---- the NASA key must never leave the backend -------------------------
    with check(report, "NASA key is not exposed by any endpoint") as c:
        # Test for the CONFIGURED SECRET VALUE, not for the word "MAP_KEY".
        # The sources endpoint legitimately contains the string "MAP_KEY" while
        # documenting that a key is required and held server-side; matching on
        # the word flags that documentation as a breach. The only thing that
        # actually matters is whether the secret itself appears.
        #
        # The key value is never printed by this script, only compared.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.config import settings  # noqa: PLC0415

        secret = (getattr(settings, "firms_map_key", "") or "").strip()
        paths = ("/health", "/api/meta", "/api/sources", "/api/model/info", "/api/incidents")
        leaked = []
        assigned = []
        for path in paths:
            body = client.get(path).text
            if secret and len(secret) >= 8 and secret in body:
                leaked.append(path)
            # A key pasted into a URL would look like MAP_KEY=<value>.
            if "map_key=" in body.lower():
                assigned.append(path)
        if leaked:
            c.bad(f"THE CONFIGURED KEY VALUE APPEARS IN {leaked}")
        elif assigned:
            c.bad(f"a MAP_KEY=... assignment appears in {assigned}")
        elif not secret:
            c.ok(f"no key configured; {len(paths)} endpoints carry no MAP_KEY assignment")
        else:
            c.ok(f"configured key absent from all {len(paths)} endpoints checked")

    # ---- model honesty -----------------------------------------------------
    with check(report, "Model reports its circularity warning") as c:
        info = client.get("/api/model/info").json()
        metrics = info.get("metrics", {})
        ba = metrics.get("balanced_accuracy")
        if ba is None:
            c.bad("no balanced_accuracy in the payload")
        elif ba >= 0.98 and not metrics.get("circularity_warning"):
            c.bad(f"balanced accuracy {ba} with no circularity_warning")
        else:
            c.ok(
                f"balanced_accuracy={ba}, circularity_warning="
                f"{metrics.get('circularity_warning')}"
            )

    # ---- replay catalogue --------------------------------------------------
    catalogue = None
    with check(report, "Replay catalogue is available") as c:
        t = time.perf_counter()
        r = client.get("/api/replay/catalogue")
        catalogue = r.json()
        build_ms = (time.perf_counter() - t) * 1000
        if r.status_code != 200 or not catalogue.get("available"):
            c.bad(f"HTTP {r.status_code}, available={catalogue.get('available')}")
        elif catalogue["case_count"] < 20:
            c.bad(f"only {catalogue['case_count']} cases; the brief asks for 20-30")
        else:
            c.ok(f"{catalogue['case_count']} cases in {build_ms:.0f} ms")

    if not catalogue or not catalogue.get("cases"):
        client.close()
        return report

    with check(report, "Every case declares ground truth UNKNOWN") as c:
        bad = [x["case_id"] for x in catalogue["cases"] if x["ground_truth"] != "UNKNOWN"]
        if bad:
            c.bad(f"{len(bad)} case(s) claim known ground truth: {bad[:3]}")
        else:
            c.ok(f"all {len(catalogue['cases'])} cases report UNKNOWN")

    with check(report, "Every case carries source provenance") as c:
        required = ("event_id", "date", "latitude", "longitude", "source", "satellite")
        missing = [
            x["case_id"] for x in catalogue["cases"] if any(x.get(f) is None for f in required)
        ]
        if missing:
            c.bad(f"{len(missing)} case(s) missing provenance: {missing[:3]}")
        else:
            c.ok(f"{len(required)} provenance fields present on every case")

    # ---- a real replay -----------------------------------------------------
    # Pick a case that should alert, so persistence and the workflow are exercised.
    critical = next(
        (x for x in catalogue["cases"] if x["scenario"] == "CRITICAL_PRIORITY_EVENT"),
        catalogue["cases"][0],
    )
    run_body = None
    with check(report, "Replay executes the full pipeline") as c:
        t = time.perf_counter()
        r = client.post(f"/api/replay/run/{critical['case_id']}", params={"persist": "true"})
        ms = (time.perf_counter() - t) * 1000
        if r.status_code != 200:
            c.bad(f"HTTP {r.status_code}: {r.text[:180]}")
        else:
            run_body = r.json()
            stages = [s["stage"] for s in run_body["stages"]]
            failed_stages = [s["stage"] for s in run_body["stages"] if not s["ok"]]
            if failed_stages:
                c.bad(f"stages failed: {failed_stages}")
            elif len(stages) != 10:
                c.bad(f"expected 10 stages, got {len(stages)}: {stages}")
            else:
                c.ok(f"10/10 stages ok in {ms:.0f} ms ({run_body['run']['total_ms']:.0f} ms server-side)")

    if run_body is None:
        client.close()
        return report

    with check(report, "Stage timings are measured, not zero") as c:
        zero = [s["stage"] for s in run_body["stages"] if s["duration_ms"] <= 0.0]
        slowest = max(run_body["stages"], key=lambda s: s["duration_ms"])
        if len(zero) > 3:
            c.bad(f"{len(zero)} stages reported 0 ms: {zero}")
        else:
            c.ok(f"slowest stage {slowest['stage']} at {slowest['duration_ms']:.1f} ms")

    with check(report, "Timestamps differ between two runs") as c:
        first = run_body["run"]["started_at"]
        r2 = client.post(f"/api/replay/run/{critical['case_id']}", params={"persist": "false"})
        second = r2.json()["run"]["started_at"]
        if first == second:
            c.bad("two runs reported an identical start time — timestamps are hardcoded")
        else:
            c.ok(f"{first} != {second}")

    with check(report, "Source latency is separated from platform latency") as c:
        lat = run_body["latency"]
        caveat = lat["source"]["caveat"].lower()
        disclaimed = any(
            p in caveat for p in ("upper bound", "not meaningful", "cannot be computed")
        )
        if not disclaimed or "not our platform latency" not in caveat:
            c.bad(f"source latency is not properly disclaimed: {caveat[:90]}")
        else:
            c.ok(
                f"platform end-to-end {lat['end_to_end_platform_ms']:.1f} ms, "
                "source reported separately with caveat"
            )

    # ---- alert is computed, not hardcoded ----------------------------------
    with check(report, "Alert levels differ across cases") as c:
        levels = {}
        for case in catalogue["cases"][:10]:
            rr = client.post(f"/api/replay/run/{case['case_id']}", params={"persist": "false"})
            if rr.status_code == 200:
                lvl = rr.json()["result"].get("alert_level")
                levels[str(lvl)] = levels.get(str(lvl), 0) + 1
        if len(levels) < 2:
            c.bad(f"every case produced the same alert level: {levels}")
        else:
            c.ok(f"distribution across 10 cases: {levels}")

    # ---- duplicate-alert protection ----------------------------------------
    event_id = run_body["result"].get("event_id")
    with check(report, "Replaying the same event raises no second alert") as c:
        again = client.post(
            f"/api/replay/run/{critical['case_id']}", params={"persist": "true"}
        ).json()
        persistence = again["persistence"]
        if persistence.get("created", 0) != 0:
            c.bad(f"a second incident was created: {persistence}")
        else:
            c.ok(
                f"created={persistence.get('created')} updated={persistence.get('updated')} "
                "— one fire, one incident"
            )

    # ---- incident workflow, persisted --------------------------------------
    if event_id and run_body["result"].get("alert_raised"):
        with check(report, "Incident workflow persists across requests") as c:
            before = client.get(f"/api/incidents/{event_id}")
            if before.status_code != 200:
                c.bad(f"incident {event_id} was not persisted (HTTP {before.status_code})")
            else:
                # Drive whatever transition is legal from the CURRENT state and
                # assert the status really moved. This script runs against a
                # shared database, so the incident can be in any state —
                # asserting a fixed target would let the check pass by accident
                # whenever the incident happened to already be there.
                record = before.json()
                start = record["status"]
                offered = set(record.get("available_actions", []))
                # Prefer forward progress. `dismiss` is legal from NEW but
                # leaves the demo database with a dismissed incident, which is
                # a poor state to hand back to whoever runs this next.
                preference = ["acknowledge", "dispatch", "monitor", "reopen", "resolve", "dismiss"]
                available = [a for a in preference if a in offered]
                if not available:
                    c.bad(f"incident is {start} with no legal transition available")
                else:
                    action = available[0]
                    logged_before = len(record["actions"])
                    client.post(
                        f"/api/incidents/{event_id}/action",
                        json={"action": action, "actor": "smoke-test"},
                    )
                    after = client.get(f"/api/incidents/{event_id}").json()
                    if after["status"] == start:
                        c.bad(f"'{action}' from {start} did not change the status")
                    elif len(after["actions"]) <= logged_before:
                        c.bad("the transition was not written to the action log")
                    else:
                        c.ok(
                            f"{start} --{action}--> {after['status']}, "
                            f"log {logged_before} -> {len(after['actions'])} entries"
                        )

        with check(report, "Illegal transitions are rejected") as c:
            record = client.get(f"/api/incidents/{event_id}").json()
            cur = record["status"]
            allowed = set(record.get("available_actions", []))
            # Derive an action the server itself says is NOT available from here,
            # rather than assuming a particular current state.
            illegal = next(
                (
                    a
                    for a in ("acknowledge", "dispatch", "resolve", "reopen", "monitor")
                    if a not in allowed
                ),
                None,
            )
            if illegal is None:
                c.bad(f"every action is legal from {cur} — the state machine is not constraining")
            else:
                r = client.post(
                    f"/api/incidents/{event_id}/action", json={"action": illegal}
                )
                if r.status_code != 409:
                    c.bad(f"'{illegal}' from {cur} returned HTTP {r.status_code}, expected 409")
                else:
                    c.ok(f"'{illegal}' from {cur} rejected with HTTP 409")

    # ---- the alert rule publishes its contract -----------------------------
    with check(report, "Alert rule publishes dedup and cooldown policy") as c:
        rule = client.get("/api/incidents").json()["alert_rule"]
        missing = [k for k in ("deduplication", "cooldown", "escalation") if k not in rule]
        if missing:
            c.bad(f"rule does not publish: {missing}")
        else:
            c.ok("deduplication, cooldown and escalation policy all published")

    # ---- core dashboard endpoints still work -------------------------------
    for path, label in (
        ("/api/meta", "Meta endpoint"),
        ("/api/sources", "Sources endpoint"),
        ("/api/events?mode=demo&days=3&limit=20", "Events endpoint"),
        ("/api/incidents", "Incidents endpoint"),
        ("/api/dashboard/summary?mode=demo&days=3", "Dashboard summary"),
    ):
        with check(report, f"{label} responds") as c:
            t = time.perf_counter()
            r = client.get(path)
            ms = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                c.bad(f"HTTP {r.status_code}")
            else:
                c.ok(f"HTTP 200 in {ms:.0f} ms")

    # ---- degradation -------------------------------------------------------
    with check(report, "Unknown replay case returns 404, not 500") as c:
        r = client.post("/api/replay/run/NOPE::EVT-NOTHING", params={"persist": "false"})
        if r.status_code == 404:
            c.ok("HTTP 404 with a message, no stack trace")
        else:
            c.bad(f"HTTP {r.status_code}")

    client.close()
    return report


def write_report(report: Report) -> None:
    counts = report.counts()
    verdict = "PASS" if report.failed == 0 else "FAIL"
    ts = report.started.strftime("%d %B %Y, %H:%M UTC")

    lines: list[str] = []
    a = lines.append
    a("# Smoke test")
    a("")
    a(f"**Verdict: {verdict}** — {counts[PASS]} passed, {counts[FAIL]} failed, "
      f"{counts[ERROR]} errored.")
    a("")
    a(f"Executed {ts} against a live server at `{report.base}`.")
    a("Reproduce with `python scripts/smoke_test.py` from `backend/` while the")
    a("server is running.")
    a("")
    a("This talks HTTP to a real uvicorn process rather than using FastAPI's")
    a("TestClient, because TestClient bypasses the network and the ASGI server —")
    a("a test that passes there can still describe a system nobody can reach.")
    a("")
    a("| # | Check | Result | Evidence | Time |")
    a("|---:|---|---|---|---:|")
    for i, row in enumerate(report.rows, 1):
        mark = {PASS: "**PASS**", FAIL: "**FAIL**", ERROR: "**ERROR**"}[row["status"]]
        evidence = row["evidence"].replace("|", "\\|")
        a(f"| {i} | {row['name']} | {mark} | {evidence} | {row['ms']:.0f} ms |")
    a("")
    if report.failed:
        a("## Failures")
        a("")
        for row in report.rows:
            if row["status"] in (FAIL, ERROR):
                a(f"- **{row['name']}** — {row['evidence']}")
        a("")
    a("## What this does and does not establish")
    a("")
    a("It establishes that the server starts, that the replay pipeline executes all")
    a("ten stages on real historical data, that stage timings are measured rather")
    a("than hardcoded, that the alert rule produces different answers for different")
    a("inputs, that replaying one event twice does not raise two alerts, and that")
    a("the incident workflow persists across separate HTTP requests.")
    a("")
    a("It does **not** establish that any classification is correct. No ground truth")
    a("exists for any FIRMS detection in this dataset. See `docs/ML_MODEL_CARD.md`.")
    a("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="FIRETRACE end-to-end smoke test.")
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()

    report = run(args.base)
    counts = report.counts()

    print("=" * 78)
    print(
        f"  {counts[PASS]} PASS   {counts[FAIL]} FAIL   {counts[ERROR]} ERROR"
    )
    verdict = "PASS" if report.failed == 0 else "FAIL"
    print(f"  VERDICT: {verdict}")
    print("=" * 78)

    write_report(report)
    print(f"\nreport -> {REPORT_PATH}")
    sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    main()

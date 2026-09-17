# Demo script

A seven-minute walkthrough a judge can follow without knowing the source code.
Everything below is a real screen doing real work — there is no scripted
animation and no pre-recorded result anywhere in this flow.

## Before you start

```bash
npm run setup      # once
npm run dev        # backend on :8000, dashboard on :5173
```

Open **http://localhost:5173** and go to the **Demo** tab.

If the network is down, everything below still works: the demo runs on a frozen
snapshot of real NASA FIRMS and OpenStreetMap data held locally.

---

## The one-sentence framing

> NASA tells us *where* something hot is. We work out *what* it is — and
> specifically whether it is an industrial fire rather than a crop fire, a
> forest fire, or a gas flare that burns every single day.

---

## 1 · Select a historical event (30 seconds)

The left column lists 30 replayable cases, grouped by what each one tests. Every
case is a genuine FIRMS detection from the frozen snapshot, with its real date,
coordinates, satellite, confidence and radiative power.

**Pick `Critical alert → EVT-5F0A7E4E3D12`** (16 March 2026, 21.51 N 86.70 E,
VIIRS SNPP, 15.36 MW).

Point at the **GROUND TRUTH: UNKNOWN** line and say it out loud before anyone
asks:

> We have no field report for this pixel. Nobody drove out to check. So we can
> demonstrate that our pipeline works, but we cannot claim our answer is
> verified — and we would rather say that than have you discover it.

## 2 · View the source record (30 seconds)

The panel shows exactly what NASA gave us, nothing added: event ID, acquisition
date and time, latitude, longitude, product, satellite, instrument, confidence,
FRP, brightness. The `Retrieved by` line at the bottom is the actual request
that fetched it.

## 3 · Press REPLAY EVENT (1 minute)

This runs the real backend pipeline. Ten stages, each timed:

| Stage | What it does |
|---|---|
| `INGEST` | Reads the historical source records around this detection |
| `VALIDATE` | Re-validates every record against the FIRMS schema |
| `DEDUPLICATE` | Drops repeat observations by detection identity |
| `ENRICH` | Nearest industrial facility, OSM land cover, recurrence history |
| `FEATURES` | Builds the 48-feature vector |
| `ML_INFERENCE` | Random Forest + the abstention gate |
| `RISK_PRIORITY` | Weighted priority score |
| `CLUSTER` | Groups detections into one fire event |
| `ALERT` | Evaluates the alert rule |
| `PERSIST` | Writes detections and the incident to the database |

**Say this while it runs:**

> These timings are measured with a monotonic clock during the run you just
> triggered. Press it again and they will be different. Nothing here is a
> progress bar pretending to be work.

Typical total: **~600 ms**, with ML inference the largest single stage.

## 4 · The latency panel (45 seconds)

Two clearly separated blocks, and the separation is the point.

- **SOURCE** — when the satellite observed it, and when it reached us. For
  snapshot records this is flagged **NOT A LATENCY MEASUREMENT**, because the
  snapshot was captured in bulk months after the observation. The gap measures
  when we ran the capture, not how fast NASA published.
- **OUR PLATFORM** — the per-stage figures above, and one end-to-end number.

> We refuse to add those two together. NASA's satellite revisit and publication
> delay is hours and is not ours to claim credit for or blame. What we control
> is the sub-second part, and that is the only number we put our name to.

## 5 · The result (1 minute 30)

Classification, priority score, detection count, nearest facility, land cover,
persistence.

Then scroll to **WHY THIS PRIORITY?** — the six weighted components with their
actual values and weights.

> There is no unexplained AI score anywhere in this system. Priority is a
> transparent weighted sum you can recompute by hand. The model contributes one
> of those six inputs, and it is labelled.

## 6 · The alert (1 minute)

For this case: **CRITICAL**, with the reasons listed.

Now the part worth dwelling on. **Go back to the case list and pick
`Routine flare, suppressed → EVT-DBBAD725C280`** — Hazira, 50 detections,
36 MW, seen on many separate days. Replay it.

It comes back **HIGH, not CRITICAL.**

> This is the most important behaviour in the product. That is a gas flare on a
> refinery. It burns every day, it is hot, and a naive system would page
> somebody about it every single night until they turned the alerts off. We
> detect that it is persistent and we deliberately refuse to escalate it.
> A system that cries wolf is worse than no system.

## 7 · Duplicate protection (30 seconds)

Replay the **same** critical case a second time. The Alert panel now shows:

> **Replayed again — no second alert.** Created 0, updated 1.

> One fire, one incident. Incident identity is derived from the event's first
> detection time and position, so a repeat observation lands on the existing
> incident instead of paging anyone twice. If it had been closed and started
> burning again, that gets written to the audit log as a re-alert rather than
> silently reopening — reopening is a human decision.

## 8 · The operator workflow (1 minute)

On the alerting case, use the Response panel:

**Acknowledge → Assign (type a team name) → Monitor → Resolve**

After each action the action log grows. Refresh the page — the state is still
there.

> This is persisted server-side in SQLite, not React state. Try resolving one
> without acknowledging it first: the server returns 409 and refuses. The audit
> log cannot contain an impossible sequence.

## 9 · Close on the model page (1 minute)

Go to **Model**. The first thing on the screen is a red panel saying our score
of 1.000 is a **warning, not a result**.

> Our classifier scores a perfect 1.000 on regions it has never seen. We do not
> present that as an accuracy claim. We tried to beat ourselves with trivial
> models: a three-question decision tree scores 0.997, and plain logistic
> regression ties us exactly at 1.000. Our lift over the best baseline is zero.
>
> That proves the labels are circular — they come from a rule policy over the
> same features the model sees, so any model just recovers the rules. We audited
> separately for data leakage and it is clean.
>
> Our flagship class, industrial fire, rests on 72 labelled examples and only 8
> in the test set. We tell you that because eight samples is an anecdote, not a
> measurement.
>
> The training script raises this warning itself. We did not wait to be caught.

---

## Questions you should expect, and the short answers

**"Is this real-time?"**
No, and we never say it is. NASA FIRMS near-real-time products publish roughly
1–3 hours after overpass. We process in under a second once we have the data.
Those are different numbers and we report them separately.

**"Your model scores 100%, that's obviously fake."**
It is real, reproducible, and not an accuracy claim — see section 9. We found it
and documented it before you asked.

**"So the AI detects fires?"**
No. NASA detects the thermal anomaly. We classify what it most likely is, and
abstain when the evidence is insufficient. About 23% of ambiguous detections get
no verdict at all.

**"What happens when NASA goes down?"**
The dashboard switches to the historical snapshot and says so in the status bar.
It does not show stale data pretending to be live.

**"Can you prove it isn't hardcoded?"**
Replay any two cases and compare. Different inputs give different
classifications, different priorities and different alert levels — including no
alert at all for 10 of the 30 cases. Run `npm run smoke` for 21 automated checks
against a live server, including one that fails if two runs report identical
timestamps.

---

## If something goes wrong on stage

- **Backend unreachable** — the dashboard says "Link down" rather than showing
  stale numbers. Restart with `npm run dev`.
- **A replay fails** — the failing stage turns red and shows the exception. That
  is the honest behaviour; talk through what the stage was doing.
- **Overpass is slow** — irrelevant to this demo. Replay runs entirely on the
  local snapshot.

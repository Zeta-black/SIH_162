# Notification policy

Policy version **1.0.0**. Every notification FIRETRACE sends carries this
version and a reason code, both visible in the interface, so a recipient can ask
"why did I get this?" and get an exact answer.

The governing idea: **a notification is a claim that someone should look at
something.** An alert nobody acts on is worse than no alert, because it teaches
people to ignore the next one. So this policy is mostly about what we *don't*
send.

---

## 1. What triggers a notification

Four triggers. Nothing else sends anything.

| Reason code | Trigger | Severity | Wording template |
|---|---|---|---|
| `NEEDS_ATTENTION` | A site enters **Needs attention**, or escalates within it | high | "Needs attention at {site}" |
| `ABNORMAL_PERSISTENT` | A persistent source with an **assessed baseline** shows heat clearly above its own history | high | "Unusual heat at {site} — above its normal range" |
| `NEW_HEAT_AT_FACILITY` | A detection on or near a mapped facility with **no prior heat history** there | medium | "New heat detected at {site}" |
| `SYSTEM_FEED_DELAYED` | The feed has been delayed beyond `NOTIFY_FEED_DELAY_HOURS` (default 6) | low | "Satellite feed delayed — last update {age}" |
| `SYSTEM_WEBHOOK_FAILED` | A webhook delivery failed after all retries | low | "Alert delivery to your webhook failed" |

### What never triggers one

- **Normal**, **Watch** and **Not sure** statuses. They live on the map. A "Not
  sure" event that also needs urgency reaches the operator through the Needs
  attention queue, not through a push.
- Anything in **Past data** mode. See §5.
- A site that was already notified inside its cooldown, unless severity rose.

### Wording constraints, enforced by test

A notification may never contain: `confirmed`, `definitely`, `certain`,
`guaranteed`, `100%`, `real-time`, `instant`, `AI-powered`. The phrase is
"New heat detected at X", never "Fire confirmed at X" — FIRETRACE classifies
thermal detections and does not confirm fires.

`ABNORMAL_PERSISTENT` requires `abnormality_status == "assessed"`. A site whose
baseline could not be assessed can never produce an "above its normal range"
claim, because there is no normal range to be above. This is the notification
equivalent of the Pass 1 abnormality defect and is tested directly.

---

## 2. Hygiene — how we avoid alert fatigue

| Control | Default | What it does |
|---|---|---|
| **De-duplication** | per site + reason | One open notification per (site, reason). A repeat updates the existing row rather than creating another. |
| **One bell per site per evaluation** | — | A site can qualify for several reasons at once (a new detection on a facility footprint is both `NEEDS_ATTENTION` and `NEW_HEAT_AT_FACILITY`). Only the most severe reason speaks; two bells for one event is the fatigue this policy exists to avoid. |
| **Cooldown** | 6 h (`NOTIFY_COOLDOWN_HOURS`) | After notifying about a site, the same reason stays quiet for this long. |
| **Escalation override** | — | Cooldown is bypassed when severity rises (medium → high). A worsening situation is not held back by a timer. |
| **Hysteresis** | 0.05 priority (`NOTIFY_HYSTERESIS`) | A site must fall this far below the threshold before it can re-trigger. Stops a value sitting on 0.65 from flapping on every poll. |
| **Daily cap for system notices** | 6/day (`NOTIFY_SYSTEM_DAILY_CAP`) | A flapping network cannot flood the panel. Operational alerts are never capped. |
| **Quiet on first run** | — | The first analysis after a cold start seeds state without notifying, or every existing Needs-attention site would alert at once. |

### State machine

```
created ──seen──> acknowledged ──> resolved
   │                   │
   └──snoozed(6 h)─────┘        (snooze returns to created when it expires)
```

Every transition is stored with a timestamp. Nothing is deleted; `resolved` is a
state, so the history of what was alerted and when is auditable.

---

## 3. Channels

All free. No SMS or email is built in.

| Channel | Default | Behaviour |
|---|---|---|
| **In-app centre** | always on | Bell at top-right with an unread dot. Grouped *Needs attention* / *System*, newest first. Actions: Open on map · Acknowledge · Snooze 6 h. Fully keyboard operable. |
| **Toast** | always on | One at a time, bottom-left, for new **high** severity only. Auto-dismisses after 8 s. Never covers the detail card. Suppressed under `prefers-reduced-motion` (the item still appears in the bell). |
| **Browser notification** | opt-in | Requested only when the user clicks "Enable browser alerts" in the bell panel — never on page load. High severity only. |
| **Webhook** | off unless `FIRETRACE_WEBHOOK_URL` is set | Generic JSON with a `text` field that Slack, Teams and Discord all render. 3 attempts with exponential backoff, 8 s timeout, one audit row per attempt. |

### Webhook payload

```json
{
  "text": "FIRETRACE · Needs attention at ArcelorMittal Nippon Steel India",
  "firetrace": {
    "policy_version": "1.0.0",
    "reason_code": "NEEDS_ATTENTION",
    "severity": "high",
    "site_id": "FE-2026-43C5",
    "site_name": "...",
    "status": "needs_attention",
    "verdict": "...",
    "observed_at": "...",
    "link": "http://localhost:5173/?site=FE-2026-43C5",
    "is_test": false,
    "replay": false
  }
}
```

`is_test` is `true` for anything sent by "Send test alert", and the `text` is
prefixed `[TEST]`. A recipient can therefore always distinguish a drill from a
real alert without reading the JSON.

---

## 4. Delivery and timing

- The UI subscribes to a lightweight **changes-since** endpoint, polled every
  45 s. Chosen over Server-Sent Events because a poll survives a proxy that
  buffers, which is the likely venue network.
- Upstream FIRMS polling is unchanged and still respects the provider's limits
  and the 20-minute analysis cache. Notifications are evaluated from the
  analysis the app already has; they never cause an extra NASA request.
- New items appear with a brief ring. **The map never moves on its own** while
  the user is panning or has a card open — a "2 new" pill appears instead.

---

## 5. Replay safety

In **Past data** mode, `provenance.alerts_suppressed` is `true` and the
notification evaluator runs in preview only:

- It computes what *would* have fired and shows it as a list titled
  **"Would have alerted"**, clearly marked replay.
- It writes nothing to the notification store.
- It sends no toast, no browser notification and no webhook.

This is checked at the single point where notifications are created, not at each
channel, so a new channel cannot forget to honour it. Tested directly:
`test_replay_sends_nothing`.

---

## 6. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `FIRETRACE_WEBHOOK_URL` | unset | Outbound webhook. Disabled when empty. |
| `NOTIFY_COOLDOWN_HOURS` | 6 | Per site + reason quiet period. |
| `NOTIFY_FEED_DELAY_HOURS` | 6 | Feed age before a system notice. |
| `NOTIFY_SYSTEM_DAILY_CAP` | 6 | Maximum system notices per day. |
| `NOTIFY_HYSTERESIS` | 0.05 | Priority margin before re-triggering. |
| `NOTIFY_ENABLED` | true | Master switch. |

---

## 7. What this policy does not do

- **No SMS or email.** The webhook can be relayed to either by a free automation
  tool (a Zapier/Make/n8n webhook step, or a Slack workflow). We do not claim to
  send SMS, and nothing in the product does.
- **No escalation chains, on-call rotas or acknowledgement deadlines.** A real
  deployment would want them; this has a single shared queue.
- **No per-user routing.** There are no user accounts, so every viewer sees the
  same notifications. Acknowledgement is shared state.
- **No guarantee of delivery.** The webhook retries three times and then records
  a failure. It is not a message queue.

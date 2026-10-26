# FIRETRACE — 3-minute demo script

SIH 2026 · PS 26162 (NTRO, Disaster Management). Written to be read aloud and
followed click-by-click.

**Before you start:** `npm run demo` is running, the browser is at
`http://localhost:5173/`, and `npm run prewarm` has been run on the venue
network. See `DEMO_DAY_CHECKLIST.md`.

Everything below uses **real NASA FIRMS detections and real OpenStreetMap
facilities** from the committed archive. Nothing is simulated. If you say a
number, it is on screen.

### Bookmark these before you start

Each opens one exact site, so no step depends on where something sits in a list.

| | Link |
|---|---|
| A · Needs attention (new heat) | `http://localhost:5173/?demo=1&site=FE-2026-43C5` |
| B · Normal (persistent source) | `http://localhost:5173/?demo=1&site=FE-2026-4BA6` |
| C · Not sure | `http://localhost:5173/?demo=1&site=FE-2026-66C8` |

Clicking through the UI is the better demo — it shows the product working. The
links are the Plan B for every step and never go stale.

---

## The spine

**One plant. Two detections. Opposite answers.**

Both at **ArcelorMittal Nippon Steel India, Hazira, Gujarat**, 230 m apart.

| | A | B |
|---|---|---|
| FIRETRACE says | **Needs attention** | **Normal** |
| Why | New heat — nothing recorded here before | Persistent source — seen on 8 days |
| Peak radiative power | 4.16 MW | **36.33 MW** |
| Abnormality for that site | not assessed (no history) | **11/100**, from 8 days |

The one we flag is **8.7× cooler** than the one we call normal. A brightness
threshold gets this exactly backwards. That contrast *is* the product.

---

## 0:00 – 0:20 · The problem

> "Satellites see thousands of hot spots over India every day. A plant safety
> officer does not need another list of hot pixels — they need to know which ones
> matter. FIRETRACE answers that on one map, in plain words, and tells you when it
> is not sure."

**Do nothing. Let them look at the screen.**

Point at the top-left:

> "Live, and underneath it, how old the data actually is. That line ticks. It is
> computed from the satellite observation time, not from when we started the app."

**Hover the freshness line** for one second:

> "Exact time in IST and UTC, the source, and the honest caveat — FIRMS publishes
> a few hours after the pass. We say near-real-time, and we show you the age."

**Plan B** — if Live is empty, that is a real state and it says so: *"No new
detections in the last 24 h."* Say *"quiet today — here is the archive"* and go
to Past data.

---

## 0:20 – 0:50 · Past data, and the archive

**Click `Past data`** → pick **1-10 Sep 2026**.

> "This list is generated from what we actually hold — no hard-coded weeks."

The blue rule and banner appear.

> "Past data. Unmistakable, and it says *no alerts are sent*. A replay can never
> look live and can never fire a real alert — that is enforced in one place in
> the backend and tested directly."

Point at the top-left summary:

> "Seven need attention, eight to watch, eighteen normal, ten not sure.
> Forty-three sites from a hundred and ninety-six raw detections."

**Plan B** — if the picker is empty, press F5. The archive needs no network.

---

## 0:50 – 1:40 · The contrast that is the whole product

**Search `Arcelor`** → pick the **Needs attention** result. *(Plan B: link A.)*

> "A steel plant at Hazira. Red. And the reason in one sentence —"

**Read the verdict verbatim:**

> *"Heat on the ArcelorMittal Nippon Steel India site with an episodic signature,
> consistent with an abnormal fire rather than routine operation, so far on a
> single pass."*

Point at the badge beside the status chip:

> "**New heat.** Nothing has ever been recorded at this spot before."

Point at the grey box:

> "And what we are *not* sure about — one pass only, not corroborated yet. On the
> main screen, not in a footnote."

**Now search `Arcelor` again → pick the Normal result.** *(Plan B: link B.)*

> "Same plant. Two hundred and thirty metres away."

Point at the badge:

> "**Persistent source — seen on 8 days.** And read the number: **thirty-six
> megawatts**. The one we flagged was **four**. This is nearly nine times hotter,
> and we are telling you to ignore it."

Point at the heat band:

> "Because that green band is this site's *own* usual range, measured from its own
> history. Thirty-six megawatts is normal here. That is a furnace doing its job.
>
> A brightness threshold would flag this and miss the other one. Knowing what is
> normal *for this specific site* is what turns a detection feed into something a
> safety officer can act on."

**Plan B** — if you cannot find the green marker, the point survives verbally.
Say the two numbers and move on.

---

## 1:40 – 2:05 · When we do not know

**Search `coal`** → **Block - B coal mine**. *(Plan B: link C.)*

> "Grey. Not sure. The model's leading class did not clear our reporting
> threshold, so we do not publish a guess."

> "Ten of these forty-three sites are 'not sure'. We would rather say that than
> raise a false alarm at a plant."

**Open `See evidence` → `Details for experts`** and point at one row:

> "*Abnormality for this site: not assessed — too little history here.* We only
> have enough history at four percent of sites. Where we don't, we say so instead
> of inventing a number. That was the worst bug in our last build and we fixed it
> by making the answer smaller and true."

This is the trust moment. Do not rush it.

---

## 2:05 – 2:35 · Notifications

**Close the drawer. Click the bell (top right).**

> "This is the alerting side. Grouped: needs attention, and system notices. Each
> one is openable on the map, acknowledgeable, snoozeable."

Point at the replay line at the top of the panel:

> "Right now it says *would have alerted* — because we are in Past data. Nothing
> was sent. No toast, no browser notification, no webhook."

Point at the footer:

> "And the line that matters: **Normal, Watch and Not sure never notify.** They
> stay on the map. An alert nobody acts on teaches people to ignore the next
> one, so we only push three things — a site entering 'needs attention', unusual
> heat at a source that *has* a baseline, and new heat at a mapped facility. Six
> hour cooldown, de-duplicated per site, and escalation overrides the cooldown."

**Click the gear** for one second:

> "Policy version 1.0.0, browser alerts are opt-in, and there is a test alert that
> is labelled TEST everywhere it appears."

---

## 2:35 – 3:00 · It is a real system, and it does not fall over

**Open the Layers popover (bottom-right) → `Download GIS data`.**

> "Four GIS layers — detections, persistent sources, facilities, alerts — as
> GeoJSON or one GeoPackage in WGS 84. A pollution control board lives in QGIS,
> not in our web page. We test that file by reading it back, not by trusting that
> we wrote it."

**Click `Satellite`.**

> "And satellite imagery for context."

**Then, the reliability line. Turn the Wi-Fi off if you can.**

> "The archive needs no network at all. If the live feed goes down mid-demo, the
> app keeps working, keeps showing the real last-good data, and keeps telling you
> how old it is. We built for a bad venue network because that is the most likely
> thing to go wrong."

**Close with:**

> "One map. Plain words. An honest 'not sure'. And it runs with one free NASA key,
> or none at all."

---

## What not to say

- Do **not** say "100% accurate", or quote the 1.0 metrics. If accuracy comes up,
  `JUDGE_QA.md` Q3 — the honest answer is a strength.
- Do **not** say "real-time". Say **near-real-time** and show the age.
- Do **not** call the model score a probability.
- Do **not** say "nationwide". Say "the six industrial regions in our archive".
- Do **not** claim we confirm fires. We classify thermal detections.
- Do **not** claim a per-event optical/Sentinel-2 check. We have a satellite
  basemap; the drawer says "Optical check: not available".
- Do **not** mention other teams.

---

## If everything breaks

1. **F5.** Most things are a stale render.
2. **`?demo=1`** in the URL — forces the archive, no network.
3. **Restart:** Ctrl+C, then `npm run demo:offline`. ~20 s. Ports auto-step if
   something else holds 5173.
4. **The screen recording** on the USB stick. Say *"our laptop is struggling with
   the venue network, here is a recording of the same flow"*, then keep talking
   over it. The story still lands.

# FIRETRACE — 3-minute demo script

SIH 2026, PS 162. Written to be read aloud and followed click-by-click.

**Before you start:** `npm run demo` is already running, the browser is open at
`http://localhost:5173/?demo=1`, and `npm run prewarm` has been run on whatever
network the venue has. See `DEMO_DAY_CHECKLIST.md`.

**Bookmark these three links before the demo.** Each opens one exact site, so no
step depends on where something happens to sit in a list:

| | Link |
|---|---|
| A · Needs attention | `http://localhost:5173/?demo=1&site=FE-2026-43C5` |
| B · Normal (routine flare) | `http://localhost:5173/?demo=1&site=FE-2026-4BA6` |
| C · Not sure | `http://localhost:5173/?demo=1&site=FE-2026-66C8` |

Clicking through the UI is the better demo — it shows the product working. The
links are the Plan B for every step, and they never go stale.

Everything below uses **real NASA FIRMS detections and real OpenStreetMap
facilities** from the committed archive. Nothing in this script is simulated. If
you say a number, it is on screen.

---

## The spine of the demo

One plant. Two detections. Opposite answers.

Both are at **ArcelorMittal Nippon Steel India, Hazira, Gujarat**, 230 m apart.
The one we flag is **8.7× cooler** than the one we call normal. That single
contrast is the whole product, and it is the thing a judge will remember.

| | Site A | Site B |
|---|---|---|
| Status | **Needs attention** | **Normal** |
| Peak radiative power | 4.16 MW | **36.33 MW** |
| Prior detection days | 0 | 8 |
| Satellite passes | 1 | 13 |
| Observed | 2026-09-01 | 2026-09-10 |

A naive brightness threshold flags B and ignores A. That is backwards.

---

## 0:00 – 0:20 · The problem, in one sentence

> "Satellites see thousands of hot spots over India every day. A plant safety
> officer does not need another list of hot pixels — they need to know which
> ones matter. FIRETRACE answers that on one map, in plain words, and tells you
> when it is not sure."

**Do nothing. Just let them see the screen.**

Point at the top-left card:

> "Eight need attention, seventeen to watch, two hundred and fifty-four normal.
> Three hundred and ninety sites, from seven hundred and sixteen raw detections."

**Plan B** — if the map is blank: say "let me reload the saved archive", press
F5. The archive needs no network at all.

---

## 0:20 – 1:20 · The top event, and why

**Type** `Arcelor` in the search box and pick the **second** result — the one
marked *Needs attention* (the first is a different detection at the same plant).

The map flies in, the card opens on the right.

> Note: ArcelorMittal sits 5th in the *Needs attention first* list, not 1st —
> the top entries are gas/oil infrastructure sites. Searching is both faster and
> more reliable than counting rows. Plan B: open link **A** above.

> "This is a steel plant at Hazira. Red, needs attention. And here is the reason
> in one sentence —"

**Read the verdict aloud, verbatim from the screen:**

> *"Heat on the ArcelorMittal Nippon Steel India site with an episodic signature,
> consistent with an abnormal fire rather than routine operation, so far on a
> single pass."*

**Point at the three "why" lines:**

> "Four hundred and seventy metres onto the plant footprint. No previous
> detection at this location. Spread across 1.6 km."

Then — and this is the part to slow down for — **point at the grey box**:

> "And underneath, what we are *not* sure about. Only one satellite pass, so it
> is not corroborated yet. No optical confirmation. We say that on the main
> screen, not in a footnote."

**Plan B** — if the card does not open, click the red marker on the map. If that
fails, open link **A**.

---

## 1:20 – 2:00 · The same plant, the opposite answer

**Close the card** (× or Escape). **Search** `Arcelor` again and pick the
**third** result — the one marked *Normal*. Or click the green marker a couple of
centimetres from the red one. Plan B: open link **B** above.

> "Same plant. Two hundred and thirty metres away. Nine days later."

**Read the verdict:**

> *"Routine industrial heat on the ArcelorMittal Nippon Steel India site,
> detected on 8 separate days."*

Now the line that wins the room:

> "This one is **thirty-six megawatts**. The one we flagged was **four**. This is
> nearly nine times hotter — and we are telling you to ignore it, because this
> plant does this every few days. That is a furnace doing its job.
>
> A brightness threshold would have flagged this and missed the other one.
> Knowing what is *normal for this specific site* is what turns a detection feed
> into something a safety officer can act on."

**If you have a spare five seconds,** open *See evidence → Details for experts*
and point at **Abnormality for this site: 11/100**:

> "And that is measured, not asserted — this location has eight days of
> detection history behind it. For most sites in this archive we do not have
> enough history, and there the same row honestly reads *not assessed*."

**Plan B** — if you cannot find the green marker: the point survives verbally.
Say the two numbers, 36 MW normal versus 4 MW flagged, and move on.

---

## 2:00 – 2:30 · When we do not know

**Search** `coal` and pick **Block - B coal mine** — or click any grey marker.
Plan B: open link **C** above.

> "Grey. Not sure. The model's leading class scored 0.443, and our reporting
> threshold is 0.45. It did not clear the bar, so we do not publish a guess."

**Read the verdict:**

> *"Evidence is mixed — the leading class stayed below the reporting threshold,
> so FIRETRACE is not committing to one, on the Block - B coal mine site."*

> "There is good evidence here — three satellite passes, two different
> platforms, right on the mine. But the evidence points in different directions,
> so the honest output is 'not sure', not a confident label.
>
> A hundred and eleven of these three hundred and ninety sites are 'not sure'.
> We would rather say that than raise a false alarm at a plant."

This is the trust moment. Do not rush it.

---

## 2:30 – 3:00 · Evidence, and that it actually runs

**Click "See evidence".**

> "Everything behind that verdict: heat, place, history, context. Ticks for what
> supports it, warnings for what is missing. Including this —"

**Point at "What this is not":**

> *"Proximity to a facility is context, not proof of cause."*

> "We will not tell you a plant caused a fire because a hot pixel landed on it."

**Open "Details for experts".**

> "And for an evaluator: the model score, the priority, the version, observation
> time separate from retrieval time. We call it a model score, not a
> probability, because it is an uncalibrated vote share and we have not
> validated calibration."

**Close the drawer. Point at the chip in the top-left card.**

> "That chip is always on screen. Right now it says **Replay — real historical
> data**, because this is the committed archive. It is never allowed to say
> 'Live' unless we actually reached NASA in this request."

**If, and only if, you have more than ten seconds and working Wi-Fi** — click
**Try live**:

> "And that is today's feed, fetched now."

**Plan B** — this is the riskiest click in the demo. If it spins past about ten
seconds, click **Use archive** and say: *"Venue Wi-Fi. The app falls back to
saved data and says so — which is the behaviour we built for."* That is not an
excuse; it is the feature.

---

## What not to say

- Do **not** say "100% accurate" or quote the 1.0 metrics. If accuracy comes up,
  see `JUDGE_QA.md` Q3 — the honest answer is a strength, not a dodge.
- Do **not** call the model score a probability.
- Do **not** say "nationwide monitoring". Say "the six industrial regions in our
  archive, plus whatever today's live query returns".
- Do **not** claim the system confirms fires. It classifies thermal detections.
- Do **not** mention the competing team.

---

## If everything breaks

In order:

1. **F5.** Most things are a stale render.
2. **`?demo=1`** in the URL bar — forces the offline archive, no network.
3. **Restart:** Ctrl+C in the terminal, then `npm run demo:offline`. ~20 s.
4. **The screen recording** on the USB stick (`docs/demo/` — record it the night
   before). Say: *"Our laptop is struggling with the venue network, here is a
   recording of the same flow."* Then keep talking over it. The story still
   lands.

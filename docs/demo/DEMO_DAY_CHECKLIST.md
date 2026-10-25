# Demo day checklist

Work down it. Do not skip the night-before section — most of what can go wrong
is cheap to prevent and expensive to fix in the room.

---

## The night before

- [ ] **`git status` is clean** and you are on the branch you mean to demo.
- [ ] **Charge the laptop to 100%.** Pack the charger.
- [ ] **Run the full gate:** `npm run smoke` → expect `SMOKE PASS 50/50`.
      If anything is red, fix it tonight, not tomorrow.
- [ ] **Run `npm run demo`** and click the entire script end to end, out loud,
      with a timer. Three minutes is shorter than it sounds.
- [ ] **Run it again with Wi-Fi off.** It must still work. If it does not, stop
      and fix that before anything else.
- [ ] **Record a screen capture of a perfect run** (Win+Alt+R, or OBS). Save it
      to the USB stick *and* the desktop. This is the last-resort fallback and
      the only one that cannot fail.
- [ ] **Copy the whole repo to a USB stick**, including `backend/.venv` and
      `frontend/node_modules` if they fit. A second laptop with no internet can
      then run `npm run demo:offline`.
- [ ] **Charge your phone** and confirm the hotspot works. Note the password.
- [ ] **Print or screenshot `JUDGE_QA.md`.** Decide now who answers model
      questions and who drives the laptop.
- [ ] **Re-read the "What not to say" list** in `DEMO_SCRIPT.md`.
- [ ] **Decide whether the FIRMS key has been rotated.** If not, assume the
      current one may stop working and that the archive is your demo.

---

## One hour before

- [ ] **Plug in.** Do not demo on battery.
- [ ] **Connect to the venue Wi-Fi now** and find out whether it is usable.
      If there is a captive portal, accept it now — a portal interception is the
      single most likely cause of a "live" failure.
- [ ] **Run `npm run prewarm`.** This fills the archive cache and, if the network
      allows, the live cache too. It prints which. Under two minutes.
- [ ] **Start `npm run demo`** and leave it running. Do not restart it later.
- [ ] **Load the page once and let the map fully draw.** OpenStreetMap throttles
      rapid tile fetching, and this puts the tiles in the browser cache so the
      basemap is instant in the room.
- [ ] **Click through the three demo sites once** so the backend has them warm.
      Use the exact links, then bookmark them:
      - `?demo=1&site=FE-2026-43C5` — ArcelorMittal, Needs attention
      - `?demo=1&site=FE-2026-4BA6` — ArcelorMittal, Normal (the 36 MW flare)
      - `?demo=1&site=FE-2026-66C8` — Block - B coal mine, Not sure
- [ ] **Close everything else** — Slack, email, other browser profiles, anything
      that can raise a notification.
- [ ] **Turn off notifications** (Windows: Focus assist → Alarms only).

---

## Five minutes before

- [ ] **Display scaling 100%**, resolution 1366×768 or 1920×1080. The layout is
      tested at both. Do not demo at 125% on a small laptop screen — the
      floating panels will crowd.
- [ ] **Browser zoom at 100%** (Ctrl+0).
- [ ] **One browser window, one tab**, no bookmarks bar, no extensions sidebar.
      F11 for full screen if the chrome is distracting.
- [ ] **The tab is already on `http://localhost:5173/?demo=1`** with the map
      drawn and nothing selected.
- [ ] **The terminal is visible but not in front** — if a judge asks "is this
      really running?", you want to be able to show it in one keystroke.
- [ ] **Phone hotspot on standby**, not connected. Switch only if live fails and
      you decide live matters.
- [ ] **Glass of water.** Three minutes of talking is dry work.

---

## The 10-second recovery drills

Know these cold. Practise them.

| Symptom | Action |
|---|---|
| Map blank or stale | **F5** |
| Anything says "Live" but looks wrong | Click **Use archive** |
| Spinner past ~10 s on a live switch | Click **Use archive**, say the fallback line |
| Card will not open | Click the marker on the map instead of the list row |
| Search returns nothing | It only searches facility names — type `Arcelor` |
| Backend died (terminal shows an exit) | Ctrl+C, then `npm run demo:offline` — ~20 s |
| Port already in use | `FIRETRACE_WEB_PORT=5190 npm run demo:offline` |
| Everything is broken | Play the screen recording and keep narrating |

---

## Known risks, and what you say

**Venue Wi-Fi is unusable.**
Say: *"We built for this — the app falls back to saved data and labels it
honestly."* Then show the chip. This is a feature, not an excuse, and it is
worth saying out loud even if Wi-Fi works.

**The live view is boring today.**
Late October is Punjab stubble-burning season: a live national query returns
mostly agricultural burning and very few industrial detections. That is real and
correct. Open live briefly for credibility, then move to the archive for the
interesting cases. Do not try to find a dramatic industrial fire in the live
feed on stage.

**Basemap tiles do not load.**
OpenStreetMap throttles bulk fetching. Mitigated by loading the page once an
hour before so tiles are cached. If it still happens the markers and all the
panels still work — say *"the basemap is a public tile service and it's rate
limiting us; the data layer is ours and it's all here."*

**A judge asks about the 1.0 accuracy.**
`JUDGE_QA.md` Q3. Answer it directly and immediately — the circularity is
documented in the artefact and owning it reads as rigour. Do not get defensive
and do not let it hang.

**A judge asks whether this confirms fires.**
It does not. It classifies thermal detections and says how confident it is. Say
that plainly.

---

## After the demo

- [ ] Write down every question you could not answer well. That list is the real
      output of the day.
- [ ] Do not promise features on the spot.

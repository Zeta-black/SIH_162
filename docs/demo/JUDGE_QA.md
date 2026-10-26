# Judge Q&A

Questions a sharp evaluator is likely to ask, with answers that are true.

Rule for everyone answering: **if you do not know, say so and say what would be
needed to find out.** A confident wrong answer loses more than an honest "we
haven't validated that yet". Every number here is in `CLAIMS_REGISTER.md` with
its evidence.

---

### Q1. You say "Live" — how current is it really?

Near-real-time, and we show you exactly how near.

NASA FIRMS publishes VIIRS and MODIS detections **a few hours after the satellite
pass**. We never hide that. The line under the Live control is computed from the
newest *observation* timestamp on screen and ticks every 30 seconds; hovering it
gives the exact time in IST and UTC, the product, and the caveat in writing.

If the feed goes quiet the line says **"Feed delayed — last update 3 h ago"** and
the dot turns amber. If there is genuinely nothing, it says **"No new detections
in the last 24 h."** The label stays "Live" because that is the surface you are
on; the honesty lives in the age. What we refuse to do is the reverse — let stale
data look fresh.

**We deliberately do not say "real-time".** Nothing here is real-time and saying
so would be the easiest claim for you to puncture.

---

### Q2. Is the score a probability?

**No.** It is an uncalibrated Random Forest vote share for the leading trained
class. We label it "model score" everywhere, and the API says so in the payload
(`model.score_note`).

Turning it into a probability needs calibration against verified outcomes —
reliability curves, a Brier score — and we have no per-detection ground truth to
calibrate against. So we did not claim it.

Score, abnormality and priority are three separate fields for the same reason:
*what it is*, *how unusual it is here*, and *how urgently to look* are different
questions and collapsing them hides which one you are disagreeing with.

---

### Q3. What is your accuracy?

The question we most want to answer carefully, because the honest answer is more
useful than the flattering one.

The model scores **1.0 accuracy and 1.0 macro-F1** on a held-out, region-grouped
split. **That number is circular and you should discount it.** The training labels
are produced by a nine-rule policy over the same features the model sees, so a
high score measures how faithfully the forest reproduces that policy — not
whether it classifies fires correctly. A depth-3 decision tree and a logistic
regression score comparably on the same split, which is the giveaway.

It is recorded in the artefact itself: `metrics.json` carries
`"circularity_warning": true`.

**What we can honestly claim:** the pipeline reproduces a documented, inspectable
policy; it abstains when evidence is thin; and it separates classification from
urgency. **What we cannot claim:** validated real-world accuracy. That needs
incident reports from plant operators or a state pollution control board, which
is exactly the partnership this would need to become real.

---

### Q4. So how did you validate anything?

Four ways, none of which is "we trusted the metric":

1. **Leakage and duplication checks.** 18 duplicate detections removed before the
   split; the split is grouped by region, so one industrial cluster cannot appear
   in both train and test.
2. **Baseline comparison.** `ml/validate.py` fits a depth-3 tree and a logistic
   regression on the same split. They score comparably — which is *how we know*
   the metric reflects the policy rather than model skill.
3. **Behavioural tests.** 414 automated tests, including that an abstained event
   is never shown as a confident alarm, that a replay is never labelled live and
   never sends an alert, that a rejected API key still puts real data on the map,
   and that no notification can say a fire is confirmed.
4. **The evidence gate, measured.** On a live India-wide query in September —
   outside any crop-burning season — the ungated model called 810 of 900
   detections "agricultural burning" at a median score of 0.66. Of those, 800 had
   no land cover and 804 had no facility within 12 km: it was voting on position
   and radiative power alone. With the gate applied that falls to 164, and the
   rest are reported as unclassified with the reason stated.

What we have **not** done is compare against verified fires, because no such
labels exist in this project.

---

### Q4b. Have you checked the classifier against anything independent?

Yes, and we are careful about what it shows. `MODEL_AUDIT.md` §6 has four
**consistency checks on real detections** — run them with
`python -m ml.proxy_checks`:

- Recurring heat inside a mapped industrial site reads industrial in **92 of 98
  cases**, with six abstentions and **zero disagreements**.
- Single-day heat over vegetation far from industry reads agricultural or
  natural in **100 of 100**.
- Stripped of facility and land-cover context, the model **abstains 74.6% of the
  time instead of 8.3%**, and its median score falls from 0.79 to 0.48.

That third one is the one we would point at. A Random Forest with no facility
and no land cover is voting on position and radiative power alone and will still
return a confident-looking number; the evidence gate turns that into an
abstention, and this is the measurement showing it works on real data.

**What these are not:** accuracy. They compare the classifier against map
context, not against verified incidents. A 93.9% agreement figure means the
classifier and the map agree 93.9% of the time where the map has an opinion — it
does **not** mean 93.9% of classifications are right. We will not quote it that
way and you should not let anyone else.

One check is honestly unavailable: FIRMS carries a `type` field flagging known
static heat sources, which would be the only persistence judgement here not
derived from our own rules. **Our normalisation does not retain it.** It is the
most valuable thing on that page that we have not done.

---

### Q5. How do notifications work, and how do you avoid alert fatigue?

The policy is a document before it is code: `docs/NOTIFICATION_POLICY.md`,
version 1.0.0, and every notification carries that version and a reason code so a
recipient can ask "why did I get this?" and get an exact answer.

**What we deliberately do not send** is the more important half: **Normal, Watch
and Not sure never notify.** They stay on the map. Only three operational things
push — a site entering "needs attention", unusual heat at a source that actually
*has* a baseline, and new heat at a mapped facility with no history there.

Hygiene, all configurable and all tested: de-duplication per site and reason, a
6-hour cooldown, escalation that overrides the cooldown (a worsening situation is
not held back by a timer), 0.05 hysteresis so a value sitting on a threshold
cannot flap, a daily cap on system notices, one bell per site per evaluation, and
a quiet first run so a cold start does not alert on every pre-existing site at
once.

Channels are in-app, one toast at a time, opt-in browser notifications (permission
requested only on an explicit click, never on page load), and an optional webhook
with retry, backoff and an audit row per attempt.

**No SMS or email is built in.** The webhook can be relayed to either by a free
automation tool. We do not claim more than that.

---

### Q6. What happens when the feed is down?

We built for that, because a venue network is the most likely failure.

Three rungs, each honestly labelled:

1. **Live** — fetched from NASA in this request.
2. **Delayed** — the last successful fetch, read from disk, shown with its real
   age and an amber dot. Survives a restart, expires at 72 h.
3. **Past data** — the committed archive of real historical detections.

Verified: with a deliberately wrong API key the app serves **811 real cached
detections** with `is_live: false`, instead of the empty map under a green "Live"
badge that an earlier build showed. With the network unreachable and no cache it
falls to the archive — 390 sites, still working.

You can test it right now: turn off the Wi-Fi and press reload.

---

### Q7. How is this different from the NASA FIRMS viewer, which is free?

FIRMS tells you *where* heat is. It does not tell you whether that heat is a
refinery doing its job or a refinery on fire — which is the actual question, and
PS 26162's question.

Concretely, from this demo: FIRMS shows both ArcelorMittal detections as hot
pixels, and the 36 MW one looks far more alarming than the 4 MW one. **We invert
that**, because the 36 MW signature repeats at that site on 8 separate days and
the 4 MW one has never appeared there before. FIRMS has no concept of "normal for
this site".

We also group pixels into sites — 716 detections become 390 — so you triage
incidents rather than pixels, and we export the result as GIS layers you can open
in QGIS.

---

### Q8. What is actually novel here? Facility baselines and clustering are standard.

They are, and we will not claim otherwise. We are not claiming a new algorithm,
and we are not going to stand here and tell you nobody has done this.

What we think is worth your attention is a product decision: **the system is built
to be understood in ten seconds and to admit when it does not know.** A
first-time user reads a plain sentence, three reasons each traceable to a real
field, and an explicit list of what could not be checked. Ten of forty-three
sites say "not sure". The maths is one click away, not on the front page.

Similar components exist elsewhere. Our focus is making the output
understandable, honest and reliable in seconds, because an alert a safety officer
cannot act on is not an alert.

---

### Q9. Who is the user, and what do they do differently on Monday?

A plant safety officer, or a state pollution control board regulator.

Today they either do not look at satellite thermal data at all, or they look at a
raw FIRMS feed with no industrial context. With this they open one screen, see
which of their sites is behaving unusually, read why in one sentence, and either
dispatch someone or mark it reviewed. If they live in QGIS, they take the
GeoPackage instead.

The honest limitation: the alert is generated **in-app and optionally to a
webhook**. There is no SMS, no email, no SCADA integration. A real deployment
needs that, and it is small work compared with the data problem.

---

### Q10. How does this scale beyond the facilities you have?

Honestly: the archive holds **1,482 industrial facilities across six regions** —
Jamnagar, Hazira, Singrauli, Korba, central Punjab and Similipal. **We do not
claim national coverage**, and the map frames the data we have rather than
implying more.

Scaling is a data problem, not an architecture problem. Facilities come from
OpenStreetMap via Overpass; extending to all of India means more Overpass queries
and a bigger cache, which is an afternoon. The real work is that OSM industrial
tagging is uneven, so a national rollout would want an authoritative facility
register — a CPCB or state industries-department list — rather than crowd-sourced
tags.

---

### Q11. You only assess abnormality for 4% of sites. Isn't that useless?

It is thin, and it is the honest version of something that used to be worse.

An earlier build returned "maximally unusual" for **70% of detections** — any
location with no prior history got a fabricated 1.0. That conflated *"we watched
this place and it never lit up"* with *"we have no coverage of this place"*, and
in our archive it was overwhelmingly the second: the capture samples ten 5-day
windows, so a September event has an empty 60-day lookback because the archive
has no September data.

Now a location needs at least two prior detection days before "unusual" means
anything, and **16 of 390 sites clear that bar**. The rest say "not assessed — too
little history here".

So the answer to "isn't that useless" is: a 4% honest signal is more useful than a
70% fabricated one, and the fix is a denser archive — continuous daily pulls over
the monitored regions — not more code. That is the single highest-value next
thing we would do.

---

### Q12. The satellite data could be hours old. Doesn't that make it useless?

For *suppression*, yes — the fire brigade will beat us there. **We are not a
detection siren.**

Two things it is good for. First, **anomaly surveillance**: a thermal source
appearing at a plant that has never shown one is worth investigating even a day
later, because it may still be burning or may recur. Second, **accountability and
pattern-finding**: persistent flaring, unreported events, sites whose behaviour
changes over months.

The interface never hides the age — observation time and retrieval time are
separate fields, on the card and in the evidence drawer, because they are
different facts.

---

### Q13. Does this confirm fires?

No. It classifies thermal detections and says how confident it is.

A notification says "New heat detected at X", never "Fire confirmed at X" — and
that is enforced by test: no notification text may contain *confirmed*,
*definitely*, *certain* or *guaranteed*.

The evidence drawer carries a section headed **"What this is not"** which says in
plain words that proximity to a facility is context, not proof of cause. A hot
pixel landing on a plant does not establish that the plant caused it.

---

### Q14. Which parts of the problem statement are not done?

Three, and `docs/PS_COMPLIANCE.md` has the full table.

- **Per-event optical imagery.** We ship a Map/Satellite basemap switch, not a
  Sentinel-2 scene lookup with a band-ratio test. The drawer says "Optical check:
  not available" rather than implying one happened.
- **Land cover** comes from OpenStreetMap landuse polygons, not a spectral
  raster, and is missing for roughly half the detections — where it says "not
  mapped" and never guesses.
- **Dense history**, as in Q11.

Everything else — classification with abstention, persistent-source separation,
GIS storage and export, monitoring and alerting — is built and tested.

Also worth saying: the **official PS text is not in our repository**. We worked
from the title and our own reconstruction of the requirements, and we have marked
that as unverified rather than pretending to quote it.

---

### Q15. Can we see it break?

Yes, please. Three things to try:

1. **Turn off the Wi-Fi and reload.** The archive serves with no network.
2. **Click Past data and watch the bell.** It says "would have alerted" and sends
   nothing — no toast, no browser notification, no webhook.
3. **Ask for a date range we do not hold.** `?range=1999-01-01:1999-01-05`
   returns 404 rather than rendering an empty week as though it were real.

And if you want the whole gate: `npm run smoke` — 81 checks across secrets, lint,
build, 428 unit tests, every API route, the degradation matrix, UI copy, the
Live/Past surfaces, GIS export, and a real browser pass with axe accessibility.
It prints PASS/FAIL per group with real numbers.

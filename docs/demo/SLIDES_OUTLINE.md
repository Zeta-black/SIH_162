# Slides — 6 maximum, one idea each

Mirrors the demo. The slides exist to frame the live screen, not to replace it.
If the demo is working, spend your time there and treat these as backdrop.

Design: light background, one typeface, no gradients, no "AI-powered" badges,
no stock imagery, no logos other than the team's. Every number on a slide must
be a `Verified` row in `CLAIMS_REGISTER.md`.

---

## 1 — The problem

**Headline:** Satellites see thousands of hot spots over India every day. Which
ones matter?

**Visual:** One screenshot — the FIRMS raw view or a dense scatter of hot pixels
over India. Deliberately overwhelming.

**Say:** A plant safety officer does not need another list of hot pixels.

*No numbers on this slide.*

---

## 2 — What FIRETRACE shows

**Headline:** One map. Which industrial thermal detections need attention — and
why.

**Visual:** `docs/screens/after/main-1366x768.png`, full bleed.

**Say:** Seven need attention, eight to watch, eighteen normal, ten not sure —
from forty-three sites. Plain words, not a dashboard.

**Numbers:** 7 / 8 / 18 / 10 (claim C1).

---

## 3 — The idea, in one comparison

**Headline:** Same plant. Opposite answers. The one we ignore is 8.7x hotter.

**Visual:** Two cards side by side — the red ArcelorMittal card and the green
one. Screenshots, not a diagram.

| | Needs attention | Normal |
|---|---|---|
| 4.16 MW | 36.33 MW |
| no prior detection | 8 prior days |
| 1 pass | 13 passes |

**Say:** A brightness threshold flags the wrong one. Knowing what is normal *for
this site* is the product.

**Numbers:** claim C4.

---

## 4 — Honest intelligence

**Headline:** 111 of 390 sites say "not sure". That is the feature.

**Visual:** The grey "Not sure" card for Block - B coal mine, with the
"Not sure about:" box visible.

**Say:** Three things kept separate — what it is, how unusual it is, how urgently
to look. The score is an uncalibrated vote share and we call it a score, not a
probability. When evidence is thin the system abstains instead of guessing.

**Numbers:** 111 / 390, threshold 0.45 (claims C1, C3).

---

## 5 — It runs, including when the network does not

**Headline:** One command. One key. Works offline.

**Visual:** The provenance chip in its three states — Live / Offline / Replay —
cropped from real screenshots.

**Say:** `npm run demo`. Live when we can reach NASA, clearly-labelled saved data
when we cannot. A replay is never allowed to look like live data. Verified with
a deliberately wrong API key and with no network at all.

**Numbers:** FCP 1.2 s, 414 tests, smoke 80/80, axe 0 violations
(claims F1, F7, G1, G2).

---

## 6 — Limits, and what would make it real

**Headline:** What we have not proven.

**Say, in this order:**
- Labels are rule-generated. Our 1.0 metric measures policy reproduction, not
  fire-classification accuracy. We have not validated real-world accuracy.
- Coverage is 1,482 facilities across six regions, not national.
- No optical confirmation; alerts are in-app only.
- **What would make it real:** one season of verified incident labels from an
  operator or a pollution control board.

**Say:** We would rather show you this slide than a number we cannot defend.

---

## Slide hygiene

- Nothing animates.
- No slide has more than five numbers.
- If a figure is not in `CLAIMS_REGISTER.md` as `Verified`, cut it.
- Slide 6 is not optional. It is the slide that makes the other five credible.

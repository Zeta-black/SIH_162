# Design system

Implemented in `frontend/src/tokens.css`. Components reference tokens and never
literals, which is why the dark theme is the same system with different numbers
rather than a parallel stylesheet.

The governing idea: **quiet confidence.** The screen should look like a product
that costs money, and that comes from restraint, precision and speed — not
decoration. The map is the page; everything else floats over it and earns its
place.

---

## 1. Colour

### Grey ramp

Ten steps, hue ~215, deliberately **cool**. Warm greys fight the amber and red
status colours; a cool ground lets them read as signal rather than as part of the
furniture.

`--g-0` `--g-25` `--g-50` `--g-100` `--g-200` `--g-300` `--g-400` `--g-500`
`--g-600` `--g-700` `--g-800` `--g-900`

Semantic aliases sit on top (`--surface`, `--border`, `--ink`, `--ink-2`,
`--ink-3`), so a component asks for a role, not a number.

### Brand accent

One: `--brand` `#1a5fb4`. Used for focus rings, the active control, links and the
Past-data marker. Nothing else. A second accent is how an interface starts
looking like a template.

### Status — four, and only four

| Token | Colour | Meaning |
|---|---|---|
| `--s-attn` | `#c0362c` | Needs attention |
| `--s-watch` | `#b7791f` | Watch |
| `--s-normal` | `#2f855a` | Normal |
| `--s-unsure` | `#6b7280` | Not sure |

Each has `-ink`, `-wash` and `-line` variants so a chip, a marker and a border
can all use the family without hand-mixing.

**Colour is never the only carrier.** Red/green is the weak pair under
deuteranopia and protanopia, so every surface pairs the colour with:

- a **text label** — "Needs attention", never a bare red dot; and
- a **distinct marker shape** — a ring is a persistent source, a filled disc is
  new heat, a hollow disc is "not sure", and needs-attention markers are the
  largest.

A reader who sees no colour at all can still work the screen.

### Contrast

Body ink on surface measures AA or better at the sizes used. The smallest text
(`--t-11`, used for ages and captions) uses `--ink-3` on `--surface`, checked at
AA for normal text. Verified by axe-core on every new screen: **20 WCAG 2 A/AA
rules passing, 0 violations.**

---

## 2. Type

**One family.** Inter Variable, bundled from `node_modules`
(`@fontsource-variable/inter`) rather than a CDN — a font that arrives over the
network is a font that is missing at a venue with no Wi-Fi, and the app has to
look identical offline. Subsets are unicode-range split, so a Latin-text screen
never downloads Cyrillic or Greek.

**Two weights.** `--w-regular` 450 and `--w-medium` 600. Nothing bolder. Three
weights of one typeface is the most common way a careful design starts looking
busy.

**Six steps.** 11 / 12 / 14 / 16 / 20 / 28 px.

| Token | Used for |
|---|---|
| `--t-11` | ages, captions, group titles, the expert key-value rows |
| `--t-12` | secondary body, evidence lines, chips |
| `--t-14` | default body, the summary line, search |
| `--t-16` | card titles, **the verdict sentence**, drawer titles |
| `--t-20` | reserved |
| `--t-28` | reserved |

The verdict gets `--t-16` because it is the one sentence a judge reads in ten
seconds, and it should be the largest thing on the card.

**Tabular figures** on every number (`font-variant-numeric: tabular-nums`). Two
reasons: a column of counts aligns, and a freshness line ticking from "4 min ago"
to "5 min ago" does not shift the text next to it.

---

## 3. Space

A **4/8 scale**: `--sp-1` 4, `--sp-2` 8, `--sp-3` 12, `--sp-4` 16, `--sp-5` 24,
`--sp-6` 32, `--sp-7` 48. Nothing gets an off-grid margin.

Panels use `--sp-4` padding, inner groups `--sp-3`, tight rows `--sp-2`.

---

## 4. Shape and depth

**Radii:** 8 / 12 / 16 (`--r-sm` / `--r-md` / `--r-lg`) plus `--r-pill` for
chips and the search field. Panels are 12; sheets and the command palette are 16.

**Two shadow levels only:**

- `--shadow-rest` — anything sitting on the map;
- `--shadow-raised` — anything over other UI (popovers, drawer, palette, toast).

**No third level, and no glows.** A third level is how an interface becomes a
pile of cards. A glow is decoration pretending to be hierarchy.

---

## 5. Motion

Three durations (`--dur-fast` 120 ms, `--dur-base` 180 ms, `--dur-slow` 320 ms)
and two easings (`--ease`, `--ease-out`).

Motion exists to explain a state change and for nothing else:

| Motion | Why |
|---|---|
| Card slides in 10 px | says where it came from |
| Fly-to, ~650 ms eased | keeps the reader oriented between two places |
| Marker grows 1.22× on hover, 120 ms | affordance |
| One subtle pulse ring on the single most urgent marker | draws the eye once |
| One ring on a marker that arrived since the last poll | says "this is new" |
| Skeleton shimmer | shape of what is coming |

Everything is disabled under `prefers-reduced-motion`, and the toast is not shown
at all in that mode — the item is still in the bell, which is the durable
surface.

---

## 6. Controls

`--control-h` 36 px, `--control-h-lg` 44 px, `--touch-min` 44 px. Every
interactive target on mobile is at least 44 px; the bottom-sheet actions are
explicitly raised to it.

Focus is a 2 px `--brand` outline at 2 px offset, on every focusable element, via
`:focus-visible` so a mouse user does not see rings they did not ask for.

---

## 7. Dark theme

Built from the identical token names, redefined under both
`@media (prefers-color-scheme: dark)` (guarded by `:root:not([data-theme='light'])`)
and `:root[data-theme='dark']`. No component carries a dark-specific rule.

The basemap is inverted and desaturated in CSS rather than swapped for a paid
dark style.

**It follows the system setting and has had no design-QA pass.** Light is the
default and is what the demo uses. There is no manual toggle yet.

---

## 8. The anti-slop list

Enforced in review, and partly by the smoke gate (group 8 greps for overclaiming
copy). None of the following appears anywhere:

gradient text · decorative gradients · glassmorphism · glow · neon ·
purple-blue "AI" palettes · emoji as icons · "AI-powered" badges · stock
illustrations · 3D globes · animated number counters · confetti · marquees or
tickers · lorem ipsum · placeholder numbers · more than five numbers on screen ·
card walls · hero banners · more than two weights of one typeface ·
pill-everything.

Copy never says *revolutionary*, *next-gen*, *cutting-edge*, *seamless*,
*real-time*, *instant*, *100% accurate*.

Say **near-real-time**, and say the actual age.

---

## 9. The five-number budget

At most five numbers in the chrome at once. On the Live screen:

1. needs attention 2. watch 3. normal — in the summary line
4. the filter chip counts (three, but they restate the summary)
5. the replay day counter, in Past mode only

Cluster bubbles carry counts too. That is map **content**, as on any clustered
map, not chrome — stated in the claims register rather than argued away.

---

## 10. Icons

Inline SVG, `currentColor`, 1.8 px stroke, 24×24 viewBox, in
`components/map/mapicons.jsx`. **Never emoji** — emoji render differently on
every platform, carry a colour we do not control, and read as decoration.

---

## 11. Files

| File | Holds |
|---|---|
| `src/tokens.css` | every token, light and dark |
| `src/app.css` | shell, map, markers, panels, controls, responsive |
| `src/card.css` | detail card, evidence drawer, mobile bottom sheet |
| `src/styles.css` | the **separate** SCADA console system for `/analytics/*` |

`styles.css` is deliberately a different language: dense, square, monospaced,
information-first. That is right for an analyst's reference pages and wrong for
the screen a judge opens first, which is why the two do not share tokens.

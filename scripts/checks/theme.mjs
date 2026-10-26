/* Light-theme-only check.
 *
 * FIRETRACE ships one theme. Pass 2 shipped a dark one that followed the OS
 * setting, so a reviewer on a dark-mode machine saw dark panels, near-black
 * clusters and red markers that no longer stood out — while every screenshot,
 * taken with Playwright's default light preference, looked correct.
 *
 * This renders the same screens under `colorScheme: 'light'` and
 * `colorScheme: 'dark'` and fails unless the two are byte-identical. That is a
 * stronger assertion than "no dark CSS exists", because it also catches a
 * browser default or a third-party stylesheet reacting to the preference.
 */
import { chromium } from 'playwright'
import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const WEB = process.env.SMOKE_WEB ?? 'http://localhost:5199'
const OUT = process.env.THEME_OUT ?? null

const SCREENS = [
  { name: 'live', url: '/' },
  { name: 'past', url: '/?demo=1' },
  { name: 'card', url: '/?demo=1&site=FE-2026-4BA6', wait: '.fc-card-title' },
]

let failures = 0
const record = (name, pass, detail = '') => {
  console.log(`  ${pass ? 'ok  ' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`)
  if (!pass) failures += 1
}

const browser = await chromium.launch()

async function capture(screen, colorScheme) {
  const ctx = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    colorScheme,
    // A fixed clock keeps the "4 min ago" line from differing between the two
    // runs for reasons that have nothing to do with theme.
    reducedMotion: 'reduce',
  })
  const page = await ctx.newPage()
  await page.goto(`${WEB}${screen.url}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.fc-live', { timeout: 60000 }).catch(() => {})
  if (screen.wait) await page.waitForSelector(screen.wait, { timeout: 30000 }).catch(() => {})
  await page.waitForTimeout(4000)

  /* Neutralise everything that legitimately varies between two page loads, so
   * a difference in the screenshots can only mean a difference in theme:
   *   - live values (the ticking age, the replay day, notification ages)
   *   - map tiles, which arrive in a different order every time and are a
   *     third party's bytes rather than our styling. */
  await page.evaluate(async () => {
    /* Everything whose content comes from the feed rather than from styling.
     * The Live surface especially: two loads seconds apart can legitimately see
     * a different number of detections, or flip between "fresh" and "empty", so
     * comparing those pixels would be comparing NASA's day, not our theme. */
    const volatile = [
      '.fc-fresh',
      '.fc-summary',
      '.fc-tl-day',
      '.fc-tl-of',
      '.fc-notif-age',
      '.fc-chip',
      '.fc-queue-name',
      '.fc-queue-count',
      '.fc-cluster',
    ]
    document.querySelectorAll(volatile.join(', ')).forEach((el) => {
      el.textContent = 'x'
    })
    /* Hide the map canvas entirely.
     *
     * The regression this check exists for was in the chrome — panels, text,
     * clusters, controls. The map underneath is third-party tiles at a position
     * that depends on when a fly-to animation finished, so including it made the
     * comparison flaky in a way that had nothing to do with theme: a different
     * screen failed on each run while every computed-style assertion passed.
     *
     * Marker and cluster colours are still covered: by the computed-style
     * assertions below, and by the colour tokens being the only source of them. */
    document.querySelectorAll('.fc-canvas').forEach((el) => {
      el.style.visibility = 'hidden'
    })
  })
  await page.waitForTimeout(300)

  const buffer = await page.screenshot()
  const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)
  const bodyBg = await page.evaluate(() => {
    const panel = document.querySelector('.fc-panel')
    return panel ? getComputedStyle(panel).backgroundColor : null
  })
  const ink = await page.evaluate(() => {
    const el = document.querySelector('.fc-wordmark')
    return el ? getComputedStyle(el).color : null
  })
  // Clusters were near-black under the old dark theme, which buried the one
  // thing the map exists to surface. Checked by computed style, because the
  // canvas is hidden for the pixel comparison above.
  const cluster = await page.evaluate(() => {
    const el = document.querySelector('.fc-cluster')
    if (!el) return null
    const cs = getComputedStyle(el)
    // Luminance of the bubble's fill. The old dark theme made this near-black,
    // which buried the one thing the map exists to surface.
    const [r, g, b] = (cs.backgroundColor.match(/\d+/g) ?? [0, 0, 0]).map(Number)
    return {
      background: cs.backgroundColor,
      color: cs.color,
      luminance: Math.round((0.2126 * r + 0.7152 * g + 0.0722 * b) / 2.55) / 100,
    }
  })
  await ctx.close()
  return { buffer, scheme, bodyBg, ink, cluster }
}

for (const screen of SCREENS) {
  const light = await capture(screen, 'light')
  const dark = await capture(screen, 'dark')

  const a = createHash('sha256').update(light.buffer).digest('hex')
  const b = createHash('sha256').update(dark.buffer).digest('hex')

  if (OUT) {
    mkdirSync(OUT, { recursive: true })
    writeFileSync(join(OUT, `${screen.name}-light.png`), light.buffer)
    writeFileSync(join(OUT, `${screen.name}-dark.png`), dark.buffer)
  }

  record(
    `${screen.name}: identical under light and dark preference`,
    a === b,
    a === b ? 'pixel-identical' : `${a.slice(0, 8)} vs ${b.slice(0, 8)}`,
  )
  record(
    `${screen.name}: declares color-scheme light`,
    light.scheme === 'light' && dark.scheme === 'light',
    `${light.scheme} / ${dark.scheme}`,
  )
  record(
    `${screen.name}: panels stay white`,
    light.bodyBg === dark.bodyBg && /255, 255, 255/.test(String(dark.bodyBg)),
    String(dark.bodyBg),
  )
  record(
    `${screen.name}: text stays dark`,
    light.ink === dark.ink,
    String(dark.ink),
  )
  if (light.cluster || dark.cluster) {
    const same =
      light.cluster?.background === dark.cluster?.background &&
      light.cluster?.color === dark.cluster?.color
    record(
      `${screen.name}: clusters stay light`,
      same && (dark.cluster?.luminance ?? 0) > 0.8,
      `fill ${dark.cluster?.background} (luminance ${dark.cluster?.luminance})`,
    )
  }
}

await browser.close()
console.log(`\n  theme checks: ${failures === 0 ? 'all passed' : `${failures} failed`}`)
process.exit(failures === 0 ? 0 : 1)

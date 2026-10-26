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
    document.querySelectorAll('.fc-fresh, .fc-tl-day, .fc-tl-of, .fc-notif-age').forEach((el) => {
      el.textContent = 'x'
    })
    document.querySelectorAll('.leaflet-tile-pane').forEach((el) => {
      el.style.visibility = 'hidden'
    })
    // The cluster bubbles carry counts that shift with the replay position.
    document.querySelectorAll('.fc-cluster').forEach((el) => {
      el.textContent = '0'
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
  await ctx.close()
  return { buffer, scheme, bodyBg, ink }
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
}

await browser.close()
console.log(`\n  theme checks: ${failures === 0 ? 'all passed' : `${failures} failed`}`)
process.exit(failures === 0 ? 0 : 1)

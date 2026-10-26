/* Frame-rate measurement, on the production build.
 *
 * Pass 2 claimed no fps figure because none was measured, which was the honest
 * thing to say but not a useful one. This measures it.
 *
 * Two deliberate choices:
 *
 * 1. **The production build, not the dev server.** Vite's dev server transforms
 *    modules on demand and ships them unminified; measuring frame rate there
 *    tells you about the dev server. This serves `dist/` with `vite preview`.
 *
 * 2. **requestAnimationFrame deltas, not Chrome's FPS meter.** The meter reports
 *    compositor frames including ones where nothing of ours ran. Counting rAF
 *    callbacks during a scripted interaction measures what the page actually
 *    manages while it is being driven.
 *
 * Usage:  node scripts/checks/perf.mjs
 * Expects a preview server and an API already running (see npm run perf).
 */
import { chromium } from 'playwright'

const WEB = process.env.PERF_WEB ?? 'http://localhost:4173'
const results = []

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } })
const page = await ctx.newPage()

/** Count rAF frames while `drive` runs, and report the distribution. */
async function measure(label, drive, ms = 3000) {
  await page.evaluate(() => {
    window.__frames = []
    window.__stop = false
    let last = performance.now()
    const tick = (now) => {
      window.__frames.push(now - last)
      last = now
      if (!window.__stop) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })

  await drive(ms)

  const stats = await page.evaluate(() => {
    window.__stop = true
    const deltas = window.__frames.filter((d) => d > 0 && d < 2000)
    if (deltas.length < 5) return null
    const sorted = [...deltas].sort((a, b) => a - b)
    const pct = (p) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))]
    const mean = deltas.reduce((a, b) => a + b, 0) / deltas.length
    return {
      frames: deltas.length,
      meanFps: 1000 / mean,
      // p95 of frame *duration* is the slow tail, so it maps to the low fps a
      // person actually notices.
      p95Fps: 1000 / pct(0.95),
      worstMs: sorted[sorted.length - 1],
    }
  })

  if (!stats) {
    results.push({ label, note: 'too few frames to measure' })
    return
  }
  results.push({ label, ...stats })
}

// --------------------------------------------------------------- load
await page.goto(`${WEB}/?demo=1`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.fc-live', { timeout: 60000 })
await page.waitForSelector('.fc-timeline', { timeout: 60000 }).catch(() => {})
await page.waitForTimeout(5000)

const markers = await page.evaluate(
  () => document.querySelectorAll('.fc-marker, .fc-cluster').length,
)

// --------------------------------------------------------------- pan
await measure('pan', async (ms) => {
  const start = Date.now()
  const box = await page.locator('.fc-canvas').boundingBox()
  const cx = box.x + box.width / 2
  const cy = box.y + box.height / 2
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  let i = 0
  while (Date.now() - start < ms) {
    i += 1
    await page.mouse.move(cx + Math.sin(i / 6) * 160, cy + Math.cos(i / 9) * 90)
  }
  await page.mouse.up()
})

// -------------------------------------------------------------- zoom
await measure('zoom', async (ms) => {
  const start = Date.now()
  const box = await page.locator('.fc-canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  while (Date.now() - start < ms) {
    await page.mouse.wheel(0, Date.now() % 600 < 300 ? -120 : 120)
    await page.waitForTimeout(60)
  }
})

// ------------------------------------------------------------ replay
const hasTimeline = (await page.locator('.fc-tl-play').count()) > 0
if (hasTimeline) {
  await page.locator('.fc-tl-speeds button', { hasText: '4' }).click()
  await measure('replay 4x', async (ms) => {
    await page.locator('.fc-tl-play').click()
    await page.waitForTimeout(ms)
    await page.locator('.fc-tl-play').click()
  })
}

await browser.close()

// ------------------------------------------------------------- report
console.log(`\n  Frame rate — production build, ${markers} markers on screen`)
console.log(`  ${'-'.repeat(58)}`)
let worstMean = Infinity
for (const r of results) {
  if (r.note) {
    console.log(`  ${r.label.padEnd(12)} ${r.note}`)
    continue
  }
  worstMean = Math.min(worstMean, r.meanFps)
  console.log(
    `  ${r.label.padEnd(12)} mean ${r.meanFps.toFixed(0).padStart(3)} fps` +
      `   p95 ${r.p95Fps.toFixed(0).padStart(3)} fps` +
      `   worst frame ${r.worstMs.toFixed(0)} ms   (${r.frames} frames)`,
  )
}
console.log('')

// Reported, not gated: frame rate on a shared CI-style machine is noisy, and a
// flaky perf gate is a gate people learn to ignore. The number is the output.
if (process.env.PERF_MIN_FPS) {
  const floor = Number(process.env.PERF_MIN_FPS)
  if (worstMean < floor) {
    console.log(`  below the ${floor} fps floor`)
    process.exit(1)
  }
}

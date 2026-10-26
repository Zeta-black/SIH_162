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

/* Driving happens INSIDE the page, not over CDP.
 *
 * The first version drove with `page.mouse.move()` in a tight loop and measured
 * 16 fps on a screen with four markers. That was the harness, not the app: every
 * Playwright input event is an IPC round trip, so the loop could only issue a
 * few dozen a second and the page sat idle between them. Calling Leaflet's own
 * pan and zoom from a rAF loop in the page measures the redraw path, which is
 * the thing worth knowing. */
await page.evaluate(() => {
  // CalmMap stashes the instance on its container element for exactly this.
  const container = document.querySelector('.leaflet-container')
  window.__map = container?._leaflet_map ?? null
})

/** Pan the map back and forth from inside the page. */
async function drivePan(ms) {
  await page.evaluate(
    (duration) =>
      new Promise((resolve) => {
        const map = window.__map
        const end = performance.now() + duration
        let i = 0
        const step = () => {
          i += 1
          if (map) map.panBy([i % 2 ? 24 : -24, i % 3 ? 12 : -12], { animate: false })
          if (performance.now() < end) requestAnimationFrame(step)
          else resolve()
        }
        requestAnimationFrame(step)
      }),
    ms,
  )
}

/** Zoom in and out from inside the page. */
async function driveZoom(ms) {
  await page.evaluate(
    (duration) =>
      new Promise((resolve) => {
        const map = window.__map
        const end = performance.now() + duration
        let z = map ? map.getZoom() : 5
        let dir = 0.25
        const step = () => {
          if (map) {
            z += dir
            if (z > 8) dir = -0.25
            if (z < 4.5) dir = 0.25
            map.setZoom(z, { animate: false })
          }
          if (performance.now() < end) requestAnimationFrame(step)
          else resolve()
        }
        requestAnimationFrame(step)
      }),
    ms,
  )
}

const hasMap = await page.evaluate(() => Boolean(window.__map))

if (hasMap) {
  await measure('pan', drivePan)
  await measure('zoom', driveZoom)
} else {
  results.push({ label: 'pan', note: 'could not reach the Leaflet instance' })
  results.push({ label: 'zoom', note: 'could not reach the Leaflet instance' })
}

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

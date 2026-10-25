// FIRETRACE pre-warm:  npm run prewarm
//
// Run this before a demo, on whatever network you have.
//
// Why it exists, measured on this machine: a cold /api/map takes 3.5 s against
// the archive and up to 34 s against the live NASA feed, because the analysis
// walks every detection through the model. Warm, the same request is 0.1 s. The
// backend caches an analysis for 20 minutes in memory and writes the last good
// live fetch to disk, so one pass here is the difference between a map that is
// already on screen when a judge walks up and one that is still thinking.
//
// It is deliberately forgiving: a failure to reach NASA is reported and the
// archive is warmed anyway, because that is exactly the situation the demo
// needs to survive.

import { banner, log } from './common.mjs'

const API = process.env.FIRETRACE_API ?? 'http://127.0.0.1:8000'
const BBOX = process.env.FIRETRACE_BBOX ?? '68.0,6.5,97.5,36.0'

async function hit(label, path, timeoutMs = 60000) {
  const started = Date.now()
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${API}${path}`, { signal: controller.signal })
    const seconds = ((Date.now() - started) / 1000).toFixed(1)
    if (!res.ok) {
      log.warn(`${label} — HTTP ${res.status} after ${seconds}s`)
      return null
    }
    const body = await res.json()
    log.ok(`${label} — ${seconds}s`)
    return body
  } catch (err) {
    const seconds = ((Date.now() - started) / 1000).toFixed(1)
    log.warn(`${label} — ${err.name === 'AbortError' ? 'timed out' : err.message} after ${seconds}s`)
    return null
  } finally {
    clearTimeout(timer)
  }
}

banner('pre-warming caches')

// 1. Is the backend even up?
const health = await hit('backend health', '/health', 10000)
if (!health) {
  log.fail('The backend is not answering.')
  log.info(`Expected it at ${API}. Start it with "npm run demo" and re-run this.`)
  process.exit(1)
}
log.info(`model loaded=${health.model_loaded}  snapshot=${health.snapshot_available}  key=${health.firms_key_configured}`)

// 2. The archive. This must work; it is the demo's floor.
log.blank()
log.step('Archive (Demo Mode) — the path that must never fail')
const demo = await hit('  /api/map?mode=demo', `/api/map?bbox=${BBOX}&days=1&mode=demo`)
if (!demo) {
  log.fail('The offline archive did not warm. The demo has no safe fallback.')
  process.exit(1)
}
log.info(`  ${demo.counts.needs_attention} need attention · ${demo.counts.watch} watch · ${demo.counts.normal} normal · ${demo.counts.not_sure} not sure`)
log.info(`  provenance: ${demo.provenance.label}`)

// 3. The live feed. Allowed to fail; that is the point of step 2.
log.blank()
log.step('Live NASA FIRMS — allowed to fail')
const live = await hit('  /api/map?mode=auto', `/api/map?bbox=${BBOX}&days=1&mode=auto`, 90000)
if (live) {
  log.info(`  provenance: ${live.provenance.label}`)
  log.info(`  ${live.counts.sites} sites from ${live.counts.detections} detections`)
  if (live.provenance.state === 'live') {
    log.ok('  live feed reachable and cached to disk')
  } else {
    log.warn(`  not live: ${live.provenance.detail ?? live.provenance.state}`)
  }
} else {
  log.warn('  live feed unreachable — the demo will use the archive, clearly labelled')
}

// 4. Confirm the warm path is actually fast now.
log.blank()
log.step('Verifying the warm path')
const t0 = Date.now()
await hit('  /api/map?mode=demo (second call)', `/api/map?bbox=${BBOX}&days=1&mode=demo`)
const warmMs = Date.now() - t0
if (warmMs > 1500) {
  log.warn(`  warm call took ${warmMs} ms — slower than expected, but workable`)
} else {
  log.ok(`  warm call ${warmMs} ms`)
}

log.blank()
log.ok('Pre-warm complete.')
log.info('Open http://localhost:5173/?demo=1 for the guaranteed-offline view.')
log.blank()

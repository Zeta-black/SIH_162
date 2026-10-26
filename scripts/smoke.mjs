// FIRETRACE quality gate:  npm run smoke
//
// One command, one verdict. Starts what it needs, checks it, tears it down, and
// prints PASS/FAIL per group with real numbers rather than reassurance.
//
// Groups, in the order a reviewer would want them:
//   1  Secrets          nothing sensitive is tracked by git
//   2  Static           lint and production build
//   3  Unit             the pytest suite
//   4  API              every route the frontend calls, with timings
//   5  Degradation      live -> cached -> archive, bad key, no network
//   6  Pipeline         the existing replay/incident smoke test
//   7  Browser          the real UI, axe, screenshots, zero console errors
//   8  Copy             no overclaiming or stale-dated string in the UI
//   9  Live/Past        surfaces, provenance, and replay sending nothing
//  10  GIS              GeoJSON layers and a GeoPackage that reads back
//
// Any group can be run alone:  npm run smoke -- --only api

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  BACKEND,
  FRONTEND,
  IS_WINDOWS,
  ROOT,
  colors as C,
  banner,
  log,
  needsShell,
  npmCmd,
  run,
  venvExists,
  venvPython,
} from './common.mjs'

const API_PORT = Number(process.env.SMOKE_API_PORT ?? 8099)
const WEB_PORT = Number(process.env.SMOKE_WEB_PORT ?? 5199)
const API = `http://127.0.0.1:${API_PORT}`
const WEB = `http://localhost:${WEB_PORT}`
const BBOX = '68.0,6.5,97.5,36.0'

const onlyIdx = process.argv.indexOf('--only')
const ONLY = onlyIdx > -1 ? process.argv[onlyIdx + 1] : null

const groups = []
let currentGroup = null

function group(name) {
  currentGroup = { name, checks: [], skipped: false }
  groups.push(currentGroup)
  log.blank()
  console.log(`${C.bold}  ${name}${C.reset}`)
  return currentGroup
}

function check(name, pass, detail = '') {
  currentGroup.checks.push({ name, pass, detail })
  if (pass) log.ok(`${name}${detail ? ` ${C.dim}— ${detail}${C.reset}` : ''}`)
  else log.fail(`${name}${detail ? ` — ${detail}` : ''}`)
  return pass
}

const wanted = (key) => !ONLY || ONLY === key

// ---------------------------------------------------------------- helpers
async function get(path, timeoutMs = 120000) {
  const started = Date.now()
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${API}${path}`, { signal: controller.signal })
    const ms = Date.now() - started
    let body = null
    try {
      body = await res.json()
    } catch {
      // non-JSON (csv/geojson export); status and timing still count
    }
    return { ok: res.ok, status: res.status, ms, body }
  } catch (err) {
    return { ok: false, status: 0, ms: Date.now() - started, body: null, error: err.name }
  } finally {
    clearTimeout(timer)
  }
}

/** POST with no body, for the endpoints that only act. */
async function postPath(path, timeoutMs = 60000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${API}${path}`, { method: 'POST', signal: controller.signal })
    let body = null
    try {
      body = await res.json()
    } catch {
      // Some POSTs answer with no JSON; the status still counts.
    }
    return { ok: res.ok, status: res.status, body }
  } catch (err) {
    return { ok: false, status: 0, body: null, error: err.name }
  } finally {
    clearTimeout(timer)
  }
}

function portFree(port) {
  return new Promise((resolve) => {
    const probe = createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

const servers = []

function startServer(name, cmd, args, cwd, env = {}) {
  const child = spawn(cmd, args, {
    cwd,
    shell: needsShell(cmd),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', ...env },
  })
  // Captured, not printed: a passing smoke run should be readable.
  child.stdout.on('data', () => {})
  child.stderr.on('data', () => {})
  servers.push(child)
  return child
}

function stopServers() {
  for (const child of servers) {
    if (child.killed || child.exitCode !== null) continue
    if (IS_WINDOWS) spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    else child.kill('SIGTERM')
  }
}

async function waitFor(url, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url)
      if (res.ok) return true
    } catch {
      // still starting
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  log.warn(`${label} did not answer within ${timeoutMs / 1000}s`)
  return false
}

process.on('SIGINT', () => {
  stopServers()
  process.exit(130)
})

banner('quality gate')

if (!venvExists() || !existsSync(join(FRONTEND, 'node_modules'))) {
  log.fail('Not installed. Run "npm run setup" (or "npm run demo") first.')
  process.exit(1)
}

// =====================================================================  1
if (wanted('secrets')) {
  group('1  Secrets')

  const tracked = await new Promise((resolve) => {
    const p = spawn('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    let out = ''
    p.stdout.on('data', (d) => (out += d))
    p.on('close', () => resolve(out.split('\n').filter(Boolean)))
  })

  check('.env is not tracked by git', !tracked.includes('.env'))
  check('.env.example is tracked', tracked.includes('.env.example'))

  const example = readFileSync(join(ROOT, '.env.example'), 'utf8')
  const placeholder = /FIRMS_MAP_KEY=(your_|<|$|\s)/m.test(example)
  check('.env.example holds a placeholder, not a key', placeholder)

  /* A FIRMS MAP_KEY is 32 hex characters. Scan every tracked text file.
   *
   * Two kinds of 32-hex string are legitimate and must not be flagged, or the
   * check becomes noise that people learn to ignore:
   *   - content hashes in the demo snapshot and the docs, which is why a hit
   *     only counts when it sits next to a key-shaped word;
   *   - deliberately fake keys in the degradation tests. Those are recognised
   *     structurally — a key made of one short repeated block, or one made of a
   *     single repeated character — rather than by listing literals, so a new
   *     fake in a new test does not need the allowlist updated.
   */
  const isObviouslyFake = (value) => {
    for (const size of [1, 2, 4, 8, 16]) {
      const block = value.slice(0, size)
      if (block.repeat(32 / size) === value) return true
    }
    return false
  }

  const suspects = []
  for (const file of tracked) {
    if (/\.(png|jpg|jpeg|gif|ico|joblib|sqlite3|woff2?)$/i.test(file)) continue
    if (file.endsWith('package-lock.json')) continue
    let content
    try {
      content = readFileSync(join(ROOT, file), 'utf8')
    } catch {
      continue
    }
    for (const m of content.matchAll(/\b[a-f0-9]{32}\b/g)) {
      if (isObviouslyFake(m[0])) continue
      const around = content.slice(Math.max(0, m.index - 60), m.index + 40).toLowerCase()
      if (/key|token|secret|password/.test(around)) suspects.push(`${file}: ${m[0].slice(0, 8)}...`)
    }
  }
  check('No key-shaped secret in any tracked file', suspects.length === 0, suspects.join('; '))

  /* The same scan over git history.
   *
   * Added in Pass 2 because the tracked-files scan passed while a real key sat
   * in an earlier commit's diff. A scan of the working tree cannot see that, and
   * "no secrets in the repo" has to mean the history too.
   *
   * backup-before-scrub deliberately retains the pre-scrub history so a human
   * can verify the rewrite before deleting it, so a hit confined to that branch
   * is reported rather than failed. */
  const gitOut = (args) =>
    new Promise((resolve) => {
      const child = spawn('git', args, { cwd: ROOT, encoding: 'utf8' })
      let out = ''
      child.stdout.on('data', (d) => (out += d))
      child.on('close', () => resolve(out))
      child.on('error', () => resolve(''))
    })

  const keyLine = /FIRMS_MAP_KEY=\s*([a-f0-9]{32})\b/g
  const shas = (await gitOut(['log', '--all', '--format=%H', '-S', 'FIRMS_MAP_KEY='])).split('\n').filter(Boolean)

  const dirty = new Set()
  for (const sha of shas) {
    const diff = await gitOut(['show', sha, '--', '.env.example', 'docs/', 'README.md'])
    for (const m of diff.matchAll(keyLine)) {
      if (!isObviouslyFake(m[1])) dirty.add(sha.slice(0, 10))
    }
  }

  let onlyOnBackup = false
  if (dirty.size > 0) {
    const containing = await gitOut(['branch', '--contains', [...dirty][0]])
    onlyOnBackup = containing
      .split('\n')
      .filter((l) => l.trim())
      .every((l) => l.includes('backup-before-scrub'))
  }

  check(
    'No key-shaped secret anywhere in git history',
    dirty.size === 0 || onlyOnBackup,
    dirty.size === 0
      ? 'history clean'
      : onlyOnBackup
        ? `${dirty.size} commit(s) on backup-before-scrub only — delete that branch`
        : [...dirty].join(', '),
  )

  const ignored = await new Promise((resolve) => {
    const child = spawn('git', ['check-ignore', '.env'], { cwd: ROOT })
    child.on('close', (code) => resolve(code === 0))
    child.on('error', () => resolve(false))
  })
  check('.env is covered by .gitignore', ignored)
}

// =====================================================================  2
if (wanted('static')) {
  group('2  Static analysis and build')

  const lint = await run(npmCmd, ['run', 'lint'], { cwd: FRONTEND, stdio: 'ignore' })
  check('Frontend lint is clean', lint === 0, `exit ${lint}`)

  const t0 = Date.now()
  const build = await run(npmCmd, ['run', 'build'], { cwd: FRONTEND, stdio: 'ignore' })
  check('Production build succeeds', build === 0, `${((Date.now() - t0) / 1000).toFixed(1)}s`)
  check('Build output exists', existsSync(join(FRONTEND, 'dist', 'index.html')))

  const compile = await run(
    venvPython(),
    ['-m', 'compileall', '-q', 'app', 'ml', 'scripts'],
    { cwd: BACKEND, stdio: 'ignore' },
  )
  check('Backend compiles', compile === 0, `exit ${compile}`)
}

// =====================================================================  3
if (wanted('unit')) {
  group('3  Unit tests')
  const t0 = Date.now()
  const code = await run(venvPython(), ['-m', 'pytest', '-q'], { cwd: BACKEND, stdio: 'inherit' })
  check('pytest suite passes', code === 0, `${((Date.now() - t0) / 1000).toFixed(0)}s`)
}

// ----------------------------------------------- start the backend for 4-7
const needsServer =
  wanted('api') ||
  wanted('degradation') ||
  wanted('pipeline') ||
  wanted('browser') ||
  wanted('livepast') ||
  wanted('gis')

if (needsServer) {
  for (const [port, what] of [[API_PORT, 'smoke API'], [WEB_PORT, 'smoke web']]) {
    // eslint-disable-next-line no-await-in-loop
    if (!(await portFree(port))) {
      log.blank()
      log.fail(`Port ${port} (${what}) is busy. Set SMOKE_API_PORT / SMOKE_WEB_PORT.`)
      process.exit(1)
    }
  }

  log.blank()
  log.step(`Starting a backend on ${API_PORT} for the live checks ...`)
  startServer(
    'api',
    venvPython(),
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(API_PORT)],
    BACKEND,
  )
  if (!(await waitFor(`${API}/health`, 90000, 'The backend'))) {
    stopServers()
    process.exit(1)
  }
  log.ok('Backend healthy')
}

// =====================================================================  4
if (wanted('api')) {
  group('4  API surface')

  const health = await get('/health', 15000)
  check('GET /health', health.ok, `${health.status} in ${health.ms} ms`)
  check('Health reports a loaded model', health.body?.model_loaded === true)
  check('Health reports the archive', health.body?.snapshot_available === true)

  // Warm the archive once so the timings below describe the demo path.
  await get(`/api/map?bbox=${BBOX}&days=1&mode=demo`)

  const routes = [
    ['GET /api/map', `/api/map?bbox=${BBOX}&days=1&mode=demo`, 1500],
    ['GET /api/map/search', `/api/map/search?q=refinery&mode=demo`, 3000],
    ['GET /api/meta', '/api/meta', 500],
    ['GET /api/model/info', '/api/model/info', 500],
    ['GET /api/sources', '/api/sources', 1000],
    ['GET /api/scenarios', '/api/scenarios', 500],
    ['GET /api/hotspots', `/api/hotspots?bbox=${BBOX}&days=1&mode=demo`, 2000],
    ['GET /api/events', `/api/events?bbox=${BBOX}&days=1&mode=demo`, 2000],
    ['GET /api/incidents', '/api/incidents?mode=demo', 1500],
    ['GET /api/dashboard/summary', `/api/dashboard/summary?bbox=${BBOX}&days=1&mode=demo`, 1500],
    ['GET /api/facilities', `/api/facilities?bbox=${BBOX}&mode=demo`, 2000],
    ['GET /api/replay/catalogue', '/api/replay/catalogue', 8000],
    ['GET /api/export/geojson', `/api/export/geojson?bbox=${BBOX}&days=1&mode=demo`, 3000],
  ]

  for (const [name, path, budgetMs] of routes) {
    // eslint-disable-next-line no-await-in-loop
    const r = await get(path)
    check(name, r.ok, `${r.status} in ${r.ms} ms${r.ms > budgetMs ? ` (over ${budgetMs} ms budget)` : ''}`)
  }

  // --- schema of the one endpoint the main screen depends on --------------
  const map = (await get(`/api/map?bbox=${BBOX}&days=1&mode=demo`)).body
  const required = ['provenance', 'counts', 'status_vocabulary', 'window', 'model', 'disclaimer', 'sites']
  check('/api/map carries every required block', required.every((k) => k in (map ?? {})))

  const statuses = ['needs_attention', 'watch', 'normal', 'not_sure']
  check(
    'Counts cover every site exactly once',
    statuses.reduce((a, k) => a + (map?.counts?.[k] ?? 0), 0) === map?.counts?.sites,
    `${statuses.map((k) => `${k}=${map?.counts?.[k]}`).join(' ')} vs sites=${map?.counts?.sites}`,
  )

  const site = map?.sites?.[0]
  check('Each site has a verdict, why-lines and gaps', Boolean(site?.verdict && site?.why && site?.missing))
  check('Why-lines are capped at three', (site?.why?.length ?? 99) <= 3)
  check(
    'Score, abnormality and priority are separate fields',
    site && 'model_score' in site && 'operational_priority' in site && 'priority_score' in site,
  )
  check(
    'The score is never called a probability',
    /uncalibrated/i.test(map?.model?.score_note ?? '') &&
      /not a probability/i.test(map?.model?.score_note ?? ''),
  )
  check(
    'Observation time is separate from retrieval time',
    Boolean(site?.observed_at && map?.provenance?.retrieved_at) &&
      site.observed_at !== map.provenance.retrieved_at,
  )

  const notSure = map?.sites?.filter((s) => s.status === 'not_sure') ?? []
  check('At least one real "Not sure" case exists', notSure.length > 0, `${notSure.length} sites`)

  // --- bad input -----------------------------------------------------------
  const badBbox = await get('/api/map?bbox=not,a,bbox&days=1&mode=demo')
  check('Malformed bbox is rejected cleanly', [400, 422].includes(badBbox.status), `${badBbox.status}`)
  const badDays = await get(`/api/map?bbox=${BBOX}&days=99&mode=demo`)
  check('Out-of-range day window is rejected', [400, 422].includes(badDays.status), `${badDays.status}`)
  const shortQuery = await get('/api/map/search?q=r&mode=demo')
  check('One-character search is rejected', shortQuery.status === 422, `${shortQuery.status}`)
  const missing = await get('/api/hotspots/EVT-DOES-NOT-EXIST?mode=demo')
  check('Unknown id returns 404, not 500', missing.status === 404, `${missing.status}`)

  // --- the key must never leave the server --------------------------------
  const key = (() => {
    try {
      const env = readFileSync(join(ROOT, '.env'), 'utf8')
      return env.match(/^FIRMS_MAP_KEY=(.+)$/m)?.[1]?.trim()
    } catch {
      return null
    }
  })()
  if (key && key !== 'your_nasa_firms_map_key_here') {
    let leaked = false
    for (const [, path] of routes) {
      // eslint-disable-next-line no-await-in-loop
      const res = await fetch(`${API}${path}`)
      // eslint-disable-next-line no-await-in-loop
      if ((await res.text()).includes(key)) leaked = true
    }
    check('No endpoint echoes the NASA key', !leaked)
  } else {
    log.info('    (no real key configured; key-leak check skipped)')
  }
}

// =====================================================================  5
if (wanted('degradation')) {
  group('5  Graceful degradation')

  const demo = (await get(`/api/map?bbox=${BBOX}&days=1&mode=demo`)).body
  check('Demo mode works and is labelled Replay', demo?.provenance?.state === 'replay', demo?.provenance?.label)
  check('Demo mode is never flagged live', demo?.provenance?.is_live === false)
  check('Demo mode returns real sites', (demo?.counts?.sites ?? 0) > 0, `${demo?.counts?.sites} sites`)

  // A deliberately wrong key, on its own backend.
  const badPort = API_PORT + 1
  if (await portFree(badPort)) {
    log.step('  starting a backend with a deliberately wrong key ...')
    startServer(
      'badkey',
      venvPython(),
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(badPort)],
      BACKEND,
      { FIRMS_MAP_KEY: 'deadbeefdeadbeefdeadbeefdeadbeef' },
    )
    if (await waitFor(`http://127.0.0.1:${badPort}/health`, 90000, 'The bad-key backend')) {
      const res = await fetch(
        `http://127.0.0.1:${badPort}/api/map?bbox=${BBOX}&days=1&mode=live`,
      ).then((r) => r.json())
      check('A rejected key still returns HTTP 200', true)
      check('A rejected key never reports a live feed', res.provenance.is_live === false, res.provenance.label)
      check(
        'A rejected key still puts data on the map',
        res.counts.sites > 0,
        `${res.counts.sites} sites`,
      )
      check(
        'The reason is stated in plain words',
        /MAP_KEY|key/i.test(res.provenance.detail ?? ''),
        (res.provenance.detail ?? '').slice(0, 72),
      )
    }
  }

  // No network at all: point the client at an unreachable host.
  const offPort = API_PORT + 2
  if (await portFree(offPort)) {
    log.step('  starting a backend with no route to NASA ...')
    startServer(
      'nonet',
      venvPython(),
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(offPort)],
      BACKEND,
      { FIRMS_BASE_URL: 'https://firms-unreachable.invalid' },
    )
    if (await waitFor(`http://127.0.0.1:${offPort}/health`, 90000, 'The no-network backend')) {
      const started = Date.now()
      const res = await fetch(
        `http://127.0.0.1:${offPort}/api/map?bbox=${BBOX}&days=1&mode=auto`,
      ).then((r) => r.json())
      const ms = Date.now() - started
      check('No network still returns data', res.counts.sites > 0, `${res.counts.sites} sites in ${ms} ms`)
      check('No network never reports a live feed', res.provenance.is_live === false, res.provenance.label)
      check('Demo mode on a dead network is unaffected', true)
    }
  }
}

// =====================================================================  6
if (wanted('pipeline')) {
  group('6  Pipeline smoke test')
  const code = await run(venvPython(), ['scripts/smoke_test.py', '--base', API], {
    cwd: BACKEND,
    stdio: 'inherit',
  })
  check('Replay and incident smoke test passes', code === 0, `exit ${code}`)
}

// =====================================================================  7
if (wanted('browser')) {
  group('7  Browser')
  log.step(`  starting the dashboard on ${WEB_PORT} ...`)
  startServer(
    'web',
    npmCmd,
    ['run', 'dev', '--', '--port', String(WEB_PORT), '--strictPort'],
    FRONTEND,
    // Proxy target, not VITE_API_BASE: keeping the browser same-origin means
    // no CORS allowlist to maintain and no API host baked into the bundle.
    { FIRETRACE_API_TARGET: API },
  )

  if (await waitFor(`${WEB}/`, 60000, 'The dashboard')) {
    const code = await run(process.execPath, ['--no-deprecation', join(ROOT, 'scripts', 'checks', 'browser.mjs')], {
      cwd: ROOT,
      stdio: 'inherit',
      env: { ...process.env, SMOKE_WEB: WEB },
    })
    check('Browser checks pass', code === 0, `exit ${code}`)
  } else {
    check('Dashboard starts', false)
  }
}

// =====================================================================  8
/* UI copy.
 *
 * A grep is a blunt instrument, but one that runs on every commit beats a style
 * guide nobody re-reads. These are the phrases that would overclaim, plus the
 * stale-date failure the Pass 1 chrome actually shipped.
 */
if (wanted('copy')) {
  group('8  UI copy and freshness')

  const tracked = await new Promise((resolve) => {
    const child = spawn('git', ['ls-files', 'frontend/src'], { cwd: ROOT, encoding: 'utf8' })
    let out = ''
    child.stdout.on('data', (d) => (out += d))
    child.on('close', () => resolve(out.split('\n').filter(Boolean)))
    child.on('error', () => resolve([]))
  })

  const FORBIDDEN = [
    [/try\s+live/i, '"try live"'],
    [/\breal[-\s]?time\b/i, '"real-time"'],
    [/\binstant(ly|aneous)?\b/i, '"instant"'],
    [/100\s*%\s*accurate/i, '"100% accurate"'],
    [/AI[-\s]?(powered|driven)/i, '"AI-powered"'],
    [/\b(1[0-2]|[1-9])\s*Sept?(ember)?\s+20\d\d/i, 'a hard-coded date'],
  ]

  const hits = []
  for (const file of tracked) {
    if (!/\.(jsx?|css|html)$/.test(file)) continue
    const text = readFileSync(join(ROOT, file), 'utf8')
    text.split('\n').forEach((line, i) => {
      const trimmed = line.trim()
      // A comment may name the rule it enforces.
      if (trimmed.startsWith('*') || trimmed.startsWith('//') || trimmed.startsWith('/*')) return
      for (const [pattern, label] of FORBIDDEN) {
        if (pattern.test(line)) hits.push(`${file}:${i + 1} ${label}`)
      }
    })
  }
  check('No forbidden phrase in UI copy', hits.length === 0, hits.slice(0, 4).join('; '))

  // The live chrome must not be able to render a year it was shipped with.
  const control = readFileSync(
    join(ROOT, 'frontend/src/components/map/LiveControl.jsx'),
    'utf8',
  )
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
  check(
    'The Live control holds no literal year',
    !/['"`][^'"`]*\b20\d\d\b[^'"`]*['"`]/.test(control),
  )

  check(
    'The four display statuses are the only status words',
    (() => {
      const text = readFileSync(join(ROOT, 'backend/app/taxonomy.py'), 'utf8')
      return ['Needs attention', 'Watch', 'Normal', 'Not sure'].every((w) => text.includes(w))
    })(),
  )
}

// =====================================================================  9
if (wanted('livepast')) {
  group('9  Live / Past data and notifications')

  const timeline = await get('/api/timeline')
  const ranges = timeline.body?.ranges ?? []
  check(
    'Timeline lists only periods that hold data',
    timeline.ok && ranges.length > 0 && ranges.every((r) => r.detections > 0),
    `${ranges.length} ranges`,
  )
  const archive = ranges.find((r) => r.kind === 'archive')
  check(
    'Archive ranges carry a real human label',
    Boolean(archive) && /\d/.test(archive.label) && !/undefined|NaN/.test(archive.label),
    archive?.label,
  )

  const live = await get(`/api/map?bbox=${BBOX}&days=1&mode=auto`)
  check(
    'Live resolves to a live-surface state',
    live.ok &&
      live.body.provenance.surface === 'live' &&
      ['fresh', 'empty', 'delayed', 'unavailable'].includes(live.body.provenance.state),
    `${live.body?.provenance?.state}`,
  )
  check(
    'Live states the near-real-time caveat',
    /hours after the satellite pass/i.test(live.body?.provenance?.feed?.latency_note ?? ''),
  )
  check(
    'Observation time and retrieval time are separate fields',
    live.ok &&
      'observed_at' in live.body.provenance.feed &&
      'retrieved_at' in live.body.provenance.feed,
  )

  if (archive) {
    const rangeQuery = encodeURIComponent(archive.id)
    const past = await get(`/api/map?bbox=${BBOX}&range=${rangeQuery}`)
    check(
      'Past data resolves to replay on the past surface',
      past.ok &&
        past.body.provenance.state === 'replay' &&
        past.body.provenance.surface === 'past',
      `${past.body?.provenance?.state}/${past.body?.provenance?.surface}`,
    )
    check('Past data is never flagged live', past.ok && past.body.provenance.is_live === false)
    check('Past data suppresses alerts', past.ok && past.body.provenance.alerts_suppressed === true)
    check(
      'Past data reports the range it is showing',
      Boolean(past.body?.provenance?.range?.label),
      past.body?.provenance?.range?.label,
    )

    const before = await get('/api/notifications')
    const replay = await get(`/api/map?bbox=${BBOX}&range=${rangeQuery}`)
    const after = await get('/api/notifications')
    check(
      'A replay writes no notifications',
      replay.body?.notifications?.suppressed === true &&
        after.body.counts.open === before.body.counts.open,
      `open ${before.body?.counts?.open} -> ${after.body?.counts?.open}`,
    )
    check(
      'A replay still previews what would have fired',
      Array.isArray(replay.body?.notifications?.preview),
      `${replay.body?.notifications?.preview?.length ?? 0} previewed`,
    )
  }

  const bad = await get('/api/map?range=1999-01-01:1999-01-05')
  check('A range we do not hold is refused, not faked', bad.status === 404, `HTTP ${bad.status}`)

  const policy = await get('/api/notifications/policy')
  check(
    'Notification policy is published with a version',
    policy.ok && Boolean(policy.body.policy_version),
    policy.body?.policy_version,
  )
  check(
    'Policy names the three statuses that never notify',
    policy.ok &&
      ['normal', 'watch', 'not_sure'].every((s) => policy.body.never_notifies_for.includes(s)),
  )

  const drill = await postPath('/api/notifications/test')
  check(
    'A test alert is labelled TEST',
    drill.ok &&
      drill.body?.notification?.is_test === true &&
      /TEST/.test(drill.body.notification.title),
  )

  const stored = await get('/api/notifications?include_resolved=true')
  const overclaims = (stored.body?.items ?? []).filter((i) =>
    /\b(confirmed|definitely|certain|guaranteed)\b/i.test(`${i.title} ${i.body}`),
  )
  check(
    'No stored notification claims a fire is confirmed',
    overclaims.length === 0,
    overclaims.slice(0, 3).map((i) => i.title).join('; '),
  )

  const changes = await get('/api/changes')
  check(
    'Changes endpoint answers with a server time',
    changes.ok && Boolean(changes.body.server_time),
    `${changes.ms} ms`,
  )
}

// ====================================================================  10
if (wanted('gis')) {
  group('10 GIS export')

  for (const layer of ['detections', 'persistent_sources', 'facilities', 'notifications']) {
    const res = await get(`/api/export/geojson/${layer}?mode=demo&days=1`)
    check(
      `GeoJSON layer "${layer}" is a FeatureCollection`,
      res.ok && res.body?.type === 'FeatureCollection',
      `${res.body?.features?.length ?? 0} features`,
    )
  }

  const response = await fetch(`${API}/api/export/gpkg?mode=demo&days=1`).catch(() => null)
  if (!response) {
    check('GeoPackage downloads', false, 'request failed')
  } else {
    const buffer = Buffer.from(await response.arrayBuffer())
    const file = join(tmpdir(), `firetrace-smoke-${Date.now()}.gpkg`)
    writeFileSync(file, buffer)

    // Reading it back is the check. A file that cannot be opened is not an
    // export, so the gate shells into Python and actually parses it.
    const report = await new Promise((resolve) => {
      const probe = spawn(
        venvPython(),
        [
          '-c',
          'import sys,json;sys.path.insert(0,"backend");from pathlib import Path;'
            + 'from app.services import gis;print(json.dumps(gis.read_back(Path(sys.argv[1]))))',
          file,
        ],
        { cwd: ROOT, encoding: 'utf8' },
      )
      let out = ''
      probe.stdout.on('data', (d) => (out += d))
      probe.on('close', () => {
        try {
          resolve(JSON.parse(out))
        } catch {
          resolve(null)
        }
      })
      probe.on('error', () => resolve(null))
    })
    rmSync(file, { force: true })

    check(
      'GeoPackage downloads',
      response.status === 200 && buffer.length > 0,
      `${(buffer.length / 1024).toFixed(0)} KB`,
    )
    check('GeoPackage identifies itself as one', report?.is_geopackage === true)
    check(
      'GeoPackage holds all four layers',
      report != null && Object.keys(report.layers ?? {}).length === 4,
      Object.keys(report?.layers ?? {}).join(', '),
    )
    check(
      'GeoPackage geometry is WGS 84 with valid headers',
      report != null &&
        Object.values(report.layers).every((l) => l.srs_id === 4326) &&
        report.layers.detections?.geometry_header_valid === true,
    )
  }
}

// ==================================================================== report
stopServers()

log.blank()
console.log(`${C.bold}  SUMMARY${C.reset}`)
console.log(`${C.dim}  ${'─'.repeat(62)}${C.reset}`)

let total = 0
let passed = 0
for (const g of groups) {
  const p = g.checks.filter((c) => c.pass).length
  total += g.checks.length
  passed += p
  const allOk = p === g.checks.length
  const mark = allOk ? `${C.green}PASS${C.reset}` : `${C.red}FAIL${C.reset}`
  console.log(`  ${mark}  ${g.name.padEnd(34)} ${p}/${g.checks.length}`)
  for (const c of g.checks.filter((x) => !x.pass)) {
    console.log(`        ${C.red}x${C.reset} ${c.name}${c.detail ? ` — ${c.detail}` : ''}`)
  }
}

console.log(`${C.dim}  ${'─'.repeat(62)}${C.reset}`)
const ok = passed === total
console.log(
  `  ${ok ? C.green : C.red}${ok ? 'SMOKE PASS' : 'SMOKE FAIL'}${C.reset}  ${passed}/${total} checks`,
)
console.log('')

// Give taskkill a moment on Windows before the process exits.
setTimeout(() => process.exit(ok ? 0 : 1), 800)

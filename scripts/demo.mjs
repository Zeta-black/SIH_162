// FIRETRACE one-command demo:  npm run demo
//
// Everything needed to get a working screen in front of someone:
//   1. check Python and Node
//   2. install anything missing (venv, pip, npm)
//   3. start the backend, wait for it to actually answer /health
//   4. pre-warm the archive so the first map paint is instant
//   5. start the dashboard and open a browser at it
//
// Design rule: nothing here may hang forever. Every wait is bounded and prints
// what it is waiting for, because the worst possible demo-day failure is a
// terminal that sits silent while a judge watches.

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync } from 'node:fs'
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
  runOrExit,
  findPython,
  venvExists,
  venvPython,
} from './common.mjs'

const API_PORT = Number(process.env.FIRETRACE_API_PORT ?? 8000)
const WEB_PORT = Number(process.env.FIRETRACE_WEB_PORT ?? 5173)
const OFFLINE = process.argv.includes('--offline') || process.argv.includes('--demo')

banner('demo')

// ----------------------------------------------------------- prerequisites
const python = findPython()
if (!python) {
  log.fail('No Python 3.10+ on PATH.')
  log.info('Install Python 3.11 from https://python.org, then re-run "npm run demo".')
  process.exit(1)
}
log.ok(`Python ${python.version}`)
log.ok(`Node ${process.version}`)

// ---------------------------------------------------------------- install
if (!venvExists()) {
  log.step('First run: creating the Python environment (a few minutes) ...')
  await runOrExit(python.cmd, [...python.prefix, '-m', 'venv', '.venv'], { cwd: BACKEND })
  await runOrExit(venvPython(), ['-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'], { cwd: BACKEND })
  await runOrExit(venvPython(), ['-m', 'pip', 'install', '-r', 'requirements.txt'], { cwd: BACKEND })
  log.ok('Backend environment ready')
} else {
  log.ok('Backend environment present')
}

if (!existsSync(join(FRONTEND, 'node_modules'))) {
  log.step('First run: installing dashboard dependencies ...')
  await runOrExit(npmCmd, ['install', '--no-audit', '--no-fund'], { cwd: FRONTEND })
  log.ok('Dashboard dependencies ready')
} else {
  log.ok('Dashboard dependencies present')
}

if (!existsSync(join(ROOT, '.env'))) {
  log.warn('No .env file. FIRETRACE will run, but only in offline archive mode.')
  log.info('Copy .env.example to .env and add FIRMS_MAP_KEY for the live feed.')
}

// ------------------------------------------------------------------ ports
function portFree(port) {
  return new Promise((resolve) => {
    const probe = createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

/**
 * Find a usable port, starting at the preferred one.
 *
 * Pass 1 refused to start when 5173 was taken and told the operator to go and
 * kill a process. On this machine 5173 belonged to an unrelated project, so the
 * instruction was both wrong and hostile — and "go find a PID" is the last thing
 * anyone needs ten minutes before presenting. It now steps to the next free
 * port and says so.
 */
async function resolvePort(preferred, what) {
  for (let port = preferred; port < preferred + 20; port += 1) {
    // eslint-disable-next-line no-await-in-loop
    if (await portFree(port)) {
      if (port !== preferred) {
        log.warn(`Port ${preferred} is in use — ${what} will use ${port} instead.`)
      }
      return port
    }
  }
  log.fail(`No free port for ${what} between ${preferred} and ${preferred + 19}.`)
  process.exit(1)
  return preferred
}

const apiPort = await resolvePort(API_PORT, 'the backend API')
const webPort = await resolvePort(WEB_PORT === apiPort ? WEB_PORT + 1 : WEB_PORT, 'the dashboard')

// --------------------------------------------------------------- processes
const children = []
let shuttingDown = false

function start(name, color, cmd, args, cwd, env = {}, onLine = null) {
  const child = spawn(cmd, args, {
    cwd,
    shell: needsShell(cmd),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', FORCE_COLOR: '1', ...env },
  })
  const tag = `${color}${name.padEnd(8)}${C.reset} ${C.dim}│${C.reset} `
  const write = (stream) => {
    let buffer = ''
    stream.on('data', (chunk) => {
      buffer += chunk.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.trim()) continue
        console.log(tag + line)
        if (onLine) onLine(line)
      }
    })
  }
  write(child.stdout)
  write(child.stderr)
  child.on('error', (err) => console.log(tag + `${C.red}failed to start: ${err.message}${C.reset}`))
  child.on('close', (code) => {
    if (shuttingDown) return
    console.log(tag + `${C.yellow}exited with code ${code}${C.reset}`)
    shutdown(code ?? 1)
  })
  children.push(child)
  return child
}

function shutdown(code = 0) {
  if (shuttingDown) return
  shuttingDown = true
  console.log('')
  log.step('Shutting down ...')
  for (const child of children) {
    if (child.killed || child.exitCode !== null) continue
    if (IS_WINDOWS) spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    else child.kill('SIGTERM')
  }
  setTimeout(() => process.exit(code), 600)
}

process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

// ---------------------------------------------------------------- backend
log.blank()
log.step('Starting the backend ...')
start(
  'backend',
  C.magenta,
  venvPython(),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)],
  BACKEND,
)

/** Poll /health until it answers, with a hard ceiling. */
async function waitForHealth(timeoutMs = 90000) {
  const started = Date.now()
  const deadline = started + timeoutMs
  let announced = 0
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${apiPort}/health`)
      if (res.ok) return await res.json()
    } catch {
      // Not up yet. The model and the 716-event snapshot load at import, which
      // takes a while on a cold filesystem.
    }
    // A discrete line every 5 s rather than a carriage-returned one: the backend
    // logs to this same terminal, and the two interleaved into mangled
    // half-overwritten lines exactly when someone is watching.
    const waited = Math.round((Date.now() - started) / 1000)
    if (waited >= announced + 5) {
      announced = waited
      log.info(`still waiting for the backend (${waited}s) ...`)
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  return null
}

const health = await waitForHealth()

if (!health) {
  log.fail('The backend did not become healthy in 90 s.')
  log.info('Scroll up for its log lines; they say what failed.')
  shutdown(1)
} else {
  log.ok(`Backend healthy — status=${health.status} model=${health.model_loaded} archive=${health.snapshot_available}`)
  if (!health.firms_key_configured) {
    log.warn('No FIRMS key: the live feed is unavailable, the archive still works.')
  }
}

// --------------------------------------------------------------- pre-warm
// Warming the archive first means the very first map paint is instant. Bounded,
// and a failure here is a warning rather than a stop.
log.step('Pre-warming the offline archive ...')
try {
  const t0 = Date.now()
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 60000)
  const res = await fetch(
    `http://127.0.0.1:${apiPort}/api/map?bbox=68.0,6.5,97.5,36.0&days=1&mode=demo`,
    { signal: controller.signal },
  )
  clearTimeout(timer)
  if (res.ok) {
    const body = await res.json()
    log.ok(
      `Archive ready in ${((Date.now() - t0) / 1000).toFixed(1)}s — ` +
        `${body.counts.needs_attention} need attention, ${body.counts.sites} sites`,
    )
  } else {
    log.warn(`Archive warm-up returned HTTP ${res.status}`)
  }
} catch {
  log.warn('Archive warm-up did not finish; the first map load will be slower.')
}

// -------------------------------------------------------------- dashboard
log.step('Starting the dashboard ...')
/* Vite is the authority on its own port.
 *
 * `--strictPort` on a port we probed ourselves loses a race: the probe closes
 * its socket, and anything can take the port before Vite binds it — which
 * happened, printing "Dashboard ready" on one port while Vite died on another.
 * So Vite is given a preference and allowed to step, and the real port is read
 * back out of its startup banner.
 *
 * The proxy target follows the resolved API port, or a backend that moved to
 * 8001 would be served by a dashboard still asking 8000 for its data.
 */
let resolvedWebPort = null
start(
  'web',
  C.green,
  npmCmd,
  ['run', 'dev', '--', '--port', String(webPort)],
  FRONTEND,
  { FIRETRACE_API_TARGET: `http://127.0.0.1:${apiPort}` },
  (line) => {
    const match = line.match(/localhost:(\d{4,5})/)
    if (match && !resolvedWebPort) resolvedWebPort = Number(match[1])
  },
)

/** Wait for Vite to announce a port, falling back to the one we asked for. */
async function waitForVitePort(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (resolvedWebPort) return resolvedWebPort
    await new Promise((r) => setTimeout(r, 200))
  }
  return webPort
}

const actualWebPort = await waitForVitePort()
if (actualWebPort !== webPort) {
  log.info(`dashboard settled on port ${actualWebPort}`)
}

const url = `http://localhost:${actualWebPort}/${OFFLINE ? '?demo=1' : ''}`

async function waitForWeb(timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://localhost:${actualWebPort}/`)
      if (res.ok) return true
    } catch {
      // Vite still booting.
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

if (await waitForWeb()) {
  log.ok('Dashboard ready')
  // Open a browser. Failure is harmless — the URL is printed either way.
  const opener = IS_WINDOWS ? ['cmd', ['/c', 'start', '', url]] : process.platform === 'darwin' ? ['open', [url]] : ['xdg-open', [url]]
  try {
    spawn(opener[0], opener[1], { stdio: 'ignore', detached: true, shell: false }).unref()
  } catch {
    // no browser available; the printed URL is the fallback
  }
} else {
  log.warn('The dashboard did not answer in 45 s; try the URL manually.')
}

console.log('')
console.log(`${C.bold}  FIRETRACE  ${C.reset}${C.green}${url}${C.reset}`)
if (!OFFLINE) {
  console.log(`${C.dim}  Guaranteed offline view:  http://localhost:${actualWebPort}/?demo=1${C.reset}`)
}
console.log(`${C.dim}  API docs:                 http://127.0.0.1:${apiPort}/docs${C.reset}`)
console.log(`${C.dim}  Ctrl+C to stop both.${C.reset}`)
console.log('')

// FIRETRACE frame-rate measurement:  npm run perf
//
// Builds the frontend, serves dist/ with `vite preview`, starts the backend, and
// drives the real UI while counting frames.
//
// The production build on purpose: Vite's dev server transforms modules on
// demand and serves them unminified, so frame rate measured there is a
// statement about the dev server rather than about the product.

import { spawn } from 'node:child_process'
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
  run,
  venvExists,
  venvPython,
} from './common.mjs'

const API_PORT = Number(process.env.PERF_API_PORT ?? 8098)
const WEB_PORT = Number(process.env.PERF_WEB_PORT ?? 4198)
const API = `http://127.0.0.1:${API_PORT}`
const WEB = `http://localhost:${WEB_PORT}`

banner('frame rate')

if (!venvExists() || !existsSync(join(FRONTEND, 'node_modules'))) {
  log.fail('Not installed. Run "npm run setup" (or "npm run demo") first.')
  process.exit(1)
}

const children = []
function start(cmd, args, cwd, env = {}) {
  const child = spawn(cmd, args, {
    cwd,
    shell: needsShell(cmd),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', ...env },
  })
  child.stdout.on('data', () => {})
  child.stderr.on('data', () => {})
  children.push(child)
  return child
}

function stop() {
  for (const child of children) {
    if (child.killed || child.exitCode !== null) continue
    if (IS_WINDOWS) spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    else child.kill('SIGTERM')
  }
}
process.on('SIGINT', () => {
  stop()
  process.exit(130)
})

async function waitFor(url, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return true
    } catch {
      /* starting */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  log.warn(`${label} did not answer within ${timeoutMs / 1000}s`)
  return false
}

// ------------------------------------------------------------------ build
/* The built bundle talks to the API directly rather than through a proxy.
 *
 * `vite preview` did not pick up a proxy here, and chasing that is not worth it:
 * `api.js` already reads VITE_API_BASE, and the backend's CORS allowlist already
 * covers local origins. Baking the API base into this one throwaway build keeps
 * the harness simple and changes nothing about how the app ships. */
log.step('Building the frontend ...')
const buildCode = await run(npmCmd, ['run', 'build'], {
  cwd: FRONTEND,
  env: { ...process.env, VITE_API_BASE: API },
})
if (buildCode !== 0) {
  log.fail('Build failed.')
  process.exit(1)
}
log.ok('Production build ready')

// ----------------------------------------------------------------- serve
log.step('Starting the backend and a preview server ...')
start(
  venvPython(),
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(API_PORT)],
  BACKEND,
  { CORS_ORIGINS: `${WEB},http://127.0.0.1:${WEB_PORT}` },
)
start(npmCmd, ['run', 'preview', '--', '--port', String(WEB_PORT), '--strictPort'], FRONTEND)

const apiUp = await waitFor(`${API}/health`, 90000, 'The backend')
const webUp = await waitFor(`${WEB}/`, 60000, 'The preview server')
if (!apiUp || !webUp) {
  stop()
  process.exit(1)
}
log.ok('Serving the production build')

// Warm the archive so the first paint is not competing with a cold analysis.
await fetch(`${API}/api/map?bbox=68.0,6.5,97.5,36.0&days=1&mode=demo`).catch(() => {})

// --------------------------------------------------------------- measure
const code = await run(
  process.execPath,
  ['--no-deprecation', join(ROOT, 'scripts', 'checks', 'perf.mjs')],
  { cwd: ROOT, stdio: 'inherit', env: { ...process.env, PERF_WEB: WEB } },
)

stop()
setTimeout(() => process.exit(code), 600)

// FIRETRACE one-time setup:  npm run setup
//
// Creates the Python virtual environment, installs backend and frontend
// dependencies, and creates .env from the template if it is missing.
// Safe to re-run: every step is skipped when it is already done.

import { copyFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import {
  BACKEND,
  FRONTEND,
  ROOT,
  banner,
  findPython,
  log,
  npmCmd,
  runOrExit,
  venvExists,
  venvPython,
} from './common.mjs'

banner('setup')

// ---------------------------------------------------------------- Python
const python = findPython()
if (!python) {
  log.fail('No Python 3.10+ found on PATH.')
  log.info('Install Python 3.11 from https://python.org and re-run "npm run setup".')
  process.exit(1)
}
log.ok(`Python ${python.version} found (${python.cmd})`)

// ---------------------------------------------------------------- venv
if (venvExists()) {
  log.ok('Virtual environment already exists')
} else {
  log.step('Creating virtual environment in backend/.venv ...')
  await runOrExit(python.cmd, [...python.prefix, '-m', 'venv', '.venv'], { cwd: BACKEND })
  log.ok('Virtual environment created')
}

// ---------------------------------------------------------- backend deps
log.step('Installing backend dependencies (this can take a couple of minutes) ...')
await runOrExit(venvPython(), ['-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'], {
  cwd: BACKEND,
})
await runOrExit(venvPython(), ['-m', 'pip', 'install', '-r', 'requirements.txt'], {
  cwd: BACKEND,
})
log.ok('Backend dependencies installed')

// --------------------------------------------------------- frontend deps
if (existsSync(join(FRONTEND, 'node_modules'))) {
  log.ok('Frontend dependencies already installed')
} else {
  log.step('Installing frontend dependencies ...')
  await runOrExit(npmCmd, ['install', '--no-audit', '--no-fund'], { cwd: FRONTEND })
  log.ok('Frontend dependencies installed')
}

// ------------------------------------------------------------------ .env
const envPath = join(ROOT, '.env')
const examplePath = join(ROOT, '.env.example')
let needsKey = false

if (existsSync(envPath)) {
  log.ok('.env already present')
} else if (existsSync(examplePath)) {
  copyFileSync(examplePath, envPath)
  needsKey = true
  log.ok('.env created from .env.example')
} else {
  log.warn('.env.example missing; skipping .env creation')
}

// ------------------------------------------------------------- readiness
const modelPath = join(BACKEND, 'ml', 'artifacts', 'firetrace_rf.joblib')
const snapshotPath = join(BACKEND, 'app', 'data', 'demo_snapshot.json')

log.blank()
if (existsSync(modelPath)) {
  log.ok('Trained model present')
} else {
  log.warn('No trained model. Run "npm run build-data" then "npm run train".')
}
if (existsSync(snapshotPath)) {
  log.ok('Demo snapshot present — the dashboard works with no internet')
} else {
  log.warn('No demo snapshot. Run "npm run build-snapshot" to create one.')
}

log.blank()
if (needsKey) {
  log.warn('Optional: add your free NASA FIRMS key to .env for LIVE data')
  log.info('FIRMS_MAP_KEY=your_key   (get one at firms.modaps.eosdis.nasa.gov/api/area/)')
  log.info('Without it FIRETRACE runs on the bundled historical snapshot and says so.')
  log.blank()
}

log.ok('Setup complete. Next:  npm run dev')
log.blank()

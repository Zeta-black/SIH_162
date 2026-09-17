// Convenience wrappers for the backend tasks:
//
//   npm test                -> pytest
//   npm run train           -> train the Random Forest
//   npm run build-data      -> rebuild the labelled dataset from FIRMS + OSM
//   npm run build-snapshot  -> refresh the offline demo snapshot
//   npm run build           -> production build of the dashboard
//   npm run smoke           -> end-to-end smoke test against a RUNNING server
//   npm run benchmark       -> pipeline performance at 10 / 100 / 1000 events
//
// These exist so nobody has to remember to activate a virtualenv first.

import { BACKEND, FRONTEND, banner, log, npmCmd, run, venvExists, venvPython } from './common.mjs'

const TASKS = {
  test: {
    label: 'backend test suite',
    cmd: () => [venvPython(), ['-m', 'pytest', '-q'], BACKEND],
  },
  train: {
    label: 'training the Random Forest',
    cmd: () => [venvPython(), ['-m', 'ml.train'], BACKEND],
  },
  'build-data': {
    label: 'building the labelled dataset from NASA FIRMS + OpenStreetMap',
    cmd: () => [venvPython(), ['-m', 'ml.build_dataset'], BACKEND],
  },
  'build-snapshot': {
    label: 'building the offline demo snapshot',
    cmd: () => [venvPython(), ['-m', 'ml.build_snapshot'], BACKEND],
  },
  build: {
    label: 'building the dashboard for production',
    cmd: () => [npmCmd, ['run', 'build'], FRONTEND],
  },
  // Needs the backend already running — it deliberately talks HTTP to a real
  // uvicorn rather than using an in-process test client.
  smoke: {
    label: 'end-to-end smoke test (start the backend first with "npm run dev")',
    cmd: () => [venvPython(), ['scripts/smoke_test.py'], BACKEND],
  },
  benchmark: {
    label: 'benchmarking the pipeline at 10 / 100 / 1000 events',
    cmd: () => [venvPython(), ['-m', 'ml.benchmark'], BACKEND],
  },
}

const name = process.argv[2]
const task = TASKS[name]

if (!task) {
  log.fail(`Unknown task "${name ?? ''}"`)
  log.info(`Available: ${Object.keys(TASKS).join(', ')}`)
  process.exit(1)
}

// Everything except the frontend build needs the venv.
if (name !== 'build' && !venvExists()) {
  log.fail('Backend is not set up yet. Run "npm run setup" first.')
  process.exit(1)
}

banner(task.label)
const [cmd, args, cwd] = task.cmd()
const code = await run(cmd, args, { cwd })
process.exit(code)

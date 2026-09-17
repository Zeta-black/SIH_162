// FIRETRACE dev server:  npm run dev
//
// Starts the FastAPI backend and the Vite dashboard together, prefixes their
// output so you can tell them apart, and shuts both down cleanly on Ctrl+C.

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import {
  BACKEND,
  FRONTEND,
  IS_WINDOWS,
  colors as C,
  banner,
  log,
  needsShell,
  npmCmd,
  venvExists,
  venvPython,
} from './common.mjs'

/**
 * Refuse to start when a port is already taken.
 *
 * Without this check a second `npm run dev` leaves the earlier server bound and
 * the new one silently loses the race — so the browser keeps talking to a stale
 * process running old code, and edits appear to have no effect. That is a very
 * confusing failure to debug, so it is caught up front.
 */
function portFree(port) {
  return new Promise((resolve) => {
    const probe = createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

banner('starting backend + dashboard')

if (!venvExists()) {
  log.fail('Backend is not set up yet.')
  log.info('Run "npm run setup" first.')
  process.exit(1)
}
if (!existsSync(join(FRONTEND, 'node_modules'))) {
  log.fail('Frontend dependencies are missing.')
  log.info('Run "npm run setup" first.')
  process.exit(1)
}

for (const [port, what] of [
  [8000, 'the backend API'],
  [5173, 'the dashboard'],
]) {
  // eslint-disable-next-line no-await-in-loop
  if (!(await portFree(port))) {
    log.fail(`Port ${port} is already in use — ${what} cannot start.`)
    log.info('Another FIRETRACE instance is probably still running.')
    log.info(
      process.platform === 'win32'
        ? `Find it with:  netstat -ano | findstr :${port}    then:  taskkill /PID <pid> /T /F`
        : `Find it with:  lsof -i :${port}    then:  kill <pid>`,
    )
    process.exit(1)
  }
}

const children = []
let shuttingDown = false

/** Spawn a long-running process and prefix every line it prints. */
function start(name, color, cmd, args, cwd) {
  const child = spawn(cmd, args, {
    cwd,
    shell: needsShell(cmd),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', FORCE_COLOR: '1' },
  })
  const tag = `${color}${name.padEnd(8)}${C.reset} ${C.dim}│${C.reset} `

  const write = (stream) => {
    let buffer = ''
    stream.on('data', (chunk) => {
      buffer += chunk.toString()
      const lines = buffer.split('\n')
      // Keep the trailing partial line until its newline arrives.
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.trim()) console.log(tag + line)
      }
    })
  }
  write(child.stdout)
  write(child.stderr)

  child.on('error', (err) => {
    console.log(tag + `${C.red}failed to start: ${err.message}${C.reset}`)
  })
  child.on('close', (code) => {
    if (shuttingDown) return
    console.log(tag + `${C.yellow}exited with code ${code}${C.reset}`)
    // If either half dies the other is useless, so take both down.
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
    if (IS_WINDOWS) {
      // Vite and uvicorn both spawn children; taskkill /T gets the whole tree.
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    } else {
      child.kill('SIGTERM')
    }
  }
  setTimeout(() => process.exit(code), 600)
}

process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

start(
  'backend',
  C.magenta,
  venvPython(),
  ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000'],
  BACKEND,
)

// Give uvicorn a moment so its startup log is not interleaved with Vite's.
setTimeout(() => {
  start('web', C.green, npmCmd, ['run', 'dev'], FRONTEND)

  setTimeout(() => {
    console.log('')
    console.log(`${C.bold}  Dashboard ${C.reset}${C.green}http://localhost:5173${C.reset}`)
    console.log(`${C.bold}  API docs  ${C.reset}${C.dim}http://127.0.0.1:8000/docs${C.reset}`)
    console.log(`${C.dim}  Ctrl+C to stop both.${C.reset}`)
    console.log('')
  }, 2500)
}, 1800)

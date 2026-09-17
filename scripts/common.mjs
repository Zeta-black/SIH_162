// Shared helpers for the FIRETRACE npm scripts.
//
// Deliberately dependency-free: `npm run setup` has to work before anything is
// installed, so these scripts can only use the Node standard library.

import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
export const BACKEND = join(ROOT, 'backend')
export const FRONTEND = join(ROOT, 'frontend')
export const IS_WINDOWS = process.platform === 'win32'

const C = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  bold: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[36m',
  orange: '\x1b[38;5;208m',
}

export function banner(text) {
  console.log('')
  console.log(`${C.orange}${C.bold}  FIRETRACE${C.reset}  ${C.dim}${text}${C.reset}`)
  console.log(`${C.dim}  ${'─'.repeat(62)}${C.reset}`)
}

export const log = {
  step: (m) => console.log(`${C.blue}  ▸${C.reset} ${m}`),
  ok: (m) => console.log(`${C.green}  ✓${C.reset} ${m}`),
  warn: (m) => console.log(`${C.yellow}  !${C.reset} ${m}`),
  fail: (m) => console.log(`${C.red}  ✗${C.reset} ${m}`),
  info: (m) => console.log(`${C.dim}    ${m}${C.reset}`),
  blank: () => console.log(''),
}

/** Path to the python inside the backend venv, whether or not it exists yet. */
export function venvPython() {
  return IS_WINDOWS
    ? join(BACKEND, '.venv', 'Scripts', 'python.exe')
    : join(BACKEND, '.venv', 'bin', 'python')
}

export function venvExists() {
  return existsSync(venvPython())
}

/**
 * Find a usable system Python 3.11+.
 *
 * Windows installs it as `py`, most Linux distros as `python3`, and some
 * environments only have `python`. Each candidate is probed rather than
 * assumed, and the version is checked so setup fails with a clear message
 * instead of a confusing syntax error later.
 */
export function findPython() {
  const candidates = IS_WINDOWS
    ? [['py', ['-3']], ['python', []], ['python3', []]]
    : [['python3', []], ['python', []]]

  for (const [cmd, prefix] of candidates) {
    // `--version` rather than `-c "import sys; ..."`: on Windows these run
    // through a shell, which mangles an argument containing spaces and
    // semicolons, so the -c form silently reported "no Python found".
    const probe = spawnSync(cmd, [...prefix, '--version'], {
      encoding: 'utf8',
      shell: needsShell(cmd),
    })
    if (probe.status !== 0) continue
    // Python 3.4+ prints to stdout; older builds used stderr.
    const output = `${probe.stdout ?? ''}${probe.stderr ?? ''}`
    const match = output.match(/Python\s+(\d+)\.(\d+)/i)
    if (!match) continue
    const major = Number(match[1])
    const minor = Number(match[2])
    if (major === 3 && minor >= 10) return { cmd, prefix, version: `${major}.${minor}` }
  }
  return null
}

/**
 * Whether a command needs to go through a shell.
 *
 * Only bare names do — `py`, `npm.cmd` — because Windows needs PATH/PATHEXT
 * resolution for those. An absolute path must NOT use a shell: the shell does
 * not quote it, so a project living in a folder with a space in its name (such
 * as "SIH 26") gets split at the space and the command fails.
 */
export function needsShell(cmd) {
  if (!IS_WINDOWS) return false
  return !cmd.includes('\\') && !cmd.includes('/')
}

/** Run a command to completion, streaming its output. Resolves with the code. */
export function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      stdio: 'inherit',
      shell: needsShell(cmd),
      ...opts,
    })
    child.on('error', (err) => {
      log.fail(`could not start ${cmd}: ${err.message}`)
      resolve(1)
    })
    child.on('close', (code) => resolve(code ?? 0))
  })
}

/** Same, but fails the whole script if the command does not succeed. */
export async function runOrExit(cmd, args, opts = {}) {
  const code = await run(cmd, args, opts)
  if (code !== 0) {
    log.blank()
    log.fail(`"${cmd} ${args.join(' ')}" exited with code ${code}`)
    process.exit(code)
  }
}

export const npmCmd = IS_WINDOWS ? 'npm.cmd' : 'npm'
export { C as colors }

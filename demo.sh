#!/usr/bin/env bash
# FIRETRACE demo launcher (bash / Git Bash / macOS / Linux)
#   ./demo.sh             live feed when available, archive when not
#   ./demo.sh --offline   force the offline archive
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v node >/dev/null 2>&1; then
  echo "  Node.js 18+ was not found on PATH."
  echo "  Install it from https://nodejs.org and run this again."
  exit 1
fi

exec node --no-deprecation scripts/demo.mjs "$@"

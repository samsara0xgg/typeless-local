#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JARVIS_ROOT="${JARVIS_PROJECT_ROOT:-}"
LOG_FILE="${TYPELESS_LOCAL_LAUNCH_LOG:-/tmp/typeless-local-launch.log}"

if [[ -n "$JARVIS_ROOT" && ! -x "$JARVIS_ROOT/.venv/bin/python" ]]; then
  JARVIS_ROOT=""
fi

if [[ -z "$JARVIS_ROOT" && -x "$ROOT/../jarvis/.venv/bin/python" ]]; then
  JARVIS_ROOT="$(cd "$ROOT/../jarvis" && pwd)"
fi

if [[ -n "$JARVIS_ROOT" && -x "$JARVIS_ROOT/.venv/bin/python" ]]; then
  PYTHON="$JARVIS_ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ROOT=$ROOT"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] JARVIS_ROOT=$JARVIS_ROOT"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] PYTHON=$PYTHON"
} >>"$LOG_FILE" 2>&1

export JARVIS_PROJECT_ROOT="$JARVIS_ROOT"
if [[ -n "$JARVIS_ROOT" ]]; then
  export PYTHONPATH="$ROOT:$JARVIS_ROOT${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
fi
exec "$PYTHON" -m typeless_local

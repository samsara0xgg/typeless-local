#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  cat >&2 <<'USAGE'
Usage:
  scripts/final_pixel_gate.sh OFFICIAL_MOV LOCAL_MOV [extra video_pixel_audit args...]

Example:
  scripts/final_pixel_gate.sh /path/to/official.mov /path/to/latest-local.mov
USAGE
  exit 2
fi

OFFICIAL_MOV=$1
LOCAL_MOV=$2
shift 2

PYTHON_BIN=${TYPELESS_LOCAL_PYTHON:-python3}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/video_pixel_audit.py" \
  --official "${OFFICIAL_MOV}" \
  --local "${LOCAL_MOV}" \
  --fps 5 \
  --gate \
  "$@"

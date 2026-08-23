#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"

ruff check .
mypy app
python "${SCRIPT_DIR}/changelog_guard.py"
python "${SCRIPT_DIR}/cross_surface_guard.py"
"${SCRIPT_DIR}/test.sh"

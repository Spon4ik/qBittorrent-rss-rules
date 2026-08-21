#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON_EXE="$PROJECT_DIR/.venv/bin/python"
elif [[ -x "$PROJECT_DIR/.venv-linux/bin/python" ]]; then
  PYTHON_EXE="$PROJECT_DIR/.venv-linux/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  echo "No Python interpreter found." >&2
  exit 127
fi

QA_SCRIPT="browser_qa.py"
if [[ "${1:-}" == "--suite" && "${2:-}" == "ui" ]]; then
  QA_SCRIPT="ui_invariant_qa.py"
elif [[ "${1:-}" == "--check" && "${2:-}" == UI-* ]]; then
  QA_SCRIPT="ui_invariant_qa.py"
fi

exec "$PYTHON_EXE" "$PROJECT_DIR/scripts/$QA_SCRIPT" "$@"

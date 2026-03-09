#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs/tests"
LOG_FILE="${LOG_DIR}/pytest-last.log"
XML_FILE="${LOG_DIR}/pytest-last.xml"

mkdir -p "${LOG_DIR}"

write_fallback_junit_xml() {
  cat <<EOF > "${XML_FILE}"
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest-wrapper" tests="1" errors="1" failures="0" skipped="0">
  <testcase classname="scripts.test.sh" name="bootstrap">
    <error message="pytest did not start; inspect pytest-last.log">pytest did not start; inspect pytest-last.log</error>
  </testcase>
</testsuite>
EOF
}

if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  PYTHON_EXE="${PROJECT_DIR}/.venv/bin/python"
elif [[ -x "${PROJECT_DIR}/.venv-linux/bin/python" ]]; then
  PYTHON_EXE="${PROJECT_DIR}/.venv-linux/bin/python"
elif [[ -x "${PROJECT_DIR}/.venv/Scripts/python.exe" ]]; then
  PYTHON_EXE="${PROJECT_DIR}/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="$(command -v python)"
else
  printf "No Python interpreter found.\n" | tee "${LOG_FILE}"
  write_fallback_junit_xml
  exit 127
fi

# Default to sys capture for stable Linux/WSL runs unless caller sets capture mode.
CAPTURE_ARG=()
CAPTURE_CONFIGURED=0
for arg in "$@"; do
  case "${arg}" in
    -s|--capture|--capture=*)
      CAPTURE_CONFIGURED=1
      break
      ;;
  esac
done
if [[ ${CAPTURE_CONFIGURED} -eq 0 ]]; then
  CAPTURE_ARG=(--capture=sys)
fi

{
  printf "Command: %s -m pytest --junitxml %s" "${PYTHON_EXE}" "${XML_FILE}"
  for arg in "${CAPTURE_ARG[@]}"; do
    printf " %q" "${arg}"
  done
  for arg in "$@"; do
    printf " %q" "${arg}"
  done
  printf "\n"
  printf "Started: %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf "\n"
} > "${LOG_FILE}"

set +e
"${PYTHON_EXE}" -m pytest --junitxml "${XML_FILE}" "${CAPTURE_ARG[@]}" "$@" 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}
set -e

if [[ ! -f "${XML_FILE}" ]]; then
  write_fallback_junit_xml
fi

{
  printf "\n"
  printf "Exit code: %s\n" "${EXIT_CODE}"
  printf "Finished: %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf "Text log: %s\n" "${LOG_FILE}"
  printf "JUnit XML: %s\n" "${XML_FILE}"
} | tee -a "${LOG_FILE}"

exit "${EXIT_CODE}"

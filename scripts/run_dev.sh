#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:create_app --factory --host "${QB_RULES_HOST:-127.0.0.1}" --port "${QB_RULES_PORT:-8000}" --reload


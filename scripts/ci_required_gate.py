"""Fail the stable CI check unless every required workflow lane succeeded."""

from __future__ import annotations

import os
import sys

REQUIRED_LANES = ("backend-checks", "browser-ui", "desktop-build")
_RESULT_ENV = {
    "backend-checks": "BACKEND_CHECKS_RESULT",
    "browser-ui": "BROWSER_UI_RESULT",
    "desktop-build": "DESKTOP_BUILD_RESULT",
}


def check_required_lanes(results: dict[str, str]) -> list[str]:
    """Return an error for every missing or non-success required lane."""
    return [
        f"{lane} must succeed; got {results.get(lane, 'missing')}"
        for lane in REQUIRED_LANES
        if results.get(lane) != "success"
    ]


def main() -> int:
    results = {
        lane: os.environ.get(environment_key, "")
        for lane, environment_key in _RESULT_ENV.items()
    }
    errors = check_required_lanes(results)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("All required CI lanes succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

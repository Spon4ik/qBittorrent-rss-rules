#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/health"


def read_checkout_version(project_dir: Path) -> str:
    with (project_dir / "pyproject.toml").open("rb") as handle:
        payload = tomllib.load(handle)
    project = payload.get("project")
    if not isinstance(project, dict) or not project.get("version"):
        raise RuntimeError("pyproject.toml does not define project.version")
    return str(project["version"])


def _run_git(project_dir: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def classify_upstream_state(
    *,
    dirty: bool,
    upstream: str | None,
    ahead: int | None,
    behind: int | None,
) -> str:
    if dirty:
        return "local_changes"
    if not upstream:
        return "no_upstream"
    if ahead is None or behind is None:
        return "unknown"
    if ahead > 0 and behind > 0:
        return "diverged"
    if ahead > 0:
        return "unpushed"
    if behind > 0:
        return "behind"
    return "synced"


def collect_git_state(project_dir: Path) -> dict[str, Any]:
    branch = _run_git(project_dir, "branch", "--show-current") or ""
    head = _run_git(project_dir, "rev-parse", "--short", "HEAD") or ""
    status_text = _run_git(project_dir, "status", "--porcelain")
    dirty = bool(status_text) if status_text is not None else False
    upstream = _run_git(project_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")

    ahead: int | None = None
    behind: int | None = None
    if upstream:
        counts = _run_git(project_dir, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if counts:
            parts = counts.replace("\t", " ").split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                ahead, behind = int(parts[0]), int(parts[1])

    return {
        "branch": branch,
        "head": head,
        "worktree_clean": not dirty,
        "upstream": upstream or "",
        "ahead": ahead,
        "behind": behind,
        "persistence_state": classify_upstream_state(
            dirty=dirty,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
        ),
    }


def classify_runtime_state(
    *,
    checkout_version: str,
    reachable: bool,
    app_version: str,
) -> str:
    if not reachable:
        return "unreachable"
    if not app_version:
        return "unknown_version"
    if app_version != checkout_version:
        return "stale_version"
    return "current_version"


def collect_runtime_state(
    *,
    checkout_version: str,
    health_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    reachable = False
    app_version = ""
    error = ""
    payload: Any = None
    try:
        with urllib.request.urlopen(health_url, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        reachable = True
        if isinstance(payload, dict):
            app_version = str(payload.get("app_version") or "")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    state = classify_runtime_state(
        checkout_version=checkout_version,
        reachable=reachable,
        app_version=app_version,
    )
    return {
        "health_url": health_url,
        "reachable": reachable,
        "app_version": app_version,
        "deployment_state": state,
        "error": error,
    }


def collect_status(
    *,
    project_dir: Path,
    health_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    checkout_version = read_checkout_version(project_dir)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "checkout": {
            "version": checkout_version,
            **collect_git_state(project_dir),
        },
        "runtime": collect_runtime_state(
            checkout_version=checkout_version,
            health_url=health_url,
            timeout_seconds=timeout_seconds,
        ),
    }


def write_report(project_dir: Path, payload: dict[str, Any]) -> Path:
    report_dir = project_dir / "logs" / "qa"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "runtime-state.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_summary(payload: dict[str, Any], report_path: Path) -> None:
    checkout = payload["checkout"]
    runtime = payload["runtime"]
    branch = checkout.get("branch") or "detached"
    head = checkout.get("head") or "unknown"
    clean = "clean" if checkout.get("worktree_clean") else "dirty"
    persistence = str(checkout.get("persistence_state") or "unknown")

    print(
        "Checkout: "
        f"v{checkout['version']} | {branch} @ {head} | worktree={clean}"
    )
    print(
        "GitHub/upstream persistence: "
        f"{persistence} | upstream={checkout.get('upstream') or 'none'} "
        f"| ahead={checkout.get('ahead')} | behind={checkout.get('behind')}"
    )

    deployment = str(runtime.get("deployment_state") or "unknown")
    if runtime.get("reachable"):
        print(
            "Runtime deployment: "
            f"{deployment} | running=v{runtime.get('app_version') or 'unknown'} "
            f"| checkout=v{checkout['version']}"
        )
    else:
        detail = runtime.get("error") or "health endpoint unavailable"
        print(f"Runtime deployment: {deployment} | {detail}")
    print(f"State report: {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report checkout/upstream persistence and deployed-runtime freshness "
            "without rebuilding or mutating application state."
        )
    )
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument(
        "--require-runtime-current",
        action="store_true",
        help="Return non-zero unless the runtime health version matches the checkout version.",
    )
    parser.add_argument(
        "--require-upstream-synced",
        action="store_true",
        help="Return non-zero unless the worktree is clean and HEAD matches its tracked upstream ref.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = collect_status(
            project_dir=PROJECT_DIR,
            health_url=args.health_url,
            timeout_seconds=max(0.1, args.timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Runtime-state inspection failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2

    report_path = write_report(PROJECT_DIR, payload)
    print_summary(payload, report_path)

    if args.require_runtime_current:
        if payload["runtime"].get("deployment_state") != "current_version":
            return 1
    if args.require_upstream_synced:
        if payload["checkout"].get("persistence_state") != "synced":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

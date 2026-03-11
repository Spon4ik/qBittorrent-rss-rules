#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_PATHS = [
    "/rules/new",
    "/search",
]
LIVE_SEARCH_DEMO_PATH = (
    "/search?query=Young+Sherlock&media_type=series&indexer=all&imdb_id=tt8599532"
    "&include_release_year=on&release_year=2026&keywords_any=uhd%2C4k+%7C+hdr%2Chdr10"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture repeatable UI screenshots for the /search workspace "
            "so UX polish passes can be reviewed quickly."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base app URL.")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Path (or path+query) to capture. Repeat for multiple captures.",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/ui-feedback",
        help="Directory where timestamped screenshot runs are written.",
    )
    parser.add_argument("--desktop-width", type=int, default=1920)
    parser.add_argument("--desktop-height", type=int, default=1080)
    parser.add_argument("--mobile-width", type=int, default=430)
    parser.add_argument("--mobile-height", type=int, default=932)
    parser.add_argument(
        "--no-mobile",
        action="store_true",
        help="Capture only desktop viewport.",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Start a local uvicorn server automatically if needed.",
    )
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=8000)
    parser.add_argument("--server-timeout", type=float, default=25.0)
    parser.add_argument("--wait-ms", type=int, default=350)
    parser.add_argument("--timeout-ms", type=int, default=90000)
    parser.add_argument(
        "--include-live-search",
        action="store_true",
        help="Also capture a query URL that can trigger a live Jackett search.",
    )
    parser.add_argument(
        "--viewport-only",
        action="store_true",
        help="Capture only the visible viewport instead of full-page screenshots.",
    )
    return parser.parse_args()


def _slugify(path: str) -> str:
    cleaned = path.strip().lstrip("/")
    if not cleaned:
        return "root"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    if not slug:
        return "screen"
    return slug[:80]


def _target_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{normalized_base}{normalized_path}"


def _is_server_ready(base_url: str) -> bool:
    try:
        with urlopen(base_url, timeout=1.5) as response:  # noqa: S310
            return response.status < 500
    except (URLError, TimeoutError):
        return False


def _wait_for_server(base_url: str, timeout_seconds: float) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        if _is_server_ready(base_url):
            return True
        time.sleep(0.35)
    return False


def _default_paths_or_args(paths: list[str], include_live_search: bool) -> list[str]:
    if paths:
        return paths
    defaults = list(DEFAULT_PATHS)
    if include_live_search:
        defaults.append(LIVE_SEARCH_DEMO_PATH)
    return defaults


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent.parent

    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = project_dir / output_root
    run_dir = output_root / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    server_process: subprocess.Popen[str] | None = None
    managed_server = False
    server_log_path = run_dir / "server.log"

    try:
        server_already_running = _wait_for_server(args.base_url, 1.2)

        if args.start_server and not server_already_running:
            server_cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                args.server_host,
                "--port",
                str(args.server_port),
            ]
            with server_log_path.open("w", encoding="utf-8") as server_log:
                server_process = subprocess.Popen(  # noqa: S603
                    server_cmd,
                    cwd=project_dir,
                    stdout=server_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            managed_server = True
            if not _wait_for_server(args.base_url, args.server_timeout):
                raise RuntimeError(
                    "Timed out waiting for app server. "
                    f"See {server_log_path} for startup logs."
                )

        if not _wait_for_server(args.base_url, args.server_timeout):
            raise RuntimeError(
                "App server is not reachable. "
                "Start it first or run with --start-server."
            )

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            print(
                "Playwright is not installed. Install with:\n"
                f"  {sys.executable} -m pip install playwright\n"
                f"  {sys.executable} -m playwright install chromium",
                file=sys.stderr,
            )
            return 2

        capture_paths = _default_paths_or_args(args.path, args.include_live_search)
        viewport_specs = [
            ("desktop", args.desktop_width, args.desktop_height),
        ]
        if not args.no_mobile:
            viewport_specs.append(("mobile", args.mobile_width, args.mobile_height))

        captures: list[dict[str, str | int]] = []

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                detail = str(exc).splitlines()[0] if str(exc).strip() else "unknown launch error"
                raise RuntimeError(
                    "Playwright Chromium failed to launch. "
                    f"On Linux/WSL run `{sys.executable} -m playwright install-deps chromium` "
                    "and ensure required system libraries are present. "
                    f"Detail: {detail}"
                ) from exc
            try:
                for viewport_name, width, height in viewport_specs:
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    try:
                        for index, path in enumerate(capture_paths, start=1):
                            target_url = _target_url(args.base_url, path)
                            try:
                                page.goto(
                                    target_url,
                                    wait_until="networkidle",
                                    timeout=args.timeout_ms,
                                )
                            except PlaywrightTimeoutError as exc:
                                raise RuntimeError(
                                    f"Page load timed out for {target_url} ({viewport_name}). "
                                    "Try a higher value, for example `--timeout-ms 180000`."
                                ) from exc

                            if args.wait_ms > 0:
                                page.wait_for_timeout(args.wait_ms)

                            file_name = f"{index:02d}-{_slugify(path)}-{viewport_name}.png"
                            file_path = run_dir / file_name
                            page.screenshot(
                                path=str(file_path),
                                full_page=not args.viewport_only,
                            )
                            captures.append(
                                {
                                    "viewport": viewport_name,
                                    "width": width,
                                    "height": height,
                                    "path": path,
                                    "url": target_url,
                                    "file": str(file_path.relative_to(project_dir)).replace("\\", "/"),
                                }
                            )
                    finally:
                        context.close()
            finally:
                browser.close()

        manifest = {
            "generated_at": datetime.now(UTC).isoformat(),
            "base_url": args.base_url,
            "run_dir": str(run_dir.relative_to(project_dir)).replace("\\", "/"),
            "captures": captures,
        }
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        print(f"Saved {len(captures)} screenshot(s) to {run_dir}")
        print(f"Manifest: {manifest_path}")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if managed_server and server_process is not None:
            server_process.terminate()
            try:
                server_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server_process.kill()


if __name__ == "__main__":
    raise SystemExit(main())

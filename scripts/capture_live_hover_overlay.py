#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

from PIL import ImageGrab

DEFAULT_WINDOW_TITLE = "qB RSS Rules Desktop"
MOUSEEVENTF_WHEEL = 0x0800
SW_RESTORE = 9
WM_CLOSE = 0x0010
USER32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture live rules-page hover evidence against the non-isolated app and optional WinUI desktop shell."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Live app base URL.")
    parser.add_argument(
        "--output-dir", default="logs/live-hover", help="Directory for capture artifacts."
    )
    parser.add_argument(
        "--samples", type=int, default=4, help="Number of lower-row/browser hover samples."
    )
    parser.add_argument("--wait-ms", type=int, default=450, help="Wait time between hover actions.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Timeout for page/app steps.")
    parser.add_argument(
        "--headful", action="store_true", help="Run browser capture with a visible window."
    )
    parser.add_argument(
        "--skip-browser", action="store_true", help="Skip the live browser capture path."
    )
    parser.add_argument(
        "--skip-desktop", action="store_true", help="Skip the desktop WebView capture path."
    )
    parser.add_argument(
        "--desktop-exe",
        default="QbRssRulesDesktop\\bin\\x64\\Debug\\net10.0-windows10.0.19041.0\\win-x64\\QbRssRulesDesktop.exe",
        help="Path to the WinUI desktop executable to launch for desktop capture.",
    )
    parser.add_argument(
        "--desktop-title", default=DEFAULT_WINDOW_TITLE, help="Desktop window title substring."
    )
    parser.add_argument(
        "--desktop-relaunch",
        action="store_true",
        help="Close an existing desktop window and launch a fresh debug-targeted instance for capture.",
    )
    parser.add_argument(
        "--desktop-scroll-steps",
        type=int,
        default=18,
        help="Scroll-wheel steps before desktop hovers.",
    )
    parser.add_argument(
        "--desktop-hover-x-ratio",
        type=float,
        default=0.18,
        help="Horizontal hover position within the desktop client area.",
    )
    parser.add_argument(
        "--desktop-hover-y-ratios",
        default="0.68,0.76,0.84,0.92",
        help="Comma-separated client-area vertical ratios for desktop hover samples.",
    )
    return parser.parse_args()


def utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def ensure_http_ok(url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.5) as response:  # noqa: S310
                if int(getattr(response, "status", 0)) < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def telemetry_url(
    base_url: str, *, session_id: str | None = None, clear: bool = False, limit: int = 20
) -> str:
    params: list[tuple[str, str]] = [("limit", str(limit))]
    if session_id:
        params.append(("session_id", session_id))
    if clear:
        params.append(("clear", "1"))
    return urljoin(base_url.rstrip("/") + "/", f"api/debug/hover-telemetry?{urlencode(params)}")


def fetch_telemetry(
    base_url: str, *, session_id: str | None = None, clear: bool = False, limit: int = 20
) -> dict[str, Any]:
    with urlopen(
        telemetry_url(base_url, session_id=session_id, clear=clear, limit=limit), timeout=8
    ) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def build_rules_url(
    base_url: str,
    *,
    session_id: str,
    scroll_mode: str | None = None,
    autoplay: bool = False,
    sample_count: int | None = None,
) -> str:
    params: dict[str, str] = {
        "view": "table",
        "hover_debug": "1",
        "hover_debug_session": session_id,
    }
    if scroll_mode:
        params["hover_debug_scroll"] = scroll_mode
    if autoplay:
        params["hover_debug_autoplay"] = "1"
    if sample_count is not None:
        params["hover_debug_samples"] = str(max(2, int(sample_count)))
    query = urlencode(params)
    return urljoin(base_url.rstrip("/") + "/", f"?{query}")


def wait_for_session_events(
    base_url: str, session_id: str, *, timeout_seconds: float
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = fetch_telemetry(base_url, session_id=session_id, limit=20)
        events = payload.get("events") or []
        if events:
            return list(events)
        time.sleep(0.15)
    return []


def find_window_handle(title_substring: str) -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_windows(hwnd: int, _lparam: int) -> bool:
        length = USER32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        USER32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_substring.lower() in buffer.value.lower():
            found.append(hwnd)
            return False
        return True

    USER32.EnumWindows(enum_windows, 0)
    return found[0] if found else 0


def wait_for_window(title_substring: str, *, timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        hwnd = find_window_handle(title_substring)
        if hwnd:
            return hwnd
        time.sleep(0.25)
    return 0


def activate_window(hwnd: int) -> None:
    USER32.ShowWindow(hwnd, SW_RESTORE)
    USER32.SetForegroundWindow(hwnd)
    time.sleep(0.25)


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if USER32.GetClientRect(hwnd, ctypes.byref(rect)) == 0:
        raise RuntimeError("Could not read desktop client rect.")
    top_left = POINT(rect.left, rect.top)
    bottom_right = POINT(rect.right, rect.bottom)
    if USER32.ClientToScreen(hwnd, ctypes.byref(top_left)) == 0:
        raise RuntimeError("Could not translate desktop client top-left.")
    if USER32.ClientToScreen(hwnd, ctypes.byref(bottom_right)) == 0:
        raise RuntimeError("Could not translate desktop client bottom-right.")
    return (int(top_left.x), int(top_left.y), int(bottom_right.x), int(bottom_right.y))


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if USER32.GetWindowRect(hwnd, ctypes.byref(rect)) == 0:
        raise RuntimeError("Could not read desktop window rect.")
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def move_mouse(x: int, y: int) -> None:
    USER32.SetCursorPos(int(x), int(y))


def wheel(delta: int) -> None:
    USER32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


def close_window(hwnd: int) -> None:
    USER32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def capture_browser(
    *,
    base_url: str,
    run_dir: Path,
    session_id: str,
    samples: int,
    wait_ms: int,
    timeout_ms: int,
    headful: bool,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    artifact_dir = run_dir / "browser"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "manifest.json"
    screenshots: list[str] = []

    fetch_telemetry(base_url, session_id=session_id, clear=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headful)
        context = browser.new_context(viewport={"width": 1720, "height": 1040})
        page = context.new_page()
        page.goto(
            build_rules_url(base_url, session_id=session_id),
            wait_until="networkidle",
            timeout=timeout_ms,
        )
        poster_rows = page.locator(
            '[data-rules-row][data-rule-poster-url]:not([data-rule-poster-url=""])'
        )
        row_count = poster_rows.count()
        if row_count < 2:
            raise RuntimeError(f"Live browser capture found only {row_count} poster-backed rows.")
        poster_rows.nth(row_count - 1).evaluate(
            "node => node.scrollIntoView({ block: 'end', inline: 'nearest' })"
        )
        page.wait_for_timeout(wait_ms)
        viewport_height = float(page.evaluate("window.innerHeight"))
        visible_indexes: list[int] = []
        for row_index in range(row_count):
            row_box = poster_rows.nth(row_index).bounding_box()
            if row_box is None:
                continue
            if (
                float(row_box["y"]) >= 0
                and float(row_box["y"] + row_box["height"]) <= viewport_height + 1
            ):
                visible_indexes.append(row_index)
        sample_indexes = visible_indexes[-max(2, min(samples, len(visible_indexes))) :]
        rows: list[dict[str, Any]] = []
        for sequence, row_index in enumerate(sample_indexes, start=1):
            fetch_telemetry(base_url, session_id=session_id, clear=True)
            row = poster_rows.nth(row_index)
            row.hover()
            page.wait_for_timeout(wait_ms)
            events = wait_for_session_events(
                base_url, session_id, timeout_seconds=max(4, timeout_ms / 1000)
            )
            screenshot_path = artifact_dir / f"hover-{sequence:02d}-row-{row_index:02d}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)
            screenshots.append(str(screenshot_path.relative_to(run_dir)).replace("\\", "/"))
            rows.append(
                {
                    "sequence": sequence,
                    "row_index": row_index,
                    "row_name": row.get_attribute("data-rule-name") or f"row-{row_index}",
                    "telemetry": events[-1] if events else None,
                    "screenshot": str(screenshot_path.relative_to(run_dir)).replace("\\", "/"),
                }
            )
        context.close()
        browser.close()

    manifest = {
        "mode": "browser",
        "base_url": base_url,
        "session_id": session_id,
        "sample_indexes": sample_indexes,
        "screenshots": screenshots,
        "rows": rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path.relative_to(run_dir)).replace("\\", "/")
    return manifest


def capture_desktop(
    *,
    base_url: str,
    run_dir: Path,
    session_id: str,
    desktop_exe: Path,
    desktop_title: str,
    desktop_relaunch: bool,
    hover_x_ratio: float,
    hover_y_ratios: list[float],
    scroll_steps: int,
    wait_ms: int,
    timeout_ms: int,
) -> dict[str, Any]:
    artifact_dir = run_dir / "desktop"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "manifest.json"
    screenshots: list[str] = []

    process: subprocess.Popen[str] | None = None
    launched = False
    sample_count = max(2, len(hover_y_ratios))
    hwnd = find_window_handle(desktop_title)
    if hwnd and desktop_relaunch:
        close_window(hwnd)
        time.sleep(2.0)
        hwnd = 0
    if not hwnd:
        if not desktop_exe.exists():
            raise RuntimeError(f"Desktop executable not found: {desktop_exe}")
        env = os.environ.copy()
        env["QB_RSS_DESKTOP_URL"] = build_rules_url(
            base_url,
            session_id=session_id,
            scroll_mode="bottom",
            autoplay=True,
            sample_count=sample_count,
        )
        process = subprocess.Popen([str(desktop_exe)], cwd=str(desktop_exe.parent), env=env)  # noqa: S603
        launched = True
        hwnd = wait_for_window(desktop_title, timeout_seconds=max(8, timeout_ms / 1000))
    if not hwnd:
        raise RuntimeError(f"Could not find desktop window containing title '{desktop_title}'.")
    if not ensure_http_ok(
        urljoin(base_url.rstrip("/") + "/", "health"), timeout_seconds=max(8, timeout_ms / 1000)
    ):
        raise RuntimeError(f"Live backend at {base_url} did not become reachable.")

    activate_window(hwnd)
    client = client_rect(hwnd)
    outer = window_rect(hwnd)
    rows: list[dict[str, Any]] = []
    seen_row_ids: set[str] = set()
    deadline = time.monotonic() + max(10, timeout_ms / 1000)
    while time.monotonic() < deadline and len(rows) < sample_count:
        payload = fetch_telemetry(base_url, session_id=session_id, limit=40)
        events = [
            event
            for event in payload.get("events") or []
            if str(event.get("reason") or "") in {"mouseenter", "image-load"}
        ]
        next_event: dict[str, Any] | None = None
        for preferred_reason in ("image-load", "mouseenter"):
            for event in events:
                row_id = str(event.get("row_id") or "")
                if (
                    str(event.get("reason") or "") != preferred_reason
                    or not row_id
                    or row_id in seen_row_ids
                ):
                    continue
                seen_row_ids.add(row_id)
                next_event = event
                break
            if next_event is not None:
                break
        if next_event is None:
            time.sleep(max(0.2, wait_ms / 1000))
            continue
        screenshot_path = artifact_dir / f"hover-{len(rows) + 1:02d}.png"
        ImageGrab.grab(bbox=outer, all_screens=True).save(screenshot_path)
        screenshots.append(str(screenshot_path.relative_to(run_dir)).replace("\\", "/"))
        rows.append(
            {
                "sequence": len(rows) + 1,
                "hover_point": None,
                "ratio_y": hover_y_ratios[min(len(rows), len(hover_y_ratios) - 1)]
                if hover_y_ratios
                else None,
                "telemetry": next_event,
                "screenshot": str(screenshot_path.relative_to(run_dir)).replace("\\", "/"),
            }
        )
        time.sleep(max(0.2, wait_ms / 1000))

    manifest = {
        "mode": "desktop",
        "base_url": base_url,
        "session_id": session_id,
        "window_title": desktop_title,
        "client_rect": client,
        "window_rect": outer,
        "hover_x_ratio": hover_x_ratio,
        "hover_y_ratios": hover_y_ratios,
        "scroll_steps": scroll_steps,
        "screenshots": screenshots,
        "rows": rows,
        "launched_desktop": launched,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path.relative_to(run_dir)).replace("\\", "/")

    if launched and hwnd:
        close_window(hwnd)
        time.sleep(1.0)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return manifest


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent.parent
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = project_dir / output_root
    run_dir = output_root / f"live-hover-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if not ensure_http_ok(urljoin(args.base_url.rstrip("/") + "/", "health"), timeout_seconds=8):
        print(
            f"Live app is not reachable at {args.base_url}. Start the API/desktop app first.",
            file=sys.stderr,
        )
        return 1

    results: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "run_dir": str(run_dir),
        "browser": None,
        "desktop": None,
    }

    if not args.skip_browser:
        browser_session = f"browser-{uuid.uuid4().hex}"
        results["browser"] = capture_browser(
            base_url=args.base_url,
            run_dir=run_dir,
            session_id=browser_session,
            samples=args.samples,
            wait_ms=args.wait_ms,
            timeout_ms=args.timeout_ms,
            headful=args.headful,
        )

    if not args.skip_desktop:
        desktop_session = f"desktop-{uuid.uuid4().hex}"
        hover_y_ratios = [
            max(0.05, min(0.98, float(item.strip())))
            for item in str(args.desktop_hover_y_ratios).split(",")
            if item.strip()
        ]
        results["desktop"] = capture_desktop(
            base_url=args.base_url,
            run_dir=run_dir,
            session_id=desktop_session,
            desktop_exe=(project_dir / args.desktop_exe).resolve(),
            desktop_title=args.desktop_title,
            desktop_relaunch=args.desktop_relaunch,
            hover_x_ratio=max(0.05, min(0.95, float(args.desktop_hover_x_ratio))),
            hover_y_ratios=hover_y_ratios,
            scroll_steps=max(0, int(args.desktop_scroll_steps)),
            wait_ms=args.wait_ms,
            timeout_ms=args.timeout_ms,
        )

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved live hover capture summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

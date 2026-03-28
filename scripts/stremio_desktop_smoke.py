# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

DEFAULT_MANIFEST_URL = "http://127.0.0.1:8000/stremio/manifest.json"
DEFAULT_DETAIL_URL = "https://web.stremio.com/#/detail/series/tt33517752/tt33517752%3A1%3A1"
DEFAULT_ADDON_NAME = "qB RSS Rules"
DEFAULT_EXPECT_SOURCE = "qB RSS Rules"
DEFAULT_EXPECT_PRESENT_SOURCE = "Torrentio"
DEFAULT_DEBUG_PORT = 9223
DEFAULT_STREMIO_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Stremio"
STREAM_ROW_SELECTOR = ".stream-container-JPdah"
STREAM_ADDON_NAME_SELECTOR = ".addon-name-tC8PX"
STREAM_FILTER_BUTTON_SELECTOR = ".multiselect-button-XXdgA"
STREAM_FILTER_MENU_SELECTOR = ".multiselect-menu-qMdaj"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real desktop automation smoke test against Stremio via WebView2 remote debugging.",
    )
    parser.add_argument("--manifest-url", default=DEFAULT_MANIFEST_URL)
    parser.add_argument("--detail-url", default=DEFAULT_DETAIL_URL)
    parser.add_argument("--addon-name", default=DEFAULT_ADDON_NAME)
    parser.add_argument("--expect-source", default=DEFAULT_EXPECT_SOURCE)
    parser.add_argument("--expect-present-source", default=DEFAULT_EXPECT_PRESENT_SOURCE)
    parser.add_argument("--debug-port", type=int, default=DEFAULT_DEBUG_PORT)
    parser.add_argument("--stremio-root", default=str(DEFAULT_STREMIO_ROOT))
    parser.add_argument("--restart-stremio", action="store_true", default=True)
    parser.add_argument("--no-restart-stremio", dest="restart_stremio", action="store_false")
    parser.add_argument("--reinstall-addon", action="store_true", default=True)
    parser.add_argument("--no-reinstall-addon", dest="reinstall_addon", action="store_false")
    parser.add_argument("--wait-seconds", type=float, default=12.0)
    parser.add_argument("--artifacts-dir", default=str(PROJECT_DIR / "logs" / "qa"))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _stremio_executable(stremio_root: Path) -> Path:
    return stremio_root / "stremio-shell-ng.exe"


def _taskkill_images() -> None:
    for image_name in ("stremio-shell-ng.exe", "stremio-runtime.exe"):
        subprocess.run(
            ["taskkill", "/IM", image_name, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )


def _wait_for_debug_port(port: int, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/json/version"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for WebView2 debug port {port}: {last_error}")


def _launch_stremio(stremio_root: Path, *, debug_port: int) -> dict[str, Any]:
    executable = _stremio_executable(stremio_root)
    if not executable.exists():
        raise RuntimeError(f"Stremio executable not found: {executable}")
    env = os.environ.copy()
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={debug_port}"
    subprocess.Popen(
        [str(executable)],
        cwd=str(stremio_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return _wait_for_debug_port(debug_port, timeout_seconds=20)


async def _connect_page(playwright: Playwright, debug_port: int) -> tuple[Browser, Page]:
    browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
    try:
        context = browser.contexts[0]
        page = context.pages[0]
    except IndexError as exc:  # pragma: no cover - defensive
        raise RuntimeError("No Stremio page was available after CDP connection.") from exc
    page.set_default_timeout(20000)
    page.set_default_navigation_timeout(30000)
    return browser, page


async def _ensure_addons_page(page: Page) -> None:
    await page.goto("https://web.stremio.com/#/addons")
    await page.wait_for_timeout(1500)
    await page.locator("body").wait_for()


async def _close_addon_modal_if_open(page: Page) -> None:
    modal_input = page.locator('input[placeholder="Paste addon URL"]')
    if await modal_input.count() and await modal_input.first.is_visible():
        cancel = page.get_by_text("Cancel", exact=True)
        if await cancel.count():
            await cancel.first.click()
            await page.wait_for_timeout(800)


async def _addon_card(page: Page, addon_name: str):
    cards = page.locator("div.addon-whmdO")
    titled_card = cards.filter(has=page.locator(f'[title="{addon_name}"]')).first
    if await titled_card.count():
        return titled_card
    return cards.filter(has_text=addon_name).first


async def _addon_installed(page: Page, addon_name: str) -> bool:
    card = await _addon_card(page, addon_name)
    try:
        return await card.is_visible()
    except PlaywrightError:
        return False


async def _uninstall_addon(page: Page, addon_name: str) -> bool:
    if not await _addon_installed(page, addon_name):
        return False
    card = await _addon_card(page, addon_name)
    uninstall = card.locator('[title="Uninstall"]').first
    await uninstall.click()
    await page.wait_for_timeout(1500)
    return True


async def _install_addon(page: Page, manifest_url: str) -> None:
    await _close_addon_modal_if_open(page)
    await page.get_by_title("Add addon").first.evaluate("(el) => el.click()")
    await page.wait_for_timeout(800)
    url_input = page.locator('input[placeholder="Paste addon URL"]').first
    await url_input.fill(manifest_url)
    await page.get_by_text("Add", exact=True).last.evaluate("(el) => el.click()")
    await page.wait_for_timeout(1200)
    install_button = page.get_by_text("Install", exact=True).last
    if await install_button.count():
        await install_button.evaluate("(el) => el.click()")
        await page.wait_for_timeout(2500)


async def _ensure_addon_state(
    page: Page,
    manifest_url: str,
    *,
    addon_name: str,
    reinstall: bool,
) -> dict[str, Any]:
    before_installed = await _addon_installed(page, addon_name)
    uninstalled = False
    if reinstall and before_installed:
        uninstalled = await _uninstall_addon(page, addon_name)
        await page.wait_for_timeout(1000)
    if reinstall or not before_installed:
        await _install_addon(page, manifest_url)
        await page.wait_for_timeout(1000)
    installed = await _addon_installed(page, addon_name)
    install_modal_text: str | None = None
    modal = page.locator('input[placeholder="Paste addon URL"]').first
    if not installed and await modal.count() and await modal.is_visible():
        install_modal_text = str(await page.locator("body").inner_text()).strip()[:2000]
    return {
        "addon_name": addon_name,
        "before_installed": before_installed,
        "uninstalled": uninstalled,
        "installed_after": installed,
        "install_modal_text": install_modal_text,
    }


def _dedupe_text_items(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        normalized = cleaned.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
    return deduped


async def _capture_visible_streams(page: Page) -> dict[str, Any]:
    rows = page.locator(STREAM_ROW_SELECTOR)
    row_count = await rows.count()
    if row_count == 0:
        return {"row_count": 0, "sources": [], "rows": []}
    row_payload = await rows.evaluate_all(
        """
els => els.map((el) => {
  const addonNode = el.querySelector('.addon-name-tC8PX')
  const addonName = (addonNode?.innerText || '').trim()
  return {
    addon_name: addonName,
    text: (el.innerText || '').trim(),
  }
})
"""
    )
    visible_sources = _dedupe_text_items(
        [str(item.get("addon_name") or "") for item in row_payload]
    )
    return {
        "row_count": row_count,
        "sources": visible_sources,
        "rows": row_payload,
    }


async def _capture_stream_filter_options(page: Page) -> dict[str, Any]:
    button = page.locator(STREAM_FILTER_BUTTON_SELECTOR).first
    if not await button.count():
        return {"selected": None, "options": []}
    selected = str(await button.inner_text()).strip()
    await button.click()
    await page.wait_for_timeout(500)
    options: list[str] = []
    menu = page.locator(STREAM_FILTER_MENU_SELECTOR).first
    if await menu.count():
        options = _dedupe_text_items(
            await menu.locator("*").evaluate_all(
                "els => els.map((el) => (el.innerText || '').trim())"
            )
        )
    await button.click()
    await page.wait_for_timeout(300)
    return {"selected": selected, "options": options}


def _provider_labels_from_streams(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in list(payload.get("streams") or []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        labels.append(name.splitlines()[0].strip())
    return _dedupe_text_items(labels)


def _hash_overlap_summary(
    network_events: list[dict[str, Any]],
    *,
    expected_source: str,
) -> dict[str, Any]:
    expected_hashes: set[str] = set()
    other_hashes: set[str] = set()
    expected_source_folded = expected_source.casefold()
    for event in network_events:
        event_hashes = {
            str(item or "").strip().casefold()
            for item in list(event.get("info_hashes") or [])
            if str(item or "").strip()
        }
        if not event_hashes:
            continue
        provider_labels = [
            str(item or "").strip().casefold()
            for item in list(event.get("provider_labels") or [])
            if str(item or "").strip()
        ]
        if expected_source_folded in provider_labels:
            expected_hashes.update(event_hashes)
        else:
            other_hashes.update(event_hashes)
    shared_hashes = sorted(expected_hashes & other_hashes)
    return {
        "expected_source_hashes": sorted(expected_hashes),
        "other_source_hashes": sorted(other_hashes),
        "shared_hashes": shared_hashes,
        "expected_hash_count": len(expected_hashes),
        "other_hash_count": len(other_hashes),
        "shared_hash_count": len(shared_hashes),
    }


async def _capture_detail_page(
    page: Page,
    *,
    detail_url: str,
    wait_seconds: float,
    expect_source: str,
    expect_present_source: str,
    artifacts_dir: Path,
) -> dict[str, Any]:
    network_events: list[dict[str, Any]] = []
    console_events: list[dict[str, Any]] = []
    page_errors: list[str] = []

    async def on_response(response) -> None:
        url = response.url
        if "/stream/" not in url:
            return
        event: dict[str, Any] = {
            "url": url,
            "status": response.status,
            "timing_ms": None,
        }
        try:
            payload = await response.json()
            event["streams_count"] = len(list(payload.get("streams") or []))
            event["provider_labels"] = _provider_labels_from_streams(payload)
            event["info_hashes"] = [
                str(item.get("infoHash") or "")
                for item in list(payload.get("streams") or [])
                if item.get("infoHash")
            ]
        except Exception:
            pass
        network_events.append(event)

    def on_console(message) -> None:
        console_events.append({"type": message.type, "text": message.text})

    def on_page_error(error) -> None:
        page_errors.append(str(error))

    page.on("response", on_response)
    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    started = time.perf_counter()
    await page.goto(detail_url)
    await page.wait_for_timeout(int(wait_seconds * 1000))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    body_text = await page.locator("body").inner_text()
    screenshot_path = artifacts_dir / "detail-page.png"
    text_path = artifacts_dir / "detail-page.txt"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    text_path.write_text(body_text, encoding="utf-8")
    visible_streams = await _capture_visible_streams(page)
    stream_filter = await _capture_stream_filter_options(page)

    return {
        "detail_url": detail_url,
        "elapsed_ms": elapsed_ms,
        "body_contains_expect_source": expect_source in body_text,
        "body_contains_expect_present_source": expect_present_source in body_text,
        "body_text_excerpt": body_text[:8000],
        "screenshot_path": str(screenshot_path),
        "text_path": str(text_path),
        "network_events": network_events,
        "visible_streams": visible_streams,
        "stream_filter": stream_filter,
        "hash_overlap": _hash_overlap_summary(
            network_events,
            expected_source=expect_source,
        ),
        "console_events": console_events,
        "page_errors": page_errors,
    }


def _artifact_run_dir(root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"stremio-desktop-smoke-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


async def _run_async(args: argparse.Namespace) -> dict[str, Any]:
    artifacts_dir = _artifact_run_dir(Path(args.artifacts_dir))
    stremio_root = Path(args.stremio_root)
    debug_info: dict[str, Any] | None = None
    if args.restart_stremio:
        _taskkill_images()
        await asyncio.sleep(2)
        debug_info = _launch_stremio(stremio_root, debug_port=args.debug_port)
        await asyncio.sleep(6)
    else:
        debug_info = _wait_for_debug_port(args.debug_port, timeout_seconds=5)

    async with async_playwright() as playwright:
        browser, page = await _connect_page(playwright, args.debug_port)
        try:
            await _ensure_addons_page(page)
            addon_state = await _ensure_addon_state(
                page,
                args.manifest_url,
                addon_name=args.addon_name,
                reinstall=args.reinstall_addon,
            )
            detail_result = await _capture_detail_page(
                page,
                detail_url=args.detail_url,
                wait_seconds=args.wait_seconds,
                expect_source=args.expect_source,
                expect_present_source=args.expect_present_source,
                artifacts_dir=artifacts_dir,
            )
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    report = {
        "debug_info": debug_info,
        "manifest_url": args.manifest_url,
        "detail_url": args.detail_url,
        "addon_name": args.addon_name,
        "expect_source": args.expect_source,
        "expect_present_source": args.expect_present_source,
        "artifacts_dir": str(artifacts_dir),
        "addon_state": addon_state,
        "detail_result": detail_result,
    }
    (artifacts_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _summarize_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    addon_state = report["addon_state"]
    detail_result = report["detail_result"]
    if not addon_state.get("installed_after"):
        failures.append(f"{report['addon_name']} addon is not installed after the automation flow.")
    if not detail_result.get("body_contains_expect_present_source"):
        failures.append(
            f"Expected visible baseline source {report['expect_present_source']!r} was not found on the detail page."
        )
    if not detail_result.get("body_contains_expect_source"):
        failures.append(
            f"Expected visible source {report['expect_source']!r} was not found on the detail page."
        )
    if not any("/stremio/stream/" in str(event.get("url") or "") for event in detail_result.get("network_events") or []):
        failures.append("No Stremio addon stream response was captured during the detail-page load.")
    return failures


def main() -> int:
    args = _parse_args()
    report = asyncio.run(_run_async(args))
    failures = _summarize_failures(report)
    output = {"report": report, "failures": failures}
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Artifacts: {report['artifacts_dir']}")
        print(
            f"Addon installed after flow: {report['addon_state']['installed_after']} | "
            f"detail elapsed: {report['detail_result']['elapsed_ms']} ms"
        )
        print(
            f"Visible {report['expect_source']!r}: {report['detail_result']['body_contains_expect_source']} | "
            f"visible {report['expect_present_source']!r}: {report['detail_result']['body_contains_expect_present_source']}"
        )
        print(f"Captured addon/network events: {len(report['detail_result']['network_events'])}")
        if failures:
            print("Failures:")
            for failure in failures:
                print(f"- {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

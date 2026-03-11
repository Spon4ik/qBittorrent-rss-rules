#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlparse
from urllib.request import urlopen
from xml.sax.saxutils import escape


@dataclass(slots=True)
class CheckResult:
    check_id: str
    phase: str
    title: str
    status: str
    detail: str
    duration_ms: int
    failure_artifact: str | None = None


@dataclass(slots=True)
class MockQbState:
    feeds_payload: dict[str, Any]
    rules: dict[str, dict[str, Any]]


@dataclass(slots=True)
class MockJackettState:
    request_count: int = 0


FEED_ALPHA = "https://example.test/rss/alpha.xml"
FEED_BETA = "https://example.test/rss/beta.xml"
FEED_GAMMA = "https://example.test/rss/gamma.xml"
DEFAULT_FEEDS = [FEED_ALPHA, FEED_BETA]


PRIMARY_ITEMS = [
    {
        "id": "primary-1",
        "title": "Young Sherlock S01E01 2160p HDR10 WEB-DL (2026)",
        "link": "https://torrent.test/primary-1",
        "guid": "urn:primary-1",
        "comments": "https://torrent.test/details/primary-1",
        "pub_date": "Tue, 09 Jan 2026 10:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "tt8599532",
        "size": 5 * 1024 * 1024 * 1024,
        "year": "",
        "seeders": 120,
        "peers": 180,
        "leechers": 60,
        "grabs": 410,
        "categories": ["5000", "5040"],
    },
    {
        "id": "primary-2",
        "title": "Юный Шерлок S01E02 2160p HDR WEB-DL (2026)",
        "link": "https://torrent.test/primary-2",
        "guid": "urn:primary-2",
        "comments": "https://torrent.test/details/primary-2",
        "pub_date": "Mon, 08 Jan 2026 11:00:00 GMT",
        "indexer": "beta",
        "imdb_id": "tt8599532",
        "size": 4 * 1024 * 1024 * 1024,
        "year": "2026",
        "seeders": 90,
        "peers": 110,
        "leechers": 20,
        "grabs": 230,
        "categories": ["5000"],
    },
]

FALLBACK_ITEMS = [
    {
        "id": "fallback-dup-primary-1",
        "title": "Young Sherlock S01E01 2160p HDR10 WEB-DL (2026)",
        "link": "https://torrent.test/primary-1",
        "guid": "urn:primary-1",
        "comments": "https://torrent.test/details/primary-1",
        "pub_date": "Tue, 09 Jan 2026 10:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "tt8599532",
        "size": 5 * 1024 * 1024 * 1024,
        "year": "2026",
        "seeders": 120,
        "peers": 180,
        "leechers": 60,
        "grabs": 410,
        "categories": ["5000", "5040"],
    },
    {
        "id": "fallback-1080",
        "title": "Young Sherlock S01E03 1080p HD WEB-DL (2025)",
        "link": "https://torrent.test/fallback-1080",
        "guid": "urn:fallback-1080",
        "comments": "https://torrent.test/details/fallback-1080",
        "pub_date": "Sun, 07 Jan 2026 12:00:00 GMT",
        "indexer": "gamma",
        "imdb_id": "",
        "size": 1500 * 1024 * 1024,
        "year": "2025",
        "seeders": 50,
        "peers": 65,
        "leechers": 15,
        "grabs": 120,
        "categories": ["5000"],
    },
    {
        "id": "fallback-hdrezka",
        "title": "Young Sherlock HDRezka Special 2160p WEB-DL (2026)",
        "link": "https://torrent.test/fallback-hdrezka",
        "guid": "urn:fallback-hdrezka",
        "comments": "https://torrent.test/details/fallback-hdrezka",
        "pub_date": "Sat, 06 Jan 2026 13:00:00 GMT",
        "indexer": "HDRezka",
        "imdb_id": "",
        "size": 3200 * 1024 * 1024,
        "year": "2026",
        "seeders": 40,
        "peers": 48,
        "leechers": 8,
        "grabs": 85,
        "categories": ["5000", "5050"],
    },
    {
        "id": "fallback-ts",
        "title": "Young Sherlock TS 2160p HDR10 CAM (2026)",
        "link": "https://torrent.test/fallback-ts",
        "guid": "urn:fallback-ts",
        "comments": "https://torrent.test/details/fallback-ts",
        "pub_date": "Fri, 05 Jan 2026 14:00:00 GMT",
        "indexer": "delta",
        "imdb_id": "",
        "size": 2700 * 1024 * 1024,
        "year": "2026",
        "seeders": 30,
        "peers": 39,
        "leechers": 9,
        "grabs": 55,
        "categories": ["5000", "5070"],
    },
    {
        "id": "fallback-test-cut",
        "title": "Young Sherlock Test Cut 2160p HDR10 (2026)",
        "link": "https://torrent.test/fallback-test-cut",
        "guid": "urn:fallback-test-cut",
        "comments": "https://torrent.test/details/fallback-test-cut",
        "pub_date": "Thu, 04 Jan 2026 15:00:00 GMT",
        "indexer": "epsilon",
        "imdb_id": "",
        "size": 2600 * 1024 * 1024,
        "year": "2026",
        "seeders": 28,
        "peers": 35,
        "leechers": 7,
        "grabs": 43,
        "categories": ["5000", "5080"],
    },
    {
        "id": "fallback-hdr",
        "title": "Young Sherlock Documentary 2160p HDR WEB-DL (2026)",
        "link": "https://torrent.test/fallback-hdr",
        "guid": "urn:fallback-hdr",
        "comments": "https://torrent.test/details/fallback-hdr",
        "pub_date": "Wed, 03 Jan 2026 16:00:00 GMT",
        "indexer": "zeta",
        "imdb_id": "",
        "size": 2400 * 1024 * 1024,
        "year": "2026",
        "seeders": 22,
        "peers": 27,
        "leechers": 5,
        "grabs": 31,
        "categories": ["5000"],
    },
    {
        "id": "fallback-unrelated",
        "title": "Ghosts S01E01 2160p HDR10 (2026)",
        "link": "https://torrent.test/fallback-unrelated",
        "guid": "urn:fallback-unrelated",
        "comments": "https://torrent.test/details/fallback-unrelated",
        "pub_date": "Tue, 02 Jan 2026 17:00:00 GMT",
        "indexer": "theta",
        "imdb_id": "",
        "size": 2100 * 1024 * 1024,
        "year": "2026",
        "seeders": 14,
        "peers": 19,
        "leechers": 5,
        "grabs": 17,
        "categories": ["5000"],
    },
]

NON_LATIN_ITEMS = [
    {
        "id": "non-latin-1",
        "title": "Пелевин - Чапаев и Пустота (audiobook)",
        "link": "https://torrent.test/non-latin-1",
        "guid": "urn:non-latin-1",
        "comments": "https://torrent.test/details/non-latin-1",
        "pub_date": "Mon, 01 Jan 2026 18:00:00 GMT",
        "indexer": "books",
        "imdb_id": "",
        "size": 550 * 1024 * 1024,
        "year": "2026",
        "seeders": 11,
        "peers": 16,
        "leechers": 5,
        "grabs": 22,
        "categories": ["3030"],
    },
    {
        "id": "non-latin-unrelated",
        "title": "Толстой - Война и мир (audiobook)",
        "link": "https://torrent.test/non-latin-unrelated",
        "guid": "urn:non-latin-unrelated",
        "comments": "https://torrent.test/details/non-latin-unrelated",
        "pub_date": "Sun, 31 Dec 2025 19:00:00 GMT",
        "indexer": "books",
        "imdb_id": "",
        "size": 700 * 1024 * 1024,
        "year": "2025",
        "seeders": 9,
        "peers": 14,
        "leechers": 5,
        "grabs": 15,
        "categories": ["3030"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic browser-closeout QA for phases 4/5/6 using "
            "isolated mock qBittorrent + Jackett services."
        )
    )
    parser.add_argument("--output-dir", default="logs/qa", help="Directory for timestamped QA artifacts.")
    parser.add_argument("--timeout-ms", type=int, default=25000, help="Playwright step timeout in milliseconds.")
    parser.add_argument("--headful", action="store_true", help="Run Chromium with a visible window.")
    parser.add_argument(
        "--app-host",
        default="127.0.0.1",
        help="App host bound for the isolated uvicorn process.",
    )
    return parser.parse_args()


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(probe.getsockname()[1])


def wait_for_http(url: str, timeout_seconds: float) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        try:
            with urlopen(url, timeout=1.5) as response:  # noqa: S310
                if int(getattr(response, "status", 0)) < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def build_qb_handler(state: MockQbState) -> type[BaseHTTPRequestHandler]:
    class QbHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _write_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_text(self, payload: str, status: int = 200) -> None:
            body = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/v2/rss/items":
                self._write_json(state.feeds_payload)
                return
            if parsed.path == "/api/v2/rss/rules":
                self._write_json(state.rules)
                return
            self._write_json({"error": f"Unhandled GET path: {parsed.path}"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
            form = parse_qs(raw_body, keep_blank_values=True)
            if parsed.path == "/api/v2/auth/login":
                self._write_text("Ok.")
                return
            if parsed.path == "/api/v2/torrents/createCategory":
                self._write_text("", status=200)
                return
            if parsed.path == "/api/v2/rss/setRule":
                rule_name = (form.get("ruleName") or [""])[0]
                rule_def_raw = (form.get("ruleDef") or ["{}"])[0]
                try:
                    rule_def = json.loads(rule_def_raw)
                except ValueError:
                    rule_def = {}
                if rule_name:
                    state.rules[rule_name] = rule_def
                self._write_text("", status=200)
                return
            if parsed.path == "/api/v2/rss/removeRule":
                rule_name = (form.get("ruleName") or [""])[0]
                if rule_name and rule_name in state.rules:
                    del state.rules[rule_name]
                self._write_text("", status=200)
                return
            self._write_json({"error": f"Unhandled POST path: {parsed.path}"}, status=404)

    return QbHandler


def _torznab_indexers_xml() -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<indexers>"
        "<indexer id=\"alpha\">"
        "<caps>"
        "<tv-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "<movie-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "</caps>"
        "</indexer>"
        "<indexer id=\"beta\">"
        "<caps>"
        "<tv-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "<movie-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "</caps>"
        "</indexer>"
        "</indexers>"
    )


def _torznab_caps_xml() -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<caps>"
        "<searching>"
        "<search available=\"yes\" supportedParams=\"q\" />"
        "<tv-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "<movie-search available=\"yes\" supportedParams=\"q,imdbid\" />"
        "<book-search available=\"yes\" supportedParams=\"q\" />"
        "<music-search available=\"yes\" supportedParams=\"q\" />"
        "</searching>"
        "</caps>"
    )


def _torznab_item_xml(item: dict[str, Any]) -> str:
    category_lines = "".join(
        f"<category>{escape(str(category_id))}</category>" for category_id in item.get("categories", [])
    )
    attrs = [
        ("size", item.get("size")),
        ("imdbid", item.get("imdb_id")),
        ("seeders", item.get("seeders")),
        ("peers", item.get("peers")),
        ("leechers", item.get("leechers")),
        ("grabs", item.get("grabs")),
        ("year", item.get("year")),
        ("category", ",".join(str(part) for part in item.get("categories", []))),
    ]
    attr_lines = ""
    for name, value in attrs:
        text = str(value or "").strip()
        if not text:
            continue
        attr_lines += f"<attr name=\"{escape(name)}\" value=\"{escape(text)}\" />"

    title = escape(str(item["title"]))
    link = escape(str(item["link"]))
    guid = escape(str(item["guid"]))
    comments = escape(str(item["comments"]))
    pub_date = escape(str(item["pub_date"]))
    indexer = escape(str(item.get("indexer") or ""))
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<guid isPermaLink=\"false\">{guid}</guid>"
        f"<comments>{comments}</comments>"
        f"<pubDate>{pub_date}</pubDate>"
        f"<jackettindexer>{indexer}</jackettindexer>"
        f"{category_lines}"
        f"{attr_lines}"
        "</item>"
    )


def _torznab_results_xml(items: list[dict[str, Any]]) -> str:
    item_lines = "".join(_torznab_item_xml(item) for item in items)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\">"
        "<channel>"
        f"{item_lines}"
        "</channel>"
        "</rss>"
    )


def _jackett_items_for_query(query: str) -> list[dict[str, Any]]:
    normalized = unquote_plus(query).strip().casefold()
    if "young sherlock" in normalized:
        return FALLBACK_ITEMS
    if "пелевин" in normalized:
        return NON_LATIN_ITEMS
    return []


def build_jackett_handler(state: MockJackettState) -> type[BaseHTTPRequestHandler]:
    class JackettHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _write_xml(self, payload: str, status: int = 200) -> None:
            body = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_error(self, message: str, status: int = 400) -> None:
            payload = (
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                f"<error code=\"203\" description=\"{escape(message)}\" />"
            )
            self._write_xml(payload, status=status)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not parsed.path.endswith("/results/torznab/api"):
                self._write_error(f"Unhandled Jackett path: {parsed.path}", status=404)
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            mode = (query.get("t") or ["search"])[0]
            state.request_count += 1
            if mode == "caps":
                self._write_xml(_torznab_caps_xml())
                return
            if mode == "indexers":
                self._write_xml(_torznab_indexers_xml())
                return

            imdb_id = (query.get("imdbid") or [""])[0].strip()
            text_query = (query.get("q") or [""])[0].strip()
            if imdb_id:
                self._write_xml(_torznab_results_xml(PRIMARY_ITEMS))
                return
            if text_query:
                self._write_xml(_torznab_results_xml(_jackett_items_for_query(text_query)))
                return
            self._write_xml(_torznab_results_xml([]))

    return JackettHandler


def start_threaded_server(handler: type[BaseHTTPRequestHandler], host: str, port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_threaded_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def read_debug_log_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def force_default_feed_urls(db_path: Path, feed_urls: list[str]) -> None:
    payload = json.dumps(feed_urls)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE app_settings SET default_feed_urls = ? WHERE id = 'default'",
            (payload,),
        )
        connection.commit()


def markdown_table(checks: list[CheckResult]) -> str:
    lines = [
        "| Check ID | Phase | Status | Duration (ms) | Detail |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in checks:
        detail = item.detail.replace("|", "\\|")
        lines.append(
            f"| {item.check_id} | {item.phase} | {item.status} | {item.duration_ms} | {detail} |"
        )
    return "\n".join(lines)


def relative_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sorted_values(values: list[str]) -> list[str]:
    return sorted(value.strip() for value in values if value and value.strip())


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent.parent
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = project_dir / output_root

    run_stamp = f"phase-closeout-{utc_stamp()}"
    run_dir = output_root / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = run_dir / "closeout-report.json"
    report_md_path = run_dir / "closeout-report.md"
    app_log_path = run_dir / "uvicorn.log"

    db_path = run_dir / "closeout.db"
    app_port = find_free_port()
    qb_port = find_free_port()
    jackett_port = find_free_port()
    app_base_url = f"http://{args.app_host}:{app_port}"
    qb_base_url = f"http://127.0.0.1:{qb_port}"
    jackett_base_url = f"http://127.0.0.1:{jackett_port}"

    qb_state = MockQbState(
        feeds_payload={
            "Feeds": {
                "Alpha": {"name": "Alpha", "url": FEED_ALPHA},
                "Beta": {"name": "Beta", "url": FEED_BETA},
                "Gamma": {"name": "Gamma", "url": FEED_GAMMA},
            }
        },
        rules={},
    )
    jackett_state = MockJackettState(request_count=0)

    qb_server, qb_thread = start_threaded_server(build_qb_handler(qb_state), "127.0.0.1", qb_port)
    jackett_server, jackett_thread = start_threaded_server(
        build_jackett_handler(jackett_state),
        "127.0.0.1",
        jackett_port,
    )

    env = os.environ.copy()
    env["QB_RULES_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["QB_RULES_QB_BASE_URL"] = qb_base_url
    env["QB_RULES_QB_USERNAME"] = "admin"
    env["QB_RULES_QB_PASSWORD"] = "adminadmin"
    env["QB_RULES_JACKETT_API_URL"] = jackett_base_url
    env["QB_RULES_JACKETT_QB_URL"] = jackett_base_url
    env["QB_RULES_JACKETT_API_KEY"] = "qa-key"
    env["QB_RULES_REQUEST_TIMEOUT"] = "5"

    server_process: subprocess.Popen[str] | None = None
    checks: list[CheckResult] = []

    def run_check(
        check_id: str,
        phase: str,
        title: str,
        check_fn: Any,
        *,
        page: Any = None,
    ) -> None:
        start = time.monotonic()
        status = "pass"
        detail = ""
        artifact: str | None = None
        try:
            check_fn()
            detail = "OK"
        except Exception as exc:  # noqa: BLE001
            status = "fail"
            detail = f"{exc.__class__.__name__}: {exc}"
            if page is not None:
                failure_path = run_dir / f"{check_id.lower()}-failure.png"
                try:
                    page.screenshot(path=str(failure_path), full_page=True)
                    artifact = relative_path(failure_path, project_dir)
                except Exception:  # noqa: BLE001
                    artifact = None
        duration_ms = int((time.monotonic() - start) * 1000)
        checks.append(
            CheckResult(
                check_id=check_id,
                phase=phase,
                title=title,
                status=status,
                detail=detail,
                duration_ms=duration_ms,
                failure_artifact=artifact,
            )
        )

    try:
        with app_log_path.open("w", encoding="utf-8") as app_log:
            server_process = subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    args.app_host,
                    "--port",
                    str(app_port),
                ],
                cwd=project_dir,
                env=env,
                stdout=app_log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if not wait_for_http(f"{app_base_url}/health", timeout_seconds=30):
            raise RuntimeError(f"Timed out waiting for isolated app server ({app_base_url}).")

        # Ensure app_settings row exists before forcing defaults.
        with urlopen(f"{app_base_url}/rules/new", timeout=10):  # noqa: S310
            pass
        force_default_feed_urls(db_path, DEFAULT_FEEDS)

        debug_log_path = project_dir / "logs" / "search-debug.log"
        debug_log_before = read_debug_log_line_count(debug_log_path)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed for this interpreter. "
                f"Install with `{sys.executable} -m pip install playwright` and "
                f"`{sys.executable} -m playwright install chromium`."
            ) from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headful)
            context = browser.new_context(viewport={"width": 1720, "height": 1040})
            page = context.new_page()
            app_requests: list[str] = []

            def on_request(request: Any) -> None:
                if request.url.startswith(app_base_url):
                    app_requests.append(request.url)

            page.on("request", on_request)

            def request_count() -> int:
                return len(app_requests)

            def checked_feed_values() -> list[str]:
                return page.eval_on_selector_all(
                    '#feed-options input[name="feed_urls"]:checked',
                    "els => els.map((el) => el.value)",
                )

            def all_feed_values() -> list[str]:
                return page.eval_on_selector_all(
                    '#feed-options input[name="feed_urls"]',
                    "els => els.map((el) => el.value)",
                )

            def search_filtered_count(section: str) -> int:
                raw = page.text_content(f'[data-search-filtered-count="{section}"]') or "0"
                return int(raw.strip() or "0")

            def search_visible_titles(section: str) -> list[str]:
                return page.evaluate(
                    """
                    (targetSection) => Array
                      .from(document.querySelectorAll(`[data-search-row="${targetSection}"]`))
                      .filter((row) => !row.hidden)
                      .map((row) => row.querySelector("td")?.textContent?.trim() || "")
                      .filter(Boolean)
                    """,
                    section,
                )

            run_check(
                "P4-01",
                "Phase 4",
                "Feed checkboxes render with remembered default prefill",
                lambda: (
                    page.goto(f"{app_base_url}/rules/new", wait_until="networkidle", timeout=args.timeout_ms),
                    page.wait_for_selector('#feed-options input[name="feed_urls"]', timeout=args.timeout_ms),
                    _expect(len(all_feed_values()) >= 3, "Expected at least 3 feed checkboxes from mock qB."),
                    _expect(
                        set(DEFAULT_FEEDS).issubset(set(checked_feed_values())),
                        (
                            "Expected remembered default feeds to be checked. "
                            f"Checked={_sorted_values(checked_feed_values())}"
                        ),
                    ),
                ),
                page=page,
            )

            run_check(
                "P4-02",
                "Phase 4",
                "Select all / Clear all controls toggle feed checkboxes deterministically",
                lambda: (
                    page.click("#feed-clear-all"),
                    _expect(len(checked_feed_values()) == 0, "Clear all should uncheck every feed."),
                    page.click("#feed-select-all"),
                    _expect(
                        len(checked_feed_values()) == len(all_feed_values()),
                        "Select all should check every feed.",
                    ),
                ),
                page=page,
            )

            dialog_messages: list[str] = []

            def on_dialog(dialog: Any) -> None:
                dialog_messages.append(dialog.message)
                dialog.accept()

            page.on("dialog", on_dialog)

            def check_phase5_media_behavior() -> None:
                _expect(page.is_visible('[data-imdb-field="true"]'), "IMDb field should be visible for series.")
                series_providers = page.eval_on_selector_all(
                    "#metadata-lookup-provider option",
                    "els => els.map((el) => el.value)",
                )
                _expect(series_providers == ["omdb"], f"Series providers mismatch: {series_providers}")

                page.select_option('select[name="media_type"]', "music")
                page.wait_for_timeout(120)
                _expect(dialog_messages, "Media switch should prompt warning-and-clear confirmation.")
                _expect(
                    "Switching media type will clear filters" in dialog_messages[-1],
                    "Media switch dialog text mismatch.",
                )
                _expect(
                    not page.is_visible('[data-imdb-field="true"]'),
                    "IMDb field should be hidden for music.",
                )
                music_providers = page.eval_on_selector_all(
                    "#metadata-lookup-provider option",
                    "els => els.map((el) => el.value)",
                )
                _expect(music_providers == ["musicbrainz"], f"Music providers mismatch: {music_providers}")

                page.select_option('select[name="media_type"]', "audiobook")
                page.wait_for_timeout(120)
                audiobook_providers = page.eval_on_selector_all(
                    "#metadata-lookup-provider option",
                    "els => els.map((el) => el.value)",
                )
                _expect(
                    set(audiobook_providers) == {"openlibrary", "google_books"},
                    f"Audiobook providers mismatch: {audiobook_providers}",
                )
                _expect(
                    not page.is_visible('[data-imdb-field="true"]'),
                    "IMDb field should stay hidden for audiobook.",
                )

                page.select_option('select[name="media_type"]', "other")
                page.wait_for_timeout(120)
                other_providers = page.eval_on_selector_all(
                    "#metadata-lookup-provider option",
                    "els => els.map((el) => el.value)",
                )
                _expect(
                    set(other_providers) == {"omdb", "musicbrainz", "openlibrary", "google_books"},
                    f"Other providers mismatch: {other_providers}",
                )
                _expect(page.is_visible('[data-imdb-field="true"]'), "IMDb field should be visible for other.")

                checked_hidden = page.evaluate(
                    """
                    () => Array.from(
                      document.querySelectorAll(
                        'input[name="quality_include_tokens"]:checked, input[name="quality_exclude_tokens"]:checked'
                      )
                    ).filter((input) => {
                      const option = input.closest('[data-quality-option="true"]') || input.closest('[data-quality-option]');
                      const group = input.closest('[data-quality-group="true"]') || input.closest('[data-quality-group]');
                      return Boolean((option && option.hidden) || (group && group.hidden));
                    }).length
                    """
                )
                _expect(checked_hidden == 0, "Switch should clear incompatible checked quality tokens.")

            run_check(
                "P5-01",
                "Phase 5",
                "Media-type switching enforces provider visibility and warning/clear behavior",
                check_phase5_media_behavior,
                page=page,
            )

            def check_phase5_rule_pattern_preview_parity() -> None:
                page.goto(f"{app_base_url}/rules/new", wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector("#pattern-preview", timeout=args.timeout_ms)
                page.fill('input[name="normalized_title"]', "Pattern Preview Rule")
                page.fill('textarea[name="additional_includes"]', "aaa, bbb|ccc, ddd")
                page.fill('textarea[name="must_not_contain"]', "cam|ts")
                page.wait_for_timeout(180)
                preview = page.input_value("#pattern-preview")
                _expect(
                    "(?=.*aaa)" in preview,
                    f"Expected required extra include term in rule preview; preview={preview!r}",
                )
                _expect(
                    "(?=.*(?:bbb|ccc))" in preview,
                    f"Expected OR group from pipe-delimited extra include term; preview={preview!r}",
                )
                _expect(
                    "(?=.*ddd)" in preview,
                    f"Expected final required extra include term in rule preview; preview={preview!r}",
                )
                _expect(
                    "(?!.*(?:cam|ts))" in preview,
                    f"Expected mustNotContain pipe alternatives in rule preview; preview={preview!r}",
                )

            run_check(
                "P5-02",
                "Phase 5",
                "Rule generated-pattern preview reflects mustNotContain and pipe alternatives",
                check_phase5_rule_pattern_preview_parity,
                page=page,
            )

            search_url = (
                f"{app_base_url}/search?query=Young+Sherlock&media_type=series&indexer=all"
                "&imdb_id=tt8599532&include_release_year=on&release_year=2026"
            )

            def check_phase6_controls() -> None:
                page.goto(search_url, wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector("[data-search-controls]", timeout=args.timeout_ms)
                controls = page.locator("[data-search-controls]")
                _expect(controls.count() == 2, "Expected synced result-view panels above both sections.")

                first_view = controls.nth(0).locator("[data-search-view-mode]")
                second_view = controls.nth(1).locator("[data-search-view-mode]")
                _expect(first_view.input_value() == "table", "Default view mode should be table.")
                _expect(second_view.input_value() == "table", "Secondary panel should mirror table default.")

                first_view.select_option("cards")
                page.wait_for_timeout(100)
                _expect(second_view.input_value() == "cards", "View mode should sync between panels.")

                first_sort_field = controls.nth(0).locator('[data-search-sort-field="1"]')
                second_sort_field = controls.nth(1).locator('[data-search-sort-field="1"]')
                first_sort_field.select_option("size_bytes")
                page.wait_for_timeout(100)
                _expect(second_sort_field.input_value() == "size_bytes", "Sort field should sync between panels.")

                controls.nth(0).locator("[data-search-save-defaults]").click()
                page.wait_for_function(
                    """
                    () => Array.from(document.querySelectorAll('[data-search-default-status]'))
                      .every((node) => (node.textContent || '').includes('Saved.'))
                    """,
                    timeout=args.timeout_ms,
                )
                statuses = page.eval_on_selector_all(
                    "[data-search-default-status]",
                    "els => els.map((el) => (el.textContent || '').trim())",
                )
                _expect(
                    all("Saved." in status for status in statuses),
                    f"Unexpected save-default statuses: {statuses}",
                )

            run_check(
                "P6-01",
                "Phase 6",
                "Dual result-view panels stay synchronized and save defaults",
                check_phase6_controls,
                page=page,
            )

            def check_phase6_local_filters() -> None:
                controls = page.locator("[data-search-controls]")
                controls.nth(0).locator("[data-search-view-mode]").select_option("table")
                page.wait_for_timeout(100)

                baseline_requests = request_count()
                page.fill('input[name="keywords_any"]', "2160p | hdr10")
                page.wait_for_timeout(180)
                grouped_preview = page.input_value("#search-pattern-preview")
                _expect(
                    "(?=.*2160p)" in grouped_preview and "(?=.*hdr10)" in grouped_preview,
                    (
                        "Expected grouped any-of text to contribute include lookaheads in generated preview; "
                        f"preview={grouped_preview!r}"
                    ),
                )
                _expect(
                    search_filtered_count("primary") == 1,
                    f"Expected primary filtered count=1 after grouped any-of; got {search_filtered_count('primary')}",
                )
                _expect(
                    search_filtered_count("fallback") == 2,
                    f"Expected fallback filtered count=2 after grouped any-of; got {search_filtered_count('fallback')}",
                )

                page.fill('textarea[name="must_not_contain"]', "ts")
                page.wait_for_timeout(180)
                _expect(
                    search_filtered_count("fallback") == 1,
                    f"Expected fallback filtered count=1 after excluded short token; got {search_filtered_count('fallback')}",
                )
                visible_fallback_titles = search_visible_titles("fallback")
                _expect(
                    any("Test Cut" in title for title in visible_fallback_titles),
                    f"Expected Test Cut to remain visible; titles={visible_fallback_titles}",
                )
                _expect(
                    all(" TS " not in f" {title} " for title in visible_fallback_titles),
                    f"Expected explicit TS token rows to be filtered; titles={visible_fallback_titles}",
                )
                _expect(
                    request_count() == baseline_requests,
                    (
                        "Local filter edits should be network-free. "
                        f"before={baseline_requests} after={request_count()}"
                    ),
                )

            run_check(
                "P6-02",
                "Phase 6",
                "Grouped keyword filters and short-token exclusion run locally without extra requests",
                check_phase6_local_filters,
                page=page,
            )

            def check_phase6_release_year_toggle() -> None:
                page.goto(search_url, wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector('[data-search-filtered-count="fallback"]', timeout=args.timeout_ms)

                baseline_requests = request_count()
                _expect(
                    search_filtered_count("fallback") == 4,
                    f"Expected fallback filtered count=4 with release-year filter enabled; got {search_filtered_count('fallback')}",
                )
                page.uncheck('input[data-search-include-year]')
                page.wait_for_timeout(200)
                _expect(
                    page.is_disabled('input[data-search-release-year]'),
                    "Release-year field should be disabled when toggle is unchecked.",
                )
                _expect(
                    search_filtered_count("fallback") == 5,
                    (
                        "Expected fallback filtered count to expand to 5 when release-year filter is off; "
                        f"got {search_filtered_count('fallback')}"
                    ),
                )
                _expect(
                    request_count() == baseline_requests,
                    (
                        "Release-year local toggling should be network-free. "
                        f"before={baseline_requests} after={request_count()}"
                    ),
                )

            run_check(
                "P6-03",
                "Phase 6",
                "Release-year toggle updates local filtering without remote requests",
                check_phase6_release_year_toggle,
                page=page,
            )

            def check_phase6_quality_toggle_and_multiselect_filters() -> None:
                page.goto(search_url, wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector('[data-search-filtered-count="fallback"]', timeout=args.timeout_ms)
                baseline_requests = request_count()
                baseline_fallback_count = search_filtered_count("fallback")

                token_slider = page.locator(
                    '[data-search-quality-option="true"][data-quality-token="cam"] [data-quality-token-slider-control]'
                )
                _expect(token_slider.count() == 1, "Expected cam quality token slider on /search.")
                pattern_preview = page.locator("#search-pattern-preview")
                _expect(pattern_preview.count() == 1, "Expected generated pattern preview textarea on /search.")

                # Regression guard: include slider must override conflicting manual excluded text terms.
                page.fill('textarea[name="additional_includes"]', "young sherlock")
                page.fill('textarea[name="must_not_contain"]', "cam")
                page.wait_for_timeout(220)
                preview_with_cam_excluded = pattern_preview.input_value()
                _expect(
                    "(?=.*young[\\s._-]*sherlock)" in preview_with_cam_excluded,
                    (
                        "Expected extra include keywords to appear in generated pattern preview; "
                        f"preview={preview_with_cam_excluded!r}"
                    ),
                )
                _expect(
                    "(?!.*cam)" in preview_with_cam_excluded,
                    (
                        "Expected mustNotContain keyword cam to appear in generated pattern preview; "
                        f"preview={preview_with_cam_excluded!r}"
                    ),
                )
                _expect(
                    search_filtered_count("fallback") == max(baseline_fallback_count - 1, 0),
                    (
                        "Expected manual excluded keyword cam to reduce fallback count by one "
                        f"(baseline={baseline_fallback_count}, now={search_filtered_count('fallback')})."
                    ),
                )
                token_slider.first.focus()
                token_slider.first.press("ArrowRight")
                page.wait_for_timeout(220)
                preview_with_cam_include = pattern_preview.input_value()
                _expect(
                    preview_with_cam_include != preview_with_cam_excluded,
                    "Expected generated pattern preview to change when cam slider toggles to Include.",
                )
                _expect(
                    "(?!.*cam)" not in preview_with_cam_include,
                    (
                        "Expected include slider to remove conflicting cam exclusion from generated pattern preview; "
                        f"preview={preview_with_cam_include!r}"
                    ),
                )
                _expect(
                    search_filtered_count("fallback") == 1,
                    (
                        "Expected cam Include slider to override conflicting excluded keyword text and keep "
                        "the cam-matching result visible; "
                        f"got {search_filtered_count('fallback')}."
                    ),
                )

                page.fill('textarea[name="must_not_contain"]', "")
                token_slider.first.press("Home")
                page.wait_for_timeout(220)
                preview_after_reset = pattern_preview.input_value()
                _expect(
                    "(?!.*cam)" not in preview_after_reset,
                    (
                        "Expected clearing mustNotContain + slider Off to remove cam exclusion from preview; "
                        f"preview={preview_after_reset!r}"
                    ),
                )
                _expect(
                    search_filtered_count("fallback") == baseline_fallback_count,
                    (
                        "Expected clearing excluded keywords and resetting slider to Off to restore baseline "
                        f"fallback count {baseline_fallback_count}; got {search_filtered_count('fallback')}."
                    ),
                )

                token_slider.first.focus()
                token_slider.first.press("End")
                page.wait_for_timeout(220)
                preview_with_cam_out = pattern_preview.input_value()
                _expect(
                    preview_with_cam_out != preview_after_reset,
                    "Expected generated pattern preview to change when cam slider toggles to Out.",
                )
                _expect(
                    "(?!.*" in preview_with_cam_out and "cam" in preview_with_cam_out,
                    (
                        "Expected cam Out slider to add a cam exclusion lookahead to generated preview; "
                        f"preview={preview_with_cam_out!r}"
                    ),
                )
                _expect(
                    search_filtered_count("fallback") == max(baseline_fallback_count - 1, 0),
                    (
                        "Expected quality Out toggle to reduce fallback count by one "
                        f"(baseline={baseline_fallback_count}, now={search_filtered_count('fallback')})."
                    ),
                )
                token_slider.first.press("Home")
                page.fill('textarea[name="additional_includes"]', "")
                page.wait_for_timeout(220)
                _expect(
                    search_filtered_count("fallback") == baseline_fallback_count,
                    (
                        "Expected quality slider reset to restore fallback count "
                        f"to {baseline_fallback_count}; got {search_filtered_count('fallback')}."
                    ),
                )

                page.click('[data-search-multiselect-summary="indexers"]')
                delta_indexer_option = page.locator(
                    '[data-search-multiselect-options="indexers"] label:has-text("delta") input[type="checkbox"]'
                )
                _expect(delta_indexer_option.count() == 1, "Expected delta indexer option in indexer multiselect.")
                delta_indexer_option.check()
                page.wait_for_timeout(220)
                _expect(
                    search_filtered_count("fallback") == 1,
                    f"Expected exactly one fallback row for delta indexer; got {search_filtered_count('fallback')}.",
                )
                delta_titles = search_visible_titles("fallback")
                _expect(
                    len(delta_titles) == 1 and " TS " in f" {delta_titles[0]} ",
                    f"Expected delta indexer filter to keep TS row only; titles={delta_titles}",
                )
                delta_indexer_option.uncheck()
                page.wait_for_timeout(180)

                page.click('[data-search-multiselect-summary="categories"]')
                documentary_category_option = page.locator(
                    '[data-search-multiselect-options="categories"] label:has-text("TV/Documentary") input[type="checkbox"]'
                )
                _expect(
                    documentary_category_option.count() == 1,
                    "Expected TV/Documentary category option in category multiselect.",
                )
                documentary_category_option.check()
                page.wait_for_timeout(220)
                _expect(
                    search_filtered_count("fallback") == 1,
                    (
                        "Expected category dropdown filter TV/Documentary to keep one fallback row; "
                        f"got {search_filtered_count('fallback')}."
                    ),
                )
                documentary_titles = search_visible_titles("fallback")
                _expect(
                    len(documentary_titles) == 1 and "Test Cut" in documentary_titles[0],
                    f"Expected TV/Documentary filter to keep Test Cut only; titles={documentary_titles}",
                )
                _expect(
                    request_count() == baseline_requests,
                    (
                        "Quality-token toggle and multiselect local filters should be network-free. "
                        f"before={baseline_requests} after={request_count()}"
                    ),
                )

            run_check(
                "P6-04",
                "Phase 6",
                "Quality-tag toggles and indexer/category multiselect filters run locally without extra requests",
                check_phase6_quality_toggle_and_multiselect_filters,
                page=page,
            )

            def check_phase6_filter_impact_and_handoff() -> None:
                page.goto(search_url, wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector('[data-search-summary="primary"]', timeout=args.timeout_ms)
                page.locator("[data-search-controls]").nth(0).locator("[data-search-view-mode]").select_option("table")
                page.wait_for_timeout(120)
                page.fill('input[name="keywords_any"]', "2160p | hdr10")
                page.wait_for_timeout(180)
                primary_impact_count = page.eval_on_selector_all(
                    '[data-filter-impact-list="primary"] li',
                    "els => els.length",
                )
                fallback_impact_count = page.eval_on_selector_all(
                    '[data-filter-impact-list="fallback"] li',
                    "els => els.length",
                )
                _expect(primary_impact_count > 0, "Primary filter-impact list should render active entries.")
                _expect(fallback_impact_count > 0, "Fallback filter-impact list should render active entries.")

                details = page.locator('[data-search-summary="primary"] .search-impact-toggle')
                details.locator("summary").click()
                page.wait_for_timeout(120)
                _expect(not details.evaluate("node => node.open"), "Filter-impact section should collapse.")
                details.locator("summary").click()
                page.wait_for_timeout(120)
                _expect(details.evaluate("node => node.open"), "Filter-impact section should expand.")

                page.fill('input[name="keywords_any"]', "")
                page.fill('textarea[name="must_not_contain"]', "")
                page.wait_for_timeout(120)
                use_link = page.locator(
                    '[data-search-row="primary"]:not([hidden]) a.button-link:has-text("Use In New Rule")'
                ).first
                _expect(use_link.count() == 1, "Expected a visible Use In New Rule link in primary results.")
                href = use_link.get_attribute("href") or ""
                _expect(href.startswith("/rules/new?"), f"Unexpected handoff href: {href}")

                use_link.click()
                page.wait_for_url("**/rules/new?**", timeout=args.timeout_ms)
                _expect(
                    page.input_value('input[name="rule_name"]').strip() == "Young Sherlock",
                    "Handoff should prefill rule name.",
                )
                _expect(
                    page.input_value('input[name="content_name"]').strip() == "Young Sherlock",
                    "Handoff should prefill content name.",
                )
                _expect(
                    page.input_value('input[name="imdb_id"]').strip() == "tt8599532",
                    "Handoff should prefill IMDb ID.",
                )
                _expect(
                    page.input_value('input[name="release_year"]').strip() == "2026",
                    "Handoff should prefill release year.",
                )
                feed_checked = page.eval_on_selector_all(
                    '#feed-options input[name="feed_urls"]:checked',
                    "els => els.length",
                )
                if feed_checked == 0:
                    page.check('#feed-options input[name="feed_urls"]')
                if not page.is_checked('input[name="include_release_year"]'):
                    page.check('input[name="include_release_year"]')

                unique_rule_name = f"QA Closeout Rule {int(time.time())}"
                page.fill('input[name="rule_name"]', unique_rule_name)
                page.click('button:has-text("Create Rule")')
                page.wait_for_url("**/rules/**", timeout=args.timeout_ms)
                current_url = page.url
                _expect("/rules/" in current_url, f"Expected redirect to created rule page, got {current_url}")
                page.click('a.button-link:has-text("Run Search")')
                page.wait_for_url("**/search?rule_id=**", timeout=args.timeout_ms)
                page.wait_for_selector('[data-search-summary="primary"]', timeout=args.timeout_ms)
                _expect(
                    page.input_value('input[name="keywords_any"]').strip() == "",
                    "Rule-derived /search run should keep Additional any-of keyword groups blank by default.",
                )
                page_text = page.content()
                _expect("Derived from rule:" in page_text, "Rule-derived search page should show derivation summary.")
                _expect(
                    "IMDb-first results" in page_text,
                    "Rule-derived movie/series search should use IMDb-first labeling.",
                )

            run_check(
                "P6-05",
                "Phase 6",
                "Filter-impact UX, search-to-rule handoff, and rule-derived search flow",
                check_phase6_filter_impact_and_handoff,
                page=page,
            )

            def check_phase6_non_latin() -> None:
                page.goto(
                    f"{app_base_url}/search?query=%D0%9F%D0%B5%D0%BB%D0%B5%D0%B2%D0%B8%D0%BD&media_type=audiobook&indexer=all",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector('[data-search-summary="primary"]', timeout=args.timeout_ms)
                _expect(
                    search_filtered_count("primary") == 1,
                    (
                        "Expected non-Latin query local matching to keep one relevant result; "
                        f"got {search_filtered_count('primary')}"
                    ),
                )

            run_check(
                "P6-06",
                "Phase 6",
                "Non-Latin query filtering keeps relevant localized matches",
                check_phase6_non_latin,
                page=page,
            )

            context.close()
            browser.close()

        def check_debug_log_growth() -> None:
            debug_after = read_debug_log_line_count(debug_log_path)
            _expect(
                debug_after >= debug_log_before + 3,
                (
                    "Expected at least 3 new debug log events from automated search runs; "
                    f"before={debug_log_before} after={debug_after}"
                ),
            )

        run_check(
            "P6-07",
            "Phase 6",
            "Structured search debug log events append during automated closeout",
            check_debug_log_growth,
        )

    finally:
        if server_process is not None:
            server_process.terminate()
            try:
                server_process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=4)
        stop_threaded_server(jackett_server, jackett_thread)
        stop_threaded_server(qb_server, qb_thread)

    failures = [item for item in checks if item.status != "pass"]
    passed = len(checks) - len(failures)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "app_base_url": app_base_url,
        "mock_services": {
            "qb": qb_base_url,
            "jackett": jackett_base_url,
            "jackett_request_count": jackett_state.request_count,
        },
        "artifacts": {
            "run_dir": relative_path(run_dir, project_dir),
            "db": relative_path(db_path, project_dir),
            "uvicorn_log": relative_path(app_log_path, project_dir),
        },
        "counts": {
            "total": len(checks),
            "passed": passed,
            "failed": len(failures),
        },
        "checks": [asdict(item) for item in checks],
    }
    report_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    headline = (
        f"# Phase 4/5/6 Browser Closeout QA ({run_stamp})\n\n"
        f"- Total checks: **{len(checks)}**\n"
        f"- Passed: **{passed}**\n"
        f"- Failed: **{len(failures)}**\n"
        f"- App URL: `{app_base_url}`\n"
        f"- Mock qB URL: `{qb_base_url}`\n"
        f"- Mock Jackett URL: `{jackett_base_url}`\n"
        f"- Jackett requests observed: **{jackett_state.request_count}**\n\n"
    )
    report_md_path.write_text(headline + markdown_table(checks) + "\n", encoding="utf-8")

    print(f"Saved closeout report: {report_json_path}")
    print(f"Saved closeout summary: {report_md_path}")
    if failures:
        print(f"{len(failures)} check(s) failed.", file=sys.stderr)
        return 1
    print("All browser closeout checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

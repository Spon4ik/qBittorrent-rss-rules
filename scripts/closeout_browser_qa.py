#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote_plus, urlparse
from urllib.request import ProxyHandler, build_opener
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
    torrent_add_calls: list[dict[str, str]]


@dataclass(slots=True)
class MockJackettState:
    request_count: int = 0


FEED_ALPHA = "https://jackett.test/api/v2.0/indexers/alpha/results/torznab/api"
FEED_BETA = "https://jackett.test/api/v2.0/indexers/beta/results/torznab/api"
FEED_GAMMA = "https://jackett.test/api/v2.0/indexers/gamma/results/torznab/api"
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
        "id": "fallback-proper",
        "title": "Young Sherlock S01E01 Proper 2160p HDR10 WEB-DL (2026)",
        "link": "https://torrent.test/fallback-proper",
        "guid": "urn:fallback-proper",
        "comments": "https://torrent.test/details/fallback-proper",
        "pub_date": "Wed, 10 Jan 2026 09:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "",
        "size": 4900 * 1024 * 1024,
        "year": "2026",
        "seeders": 115,
        "peers": 165,
        "leechers": 50,
        "grabs": 390,
        "categories": ["5000", "5040"],
    },
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
        "title": "Young Sherlock Test Cut S01E01 2160p HDR10 (2026)",
        "link": "https://torrent.test/fallback-test-cut",
        "guid": "urn:fallback-test-cut",
        "comments": "https://torrent.test/details/fallback-test-cut",
        "pub_date": "Thu, 04 Jan 2026 15:00:00 GMT",
        "indexer": "beta",
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

GHOSTS_PRIMARY_ITEMS = [
    {
        "id": "ghosts-primary-1",
        "title": "Ghosts 2019 S05E00 Christmas Special 1080p HDTV H264-UKTV",
        "link": "https://torrent.test/ghosts-primary-1",
        "guid": "urn:ghosts-primary-1",
        "comments": "https://torrent.test/details/ghosts-primary-1",
        "pub_date": "Tue, 12 Jan 2026 10:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "tt8594324",
        "size": 1700 * 1024 * 1024,
        "year": "2023",
        "seeders": 66,
        "peers": 92,
        "leechers": 26,
        "grabs": 121,
        "categories": ["5000", "5040"],
    },
    {
        "id": "ghosts-primary-2",
        "title": "Ghosts US S05E00 Christmas Special 1080p HDTV H264-UKTV",
        "link": "https://torrent.test/ghosts-primary-2",
        "guid": "urn:ghosts-primary-2",
        "comments": "https://torrent.test/details/ghosts-primary-2",
        "pub_date": "Mon, 11 Jan 2026 10:00:00 GMT",
        "indexer": "beta",
        "imdb_id": "",
        "size": 1650 * 1024 * 1024,
        "year": "2023",
        "seeders": 48,
        "peers": 71,
        "leechers": 23,
        "grabs": 97,
        "categories": ["5000", "5040"],
    },
]

KNIVES_OUT_PRIMARY_ITEMS = [
    {
        "id": "knives-out-primary-1",
        "title": "Knives Out 2019 2160p HDR WEB-DL",
        "link": "https://torrent.test/knives-out-primary-1",
        "guid": "urn:knives-out-primary-1",
        "comments": "https://torrent.test/details/knives-out-primary-1",
        "pub_date": "Tue, 12 Jan 2026 11:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "",
        "size": 6200 * 1024 * 1024,
        "year": "2019",
        "seeders": 140,
        "peers": 220,
        "leechers": 80,
        "grabs": 460,
        "categories": ["2000", "2045"],
    },
    {
        "id": "knives-out-primary-2",
        "title": "Glass Onion: A Knives Out Mystery 2022 2160p HDR WEB-DL",
        "link": "https://torrent.test/knives-out-primary-2",
        "guid": "urn:knives-out-primary-2",
        "comments": "https://torrent.test/details/knives-out-primary-2",
        "pub_date": "Mon, 11 Jan 2026 11:00:00 GMT",
        "indexer": "beta",
        "imdb_id": "",
        "size": 6100 * 1024 * 1024,
        "year": "2022",
        "seeders": 118,
        "peers": 180,
        "leechers": 62,
        "grabs": 382,
        "categories": ["2000", "2045"],
    },
    {
        "id": "knives-out-primary-3",
        "title": "Wake Up Dead Man: A Knives Out Mystery 2025 2160p HDR WEB-DL",
        "link": "https://torrent.test/knives-out-primary-3",
        "guid": "urn:knives-out-primary-3",
        "comments": "https://torrent.test/details/knives-out-primary-3",
        "pub_date": "Sun, 10 Jan 2026 11:00:00 GMT",
        "indexer": "gamma",
        "imdb_id": "",
        "size": 6300 * 1024 * 1024,
        "year": "2025",
        "seeders": 124,
        "peers": 188,
        "leechers": 64,
        "grabs": 401,
        "categories": ["2000", "2045"],
    },
]

CREATOR_PRIMARY_ITEMS = [
    {
        "id": "creator-primary-1",
        "title": "The Creator 2023 2160p HDR WEB-DL",
        "link": "https://torrent.test/creator-primary-1",
        "guid": "urn:creator-primary-1",
        "comments": "https://torrent.test/details/creator-primary-1",
        "pub_date": "Tue, 12 Jan 2026 12:00:00 GMT",
        "indexer": "alpha",
        "imdb_id": "tt11858890",
        "size": 6500 * 1024 * 1024,
        "year": "2023",
        "seeders": 132,
        "peers": 210,
        "leechers": 78,
        "grabs": 444,
        "categories": ["2000", "2045"],
    },
    {
        "id": "creator-primary-2",
        "title": "Создатель / The Creator (2023) WEB-DL 2160p HDR",
        "link": "https://torrent.test/creator-primary-2",
        "guid": "urn:creator-primary-2",
        "comments": "https://torrent.test/details/creator-primary-2",
        "pub_date": "Mon, 11 Jan 2026 12:00:00 GMT",
        "indexer": "beta",
        "imdb_id": "",
        "size": 6400 * 1024 * 1024,
        "year": "2023",
        "seeders": 121,
        "peers": 198,
        "leechers": 73,
        "grabs": 417,
        "categories": ["2000", "2045"],
    },
]

WHAT_LIES_BENEATH_PRIMARY_ITEMS = [
    {
        "id": "what-lies-beneath-primary-1",
        "title": "What Lies Beneath 2000 DUB, MVO, AVO, Sub 4K, HEVC, HDR, Dolby Vision P8 BDRip 2160p - RUSSIAN",
        "link": "https://torrent.test/what-lies-beneath-primary-1",
        "guid": "urn:what-lies-beneath-primary-1",
        "comments": "https://torrent.test/details/what-lies-beneath-primary-1",
        "pub_date": "Tue, 12 Jan 2026 12:30:00 GMT",
        "indexer": "alpha",
        "imdb_id": "tt0161081",
        "size": 40 * 1024 * 1024 * 1024,
        "year": "2000",
        "seeders": 88,
        "peers": 132,
        "leechers": 44,
        "grabs": 205,
        "categories": ["2000"],
    }
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

LOCAL_URL_OPENER = build_opener(ProxyHandler({}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic browser-closeout QA for phases 4/5/6/7/9 using "
            "isolated mock qBittorrent + Jackett services."
        )
    )
    parser.add_argument(
        "--output-dir", default="logs/qa", help="Directory for timestamped QA artifacts."
    )
    parser.add_argument(
        "--timeout-ms", type=int, default=25000, help="Playwright step timeout in milliseconds."
    )
    parser.add_argument(
        "--headful", action="store_true", help="Run Chromium with a visible window."
    )
    parser.add_argument(
        "--p9-hover-sample-count",
        type=int,
        default=4,
        help="How many lower visible rules to capture for phase-9 hover-overlay evidence.",
    )
    parser.add_argument(
        "--capture-p9-hover-video",
        action="store_true",
        help="Also record a short Playwright video for the phase-9 lower-list hover-overlay sequence.",
    )
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
            with LOCAL_URL_OPENER.open(url, timeout=1.5) as response:  # noqa: S310
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
            if parsed.path == "/api/v2/torrents/add":
                state.torrent_add_calls.append(
                    {key: values[-1] if values else "" for key, values in form.items()}
                )
                self._write_text("", status=200)
                return
            self._write_json({"error": f"Unhandled POST path: {parsed.path}"}, status=404)

    return QbHandler


def _torznab_indexers_xml() -> str:
    category_tree = (
        "<categories>"
        '<category id="5000" name="TV">'
        '<subcat id="5040" name="HD" />'
        '<subcat id="5050" name="UHD" />'
        '<subcat id="5070" name="CAM" />'
        '<subcat id="5080" name="Documentary" />'
        "</category>"
        '<category id="3000" name="Audio">'
        '<subcat id="3030" name="Audiobook" />'
        "</category>"
        "</categories>"
    )
    indexer_blocks: list[str] = []
    for indexer_id in (
        "alpha",
        "beta",
        "gamma",
        "hdrezka",
        "delta",
        "epsilon",
        "zeta",
        "theta",
        "books",
    ):
        indexer_blocks.append(
            f'<indexer id="{indexer_id}">'
            "<caps>"
            '<tv-search available="yes" supportedParams="q,imdbid" />'
            '<movie-search available="yes" supportedParams="q,imdbid" />'
            '<book-search available="yes" supportedParams="q" />'
            f"{category_tree}"
            "</caps>"
            "</indexer>"
        )
    return f'<?xml version="1.0" encoding="UTF-8"?><indexers>{"".join(indexer_blocks)}</indexers>'


def _torznab_caps_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<caps>"
        "<searching>"
        '<search available="yes" supportedParams="q" />'
        '<tv-search available="yes" supportedParams="q,imdbid" />'
        '<movie-search available="yes" supportedParams="q,imdbid" />'
        '<book-search available="yes" supportedParams="q" />'
        '<music-search available="yes" supportedParams="q" />'
        "</searching>"
        "</caps>"
    )


def _torznab_item_xml(item: dict[str, Any]) -> str:
    category_lines = "".join(
        f"<category>{escape(str(category_id))}</category>"
        for category_id in item.get("categories", [])
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
        attr_lines += f'<attr name="{escape(name)}" value="{escape(text)}" />'

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
        f'<guid isPermaLink="false">{guid}</guid>'
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
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0">'
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


def _jackett_items_for_imdb(imdb_id: str, *, mode: str) -> list[dict[str, Any]]:
    normalized = str(imdb_id or "").strip().casefold()
    if mode == "tvsearch":
        if normalized == "tt8599532":
            return PRIMARY_ITEMS
        if normalized == "tt8594324":
            return GHOSTS_PRIMARY_ITEMS
        return []
    if mode == "movie":
        if normalized == "tt8946378":
            return KNIVES_OUT_PRIMARY_ITEMS
        if normalized == "tt11858890":
            return CREATOR_PRIMARY_ITEMS
        if normalized == "tt0161081":
            return WHAT_LIES_BENEATH_PRIMARY_ITEMS
        return []
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
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<error code="203" description="{escape(message)}" />'
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
                self._write_xml(_torznab_results_xml(_jackett_items_for_imdb(imdb_id, mode=mode)))
                return
            if text_query:
                self._write_xml(_torznab_results_xml(_jackett_items_for_query(text_query)))
                return
            self._write_xml(_torznab_results_xml([]))

    return JackettHandler


def start_threaded_server(
    handler: type[BaseHTTPRequestHandler], host: str, port: int
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_threaded_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def read_debug_log_line_count(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return None


def prepare_closeout_db(
    *,
    db_path: Path,
    qb_base_url: str,
    jackett_base_url: str,
    feed_urls: list[str],
) -> None:
    from app.config import get_environment_settings, obfuscate_secret
    from app.db import get_session_factory, init_db, reset_db_caches
    from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus

    env_overrides = {
        "QB_RULES_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "QB_RULES_QB_BASE_URL": qb_base_url,
        "QB_RULES_QB_USERNAME": "admin",
        "QB_RULES_QB_PASSWORD": "adminadmin",
        "QB_RULES_JACKETT_API_URL": jackett_base_url,
        "QB_RULES_JACKETT_QB_URL": jackett_base_url,
        "QB_RULES_JACKETT_API_KEY": "qa-key",
        "QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER": "0",
        "QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER": "0",
        "QB_RULES_ENABLE_RULE_FETCH_SCHEDULER": "0",
    }
    previous_env = {key: os.environ.get(key) for key in env_overrides}
    try:
        os.environ.update(env_overrides)
        get_environment_settings.cache_clear()
        reset_db_caches()
        init_db()
        session_factory = get_session_factory()
        with session_factory() as session:
            settings = session.get(AppSettings, "default")
            if settings is None:
                settings = AppSettings(id="default")
            settings.qb_base_url = qb_base_url
            settings.qb_username = "admin"
            settings.qb_password_encrypted = obfuscate_secret("adminadmin")
            settings.jackett_api_url = jackett_base_url
            settings.jackett_qb_url = jackett_base_url
            settings.jackett_api_key_encrypted = obfuscate_secret("qa-key")
            settings.default_feed_urls = list(feed_urls)
            settings.saved_quality_profiles = {
                "qa-no-match-profile": {
                    "label": "QA No Match Profile",
                    "include_tokens": ["dolby_vision"],
                    "exclude_tokens": [],
                    "media_types": ["series"],
                }
            }
            session.add(settings)
            existing_names = set(
                session.query(Rule.rule_name)
                .filter(Rule.rule_name.like("QA P9 Hover Seed %"))
                .all()
            )
            existing_names = {item[0] for item in existing_names}
            for index in range(12):
                rule_name = f"QA P9 Hover Seed {index + 1:02d}"
                if rule_name in existing_names:
                    continue
                session.add(
                    Rule(
                        rule_name=rule_name,
                        content_name=rule_name,
                        normalized_title=rule_name,
                        imdb_id=f"tt{9000000 + index}",
                        poster_url=build_svg_data_url(rule_name),
                        media_type=MediaType.SERIES if index % 2 == 0 else MediaType.MOVIE,
                        quality_profile=QualityProfile.PLAIN,
                        feed_urls=[feed_urls[index % len(feed_urls)]],
                        enabled=True,
                        last_sync_status=SyncStatus.OK,
                    )
                )
            qa_p19_rule = session.query(Rule).filter(Rule.rule_name == "QA P19 Inline Search Profile").one_or_none()
            if qa_p19_rule is None:
                session.add(
                    Rule(
                        rule_name="QA P19 Inline Search Profile",
                        content_name="Young Sherlock",
                        normalized_title="Young Sherlock",
                        imdb_id="tt8599532",
                        media_type=MediaType.SERIES,
                        quality_profile=QualityProfile.PLAIN,
                        feed_urls=list(feed_urls),
                        enabled=True,
                        last_sync_status=SyncStatus.OK,
                    )
                )
            p23_rule_specs = [
                {
                    "rule_name": "QA P23 Series Exact",
                    "content_name": "Young Sherlock",
                    "normalized_title": "Young Sherlock",
                    "imdb_id": "tt8599532",
                    "media_type": MediaType.SERIES,
                    "quality_profile": QualityProfile.PLAIN,
                    "quality_include_tokens": ["2160p", "hdr"],
                    "additional_includes": "test cut",
                    "start_season": 1,
                    "start_episode": 1,
                },
                {
                    "rule_name": "QA P23 Series Special Exact",
                    "content_name": "Ghosts",
                    "normalized_title": "Ghosts",
                    "imdb_id": "tt8594324",
                    "media_type": MediaType.SERIES,
                    "quality_profile": QualityProfile.PLAIN,
                    "quality_include_tokens": ["1080p"],
                    "start_season": 5,
                    "start_episode": 0,
                },
                {
                    "rule_name": "QA P23 Movie Exact",
                    "content_name": "Knives Out",
                    "normalized_title": "Knives Out",
                    "imdb_id": "tt8946378",
                    "media_type": MediaType.MOVIE,
                    "quality_profile": QualityProfile.PLAIN,
                    "quality_include_tokens": ["2160p", "hdr"],
                },
                {
                    "rule_name": "QA P23 Movie Direct Exact",
                    "content_name": "The Creator",
                    "normalized_title": "The Creator",
                    "imdb_id": "tt11858890",
                    "media_type": MediaType.MOVIE,
                    "quality_profile": QualityProfile.PLAIN,
                    "quality_include_tokens": ["2160p", "hdr"],
                    "include_release_year": True,
                    "release_year": "2023",
                },
                {
                    "rule_name": "QA P23 Movie BDRip Exact",
                    "content_name": "What Lies Beneath",
                    "normalized_title": "What Lies Beneath",
                    "imdb_id": "tt0161081",
                    "media_type": MediaType.MOVIE,
                    "quality_profile": QualityProfile.PLAIN,
                    "quality_include_tokens": [
                        "ultra_hd",
                        "uhd",
                        "2160p",
                        "4k",
                        "hdr",
                        "dolby_vision",
                    ],
                    "quality_exclude_tokens": ["bdremux", "bluray"],
                },
            ]
            for spec in p23_rule_specs:
                existing_rule = session.query(Rule).filter(Rule.rule_name == spec["rule_name"]).one_or_none()
                if existing_rule is not None:
                    continue
                session.add(
                    Rule(
                        rule_name=str(spec["rule_name"]),
                        content_name=str(spec["content_name"]),
                        normalized_title=str(spec["normalized_title"]),
                        imdb_id=str(spec["imdb_id"]),
                        media_type=spec["media_type"],
                        quality_profile=spec["quality_profile"],
                        quality_include_tokens=list(spec.get("quality_include_tokens", [])),
                        quality_exclude_tokens=list(spec.get("quality_exclude_tokens", [])),
                        additional_includes=str(spec.get("additional_includes", "")),
                        include_release_year=bool(spec.get("include_release_year", False)),
                        release_year=str(spec.get("release_year", "")),
                        start_season=spec.get("start_season"),
                        start_episode=spec.get("start_episode"),
                        feed_urls=list(feed_urls),
                        enabled=True,
                        last_sync_status=SyncStatus.OK,
                    )
                )
            session.commit()
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_environment_settings.cache_clear()
        reset_db_caches()


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


def _query_source_rank(source_key: str) -> int:
    normalized = str(source_key or "").strip().casefold()
    if normalized == "primary":
        return 0
    if normalized == "primary+fallback":
        return 1
    if normalized == "fallback":
        return 2
    return 9


def _sorted_combined_title_pairs(
    pairs: list[tuple[str, str]],
    *,
    reverse: bool,
) -> list[tuple[str, str]]:
    sorted_pairs = sorted(
        pairs,
        key=lambda item: (_query_source_rank(item[1]), item[0].casefold()),
    )
    if reverse:
        grouped: dict[str, list[tuple[str, str]]] = {}
        group_order: list[str] = []
        for pair in sorted_pairs:
            source_key = pair[1]
            if source_key not in grouped:
                grouped[source_key] = []
                group_order.append(source_key)
            grouped[source_key].append(pair)
        reversed_pairs: list[tuple[str, str]] = []
        for source_key in group_order:
            reversed_pairs.extend(reversed(grouped[source_key]))
        return reversed_pairs
    return sorted_pairs


def build_svg_data_url(label: str) -> str:
    safe_label = escape(label)
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300" role="img" aria-label="{safe_label}">
      <defs>
        <linearGradient id="bg" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stop-color="#29434e" />
          <stop offset="100%" stop-color="#bf6c2c" />
        </linearGradient>
      </defs>
      <rect width="200" height="300" rx="18" fill="url(#bg)" />
      <rect x="18" y="18" width="164" height="264" rx="14" fill="rgba(255,252,246,0.14)" />
      <text x="100" y="126" font-family="Arial, sans-serif" font-size="18" font-weight="700" text-anchor="middle" fill="#fff">QA Hover</text>
      <text x="100" y="156" font-family="Arial, sans-serif" font-size="15" text-anchor="middle" fill="#fff">{safe_label}</text>
      <text x="100" y="266" font-family="Arial, sans-serif" font-size="12" text-anchor="middle" fill="#f3e5d0">2:3 poster stub</text>
    </svg>
    """.strip()
    return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"


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
    # Use `localhost.` (trailing dot) so WSL localhost rewrite logic does not
    # rewrite this deterministic local mock URL to host.docker.internal.
    qb_base_url = f"http://localhost.:{qb_port}"
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
        torrent_add_calls=[],
    )
    jackett_state = MockJackettState(request_count=0)
    p9_hover_artifacts: list[str] = []
    p9_hover_manifest_path: str | None = None
    p9_hover_video_path: str | None = None

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
    env["QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER"] = "0"
    env["QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER"] = "0"
    env["QB_RULES_ENABLE_RULE_FETCH_SCHEDULER"] = "0"

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
        prepare_closeout_db(
            db_path=db_path,
            qb_base_url=qb_base_url,
            jackett_base_url=jackett_base_url,
            feed_urls=DEFAULT_FEEDS,
        )
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

        if not wait_for_http(f"{app_base_url}/health", timeout_seconds=90):
            raise RuntimeError(f"Timed out waiting for isolated app server ({app_base_url}).")

        debug_log_path = project_dir / "logs" / "search-debug.log"
        debug_log_before = read_debug_log_line_count(debug_log_path)

        try:
            import playwright.sync_api as playwright_sync_api
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed for this interpreter. "
                f"Install with `{sys.executable} -m pip install playwright` and "
                f"`{sys.executable} -m playwright install chromium`."
            ) from exc

        with playwright_sync_api.sync_playwright() as playwright:
            viewport = {"width": 1720, "height": 1040}
            browser = playwright.chromium.launch(headless=not args.headful)
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            app_requests: list[str] = []

            def on_request(request: Any) -> None:
                if request.url.startswith(app_base_url):
                    app_requests.append(request.url)

            page.on("request", on_request)

            def request_count() -> int:
                return len(app_requests)

            phase7_context: dict[str, str] = {}

            def wait_for_torrent_add_calls(expected_count: int) -> None:
                timeout_at = time.monotonic() + (args.timeout_ms / 1000)
                while time.monotonic() < timeout_at:
                    if len(qb_state.torrent_add_calls) >= expected_count:
                        return
                    page.wait_for_timeout(80)
                _expect(
                    False,
                    (
                        "Timed out waiting for qB torrent add call count to reach "
                        f"{expected_count}; saw {len(qb_state.torrent_add_calls)}."
                    ),
                )

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

            def resolve_result_section(section: str) -> str:
                if page.locator(f'[data-search-summary="{section}"]').count() == 0:
                    return "combined"
                return section

            def source_keys_for_section(section: str) -> list[str]:
                if section in {"primary", "fallback"}:
                    return [section]
                return []

            def count_rows_for_sources(source_keys: list[str], *, visible_only: bool) -> int:
                return int(
                    page.evaluate(
                        """
                        ({ sourceKeys, visibleOnly }) => Array
                          .from(document.querySelectorAll('[data-search-row="combined"]'))
                          .filter((row) => !visibleOnly || !row.hidden)
                          .filter((row) => {
                            const source = (row.getAttribute("data-query-source-key") || "").trim().toLowerCase();
                            if (!sourceKeys.length) {
                              return true;
                            }
                            if (source === "primary+fallback") {
                              return sourceKeys.some((key) => key === "primary" || key === "fallback");
                            }
                            return sourceKeys.includes(source);
                          })
                          .length
                        """,
                        {"sourceKeys": source_keys, "visibleOnly": visible_only},
                    )
                )

            def search_filtered_count(section: str) -> int:
                source_keys = source_keys_for_section(section)
                if source_keys:
                    return count_rows_for_sources(source_keys, visible_only=True)
                resolved_section = resolve_result_section(section)
                if resolved_section == section:
                    raw = (
                        page.text_content(f'[data-search-filtered-count="{resolved_section}"]')
                        or "0"
                    )
                    return int(raw.strip() or "0")
                raw = page.text_content('[data-search-filtered-count="combined"]') or "0"
                return int(raw.strip() or "0")

            def search_fetched_count(section: str) -> int:
                source_keys = source_keys_for_section(section)
                if source_keys:
                    return count_rows_for_sources(source_keys, visible_only=False)
                resolved_section = resolve_result_section(section)
                if resolved_section == section:
                    raw = (
                        page.text_content(f'[data-search-fetched-count="{resolved_section}"]')
                        or "0"
                    )
                    return int(raw.strip() or "0")
                raw = page.text_content('[data-search-fetched-count="combined"]') or "0"
                return int(raw.strip() or "0")

            def search_visible_titles(section: str) -> list[str]:
                source_keys = source_keys_for_section(section)
                return page.evaluate(
                    """
                    ({ sourceKeys }) => Array
                      .from(document.querySelectorAll('[data-search-row="combined"]'))
                      .filter((row) => !row.hidden)
                      .filter((row) => {
                        const source = (row.getAttribute("data-query-source-key") || "").trim().toLowerCase();
                        if (!sourceKeys.length) {
                          return true;
                        }
                        if (source === "primary+fallback") {
                          return sourceKeys.some((key) => key === "primary" || key === "fallback");
                        }
                        return sourceKeys.includes(source);
                      })
                      .map((row) => row.querySelector("td:nth-child(2)")?.textContent?.trim() || "")
                      .filter(Boolean)
                    """,
                    {"sourceKeys": source_keys},
                )

            def search_visible_title_source_pairs(section: str) -> list[tuple[str, str]]:
                source_keys = source_keys_for_section(section)
                raw_pairs = page.evaluate(
                    """
                    ({ sourceKeys }) => Array
                      .from(document.querySelectorAll('[data-search-row="combined"]'))
                      .filter((row) => !row.hidden)
                      .filter((row) => {
                        const source = (row.getAttribute("data-query-source-key") || "").trim().toLowerCase();
                        if (!sourceKeys.length) {
                          return true;
                        }
                        if (source === "primary+fallback") {
                          return sourceKeys.some((key) => key === "primary" || key === "fallback");
                        }
                        return sourceKeys.includes(source);
                      })
                      .map((row) => [
                        row.querySelector("td:nth-child(2)")?.textContent?.trim() || "",
                        (row.getAttribute("data-query-source-key") || "").trim().toLowerCase(),
                      ])
                      .filter((pair) => pair[0])
                    """,
                    {"sourceKeys": source_keys},
                )
                return [
                    (str(item[0]).strip(), str(item[1]).strip())
                    for item in raw_pairs
                    if isinstance(item, list) and len(item) == 2 and str(item[0]).strip()
                ]

            def wait_for_filtered_count(
                section: str,
                expected: int,
                *,
                timeout_ms: int | None = None,
            ) -> None:
                source_keys = source_keys_for_section(section)
                if source_keys:
                    page.wait_for_function(
                        """
                        ({ sourceKeys, expectedCount }) => {
                          const rows = Array.from(document.querySelectorAll('[data-search-row="combined"]'));
                          const count = rows
                            .filter((row) => !row.hidden)
                            .filter((row) => {
                              const source = (row.getAttribute("data-query-source-key") || "").trim().toLowerCase();
                              if (!sourceKeys.length) {
                                return true;
                              }
                              if (source === "primary+fallback") {
                                return sourceKeys.some((key) => key === "primary" || key === "fallback");
                              }
                              return sourceKeys.includes(source);
                            })
                            .length;
                          return count === expectedCount;
                        }
                        """,
                        arg={"sourceKeys": source_keys, "expectedCount": expected},
                        timeout=timeout_ms or args.timeout_ms,
                    )
                    return

                resolved_section = resolve_result_section(section)
                section_key = resolved_section if resolved_section == section else "combined"
                page.wait_for_function(
                    """
                    ({ sectionKey, expectedCount }) => {
                      const element = document.querySelector(`[data-search-filtered-count="${sectionKey}"]`);
                      if (!element) {
                        return false;
                      }
                      const value = Number.parseInt((element.textContent || "0").trim(), 10);
                      return Number.isFinite(value) && value === expectedCount;
                    }
                    """,
                    arg={"sectionKey": section_key, "expectedCount": expected},
                    timeout=timeout_ms or args.timeout_ms,
                )

            def reset_inline_local_filters_for_visibility() -> None:
                matching_section = page.locator("details:has-text('Matching And Quality')").first
                if matching_section.count() == 1 and not matching_section.evaluate(
                    "node => Boolean(node.open)"
                ):
                    matching_section.locator("summary").click()
                if page.locator('textarea[name="must_not_contain"]').count() == 1:
                    page.fill('textarea[name="must_not_contain"]', "")
                if page.locator('textarea[name="additional_includes"]').count() == 1:
                    page.fill('textarea[name="additional_includes"]', "")
                include_release_year = page.locator('input[name="include_release_year"]')
                if include_release_year.count() == 1 and include_release_year.is_checked():
                    include_release_year.uncheck()
                page.evaluate(
                    """
                    () => {
                      const inputs = document.querySelectorAll(
                        'input[name="quality_include_tokens"], input[name="quality_exclude_tokens"]'
                      );
                      for (const input of inputs) {
                        if (!(input instanceof HTMLInputElement)) {
                          continue;
                        }
                        if (!input.checked) {
                          continue;
                        }
                        input.checked = false;
                        input.dispatchEvent(new Event("change", { bubbles: true }));
                      }
                    }
                    """
                )
                page.wait_for_timeout(260)

            run_check(
                "P4-01",
                "Phase 4",
                "Feed checkboxes render with remembered default prefill",
                lambda: (
                    page.goto(
                        f"{app_base_url}/rules/new",
                        wait_until="networkidle",
                        timeout=args.timeout_ms,
                    ),
                    page.wait_for_selector(
                        '#feed-options input[name="feed_urls"]', timeout=args.timeout_ms
                    ),
                    _expect(
                        len(all_feed_values()) >= 3,
                        "Expected at least 3 feed checkboxes from mock qB.",
                    ),
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
                    _expect(
                        len(checked_feed_values()) == 0, "Clear all should uncheck every feed."
                    ),
                    page.click("#feed-select-all"),
                    _expect(
                        len(checked_feed_values()) == len(all_feed_values()),
                        "Select all should check every feed.",
                    ),
                ),
                page=page,
            )

            def check_phase9_rules_main_page_workspace() -> None:
                nonlocal p9_hover_artifacts, p9_hover_manifest_path, p9_hover_video_path

                def capture_lower_hover_overlay_evidence(
                    target_page: Any,
                    *,
                    evidence_dir: Path,
                    artifact_prefix: str,
                    capture_screenshots: bool,
                ) -> tuple[list[str], str, list[dict[str, Any]]]:
                    target_page.goto(
                        f"{app_base_url}/", wait_until="networkidle", timeout=args.timeout_ms
                    )
                    target_page.wait_for_selector("[data-rules-page]", timeout=args.timeout_ms)
                    target_poster_rows = target_page.locator(
                        '[data-rules-row][data-rule-poster-url]:not([data-rule-poster-url=""])'
                    )
                    target_hover_poster = target_page.locator("[data-rules-hover-poster]").first
                    target_row_count = target_poster_rows.count()
                    _expect(
                        target_row_count >= max(8, args.p9_hover_sample_count + 4),
                        (
                            "Expected enough poster-backed rules to exercise lower-list hover behavior; "
                            f"saw {target_row_count}."
                        ),
                    )
                    target_poster_rows.nth(target_row_count - 1).evaluate(
                        "node => node.scrollIntoView({ block: 'end', inline: 'nearest' })"
                    )
                    target_page.wait_for_timeout(240)
                    viewport_height = float(target_page.evaluate("window.innerHeight"))
                    visible_indexes: list[int] = []
                    for row_index in range(target_row_count):
                        row_box = target_poster_rows.nth(row_index).bounding_box()
                        if row_box is None:
                            continue
                        row_top = float(row_box["y"])
                        row_bottom = float(row_box["y"] + row_box["height"])
                        if row_top >= 0 and row_bottom <= viewport_height + 1:
                            visible_indexes.append(row_index)
                    sample_count = max(2, min(args.p9_hover_sample_count, len(visible_indexes)))
                    sample_indexes = visible_indexes[-sample_count:]
                    _expect(
                        len(sample_indexes) >= 2,
                        (
                            "Expected at least two lower visible poster rows for hover evidence; "
                            f"visible_indexes={visible_indexes}."
                        ),
                    )

                    screenshot_artifacts: list[str] = []
                    manifest_rows: list[dict[str, Any]] = []
                    for sequence_number, row_index in enumerate(sample_indexes, start=1):
                        target_row = target_poster_rows.nth(row_index)
                        target_row.hover()
                        target_page.wait_for_timeout(260)
                        target_page.wait_for_function(
                            """
                            () => {
                              const img = document.querySelector('[data-rules-hover-image]');
                              return Boolean(img && img.complete && img.naturalWidth > 0);
                            }
                            """,
                            timeout=args.timeout_ms,
                        )
                        _expect(
                            not target_hover_poster.evaluate("node => Boolean(node.hidden)"),
                            "Hover poster should appear for each sampled lower-list rule.",
                        )
                        row_box = target_row.bounding_box()
                        poster_box = target_hover_poster.bounding_box()
                        _expect(
                            row_box is not None and poster_box is not None,
                            f"Expected row and poster bounding boxes for sampled row index {row_index}.",
                        )
                        row_name = target_row.get_attribute("data-rule-name") or f"row-{row_index}"
                        row_top = float(row_box["y"]) if row_box is not None else -1.0
                        row_bottom = (
                            float(row_box["y"] + row_box["height"]) if row_box is not None else -1.0
                        )
                        row_center = (
                            float(row_box["y"] + (row_box["height"] / 2))
                            if row_box is not None
                            else -1.0
                        )
                        poster_top = float(poster_box["y"]) if poster_box is not None else -1.0
                        poster_bottom = (
                            float(poster_box["y"] + poster_box["height"])
                            if poster_box is not None
                            else -1.0
                        )
                        edge_gap = (
                            abs(poster_bottom - row_bottom)
                            if poster_top < row_top
                            else abs(poster_top - row_top)
                        )
                        within_viewport = poster_top >= 0 and poster_bottom <= viewport_height + 1
                        manifest_rows.append(
                            {
                                "sequence": sequence_number,
                                "row_index": row_index,
                                "row_name": row_name,
                                "row_top": row_top,
                                "row_bottom": row_bottom,
                                "row_center": row_center,
                                "poster_top": poster_top,
                                "poster_bottom": poster_bottom,
                                "edge_gap": edge_gap,
                                "within_viewport": within_viewport,
                            }
                        )
                        if capture_screenshots:
                            screenshot_path = evidence_dir / (
                                f"{artifact_prefix}-hover-{sequence_number:02d}-row-{row_index:02d}.png"
                            )
                            target_page.screenshot(path=str(screenshot_path), full_page=False)
                            screenshot_artifacts.append(relative_path(screenshot_path, project_dir))

                    manifest_path = evidence_dir / f"{artifact_prefix}-manifest.json"
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "generated_at": datetime.now(UTC).isoformat(),
                                "target_url": f"{app_base_url}/",
                                "viewport": viewport,
                                "visible_indexes": visible_indexes,
                                "sample_indexes": sample_indexes,
                                "rows": manifest_rows,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    return (
                        screenshot_artifacts,
                        relative_path(manifest_path, project_dir),
                        manifest_rows,
                    )

                def capture_p9_hover_video(evidence_dir: Path) -> str | None:
                    video_context = browser.new_context(
                        viewport=viewport,
                        record_video_dir=str(evidence_dir),
                        record_video_size=viewport,
                    )
                    video_page = video_context.new_page()
                    video_handle = video_page.video
                    try:
                        capture_lower_hover_overlay_evidence(
                            video_page,
                            evidence_dir=evidence_dir,
                            artifact_prefix="p9-hover-video",
                            capture_screenshots=False,
                        )
                    finally:
                        video_context.close()
                    if video_handle is None:
                        return None
                    video_path = Path(video_handle.path())
                    target_path = evidence_dir / "p9-hover-overlay.webm"
                    if video_path != target_path:
                        if target_path.exists():
                            target_path.unlink()
                        video_path.replace(target_path)
                    return relative_path(target_path, project_dir)

                page.goto(f"{app_base_url}/", wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector("[data-rules-page]", timeout=args.timeout_ms)
                table_wrap = page.locator("[data-rules-table-wrap]").first
                cards_wrap = page.locator("[data-rules-cards-wrap]").first

                poster_rows = page.locator(
                    '[data-rules-row][data-rule-poster-url]:not([data-rule-poster-url=""])'
                )

                if (
                    table_wrap.count() == 1
                    and cards_wrap.count() == 1
                    and page.locator("[data-rules-row]").count() >= 1
                ):
                    _expect(
                        table_wrap.evaluate("node => !node.hidden"),
                        "Rules page should default to table view.",
                    )
                    _expect(
                        cards_wrap.evaluate("node => Boolean(node.hidden)"),
                        "Rules cards view should be hidden by default.",
                    )
                    page.click('[data-rules-view-mode-button="cards"]')
                    page.wait_for_timeout(120)
                    _expect(
                        cards_wrap.evaluate("node => !node.hidden"),
                        "Rules cards view should become visible after cards toggle.",
                    )
                    page.click('[data-rules-view-mode-button="table"]')
                    page.wait_for_timeout(120)
                    _expect(
                        table_wrap.evaluate("node => !node.hidden"),
                        "Rules table should become visible after table toggle.",
                    )

                    poster_row_count = poster_rows.count()
                    _expect(
                        poster_row_count >= max(8, args.p9_hover_sample_count + 4),
                        (
                            "Expected enough poster-backed rules for lower-list hover evidence; "
                            f"saw {poster_row_count}."
                        ),
                    )
                    hover_poster = page.locator("[data-rules-hover-poster]").first
                    _expect(
                        hover_poster.count() == 1,
                        "Rules table should render hover-poster shell.",
                    )

                    p9_hover_dir = run_dir / "p9-hover-overlay"
                    p9_hover_dir.mkdir(parents=True, exist_ok=True)
                    (
                        p9_hover_artifacts,
                        p9_hover_manifest_path,
                        p9_hover_rows,
                    ) = capture_lower_hover_overlay_evidence(
                        page,
                        evidence_dir=p9_hover_dir,
                        artifact_prefix="p9-hover-overlay",
                        capture_screenshots=True,
                    )
                    for hover_row in p9_hover_rows:
                        _expect(
                            bool(hover_row["within_viewport"]),
                            (
                                "Hover poster should stay fully visible inside the viewport for sampled lower rows; "
                                f"row_index={hover_row['row_index']} poster_top={hover_row['poster_top']:.1f} "
                                f"poster_bottom={hover_row['poster_bottom']:.1f}"
                            ),
                        )
                        _expect(
                            float(hover_row["edge_gap"]) <= 60,
                            (
                                "Hover poster should stay adjacent to each sampled lower-row hover instead of jumping to a detached upper zone; "
                                f"row_index={hover_row['row_index']} row_top={hover_row['row_top']:.1f} "
                                f"poster_top={hover_row['poster_top']:.1f} poster_bottom={hover_row['poster_bottom']:.1f} "
                                f"edge_gap={hover_row['edge_gap']:.1f}"
                            ),
                        )
                    if args.capture_p9_hover_video:
                        p9_hover_video_path = capture_p9_hover_video(p9_hover_dir)
                else:
                    _expect(
                        page.locator(".empty-state").count() == 1,
                        "Rules page should show empty-state when no rules are present.",
                    )

                page.click("[data-rules-save-defaults]")
                page.wait_for_timeout(300)
                _expect(
                    page.locator("[data-rules-run-status]").count() == 1,
                    "Rules main page should keep a run-status surface after saving defaults.",
                )

                schedule_enabled = page.locator("[data-rules-schedule-enabled]")
                _expect(
                    schedule_enabled.count() == 1,
                    "Rules main page should expose schedule-enabled toggle.",
                )
                if not schedule_enabled.first.is_checked():
                    schedule_enabled.first.check()
                page.fill("[data-rules-schedule-interval]", "5")
                page.select_option("[data-rules-schedule-scope]", "enabled")
                page.click("[data-rules-schedule-save]")
                page.wait_for_timeout(300)
                _expect(
                    schedule_enabled.count() == 1,
                    "Rules main page should keep schedule controls after saving the schedule.",
                )
                page.goto(
                    f"{app_base_url}/rules/new", wait_until="networkidle", timeout=args.timeout_ms
                )
                page.wait_for_selector('input[name="rule_name"]', timeout=args.timeout_ms)

            run_check(
                "P9-01",
                "Phase 9",
                "Rules main-page workspace supports table-first view, cards toggle, defaults save, and schedule save",
                check_phase9_rules_main_page_workspace,
                page=page,
            )

            dialog_messages: list[str] = []

            def on_dialog(dialog: Any) -> None:
                dialog_messages.append(dialog.message)
                dialog.accept()

            page.on("dialog", on_dialog)

            def check_phase5_media_behavior() -> None:
                _expect(
                    page.is_visible('[data-imdb-field="true"]'),
                    "IMDb field should be visible for series.",
                )
                series_providers = page.eval_on_selector_all(
                    "#metadata-lookup-provider option",
                    "els => els.map((el) => el.value)",
                )
                _expect(
                    series_providers == ["omdb"], f"Series providers mismatch: {series_providers}"
                )

                page.select_option('select[name="media_type"]', "music")
                page.wait_for_timeout(120)
                _expect(
                    dialog_messages, "Media switch should prompt warning-and-clear confirmation."
                )
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
                _expect(
                    music_providers == ["musicbrainz"],
                    f"Music providers mismatch: {music_providers}",
                )

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
                _expect(
                    page.is_visible('[data-imdb-field="true"]'),
                    "IMDb field should be visible for other.",
                )

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
                _expect(
                    checked_hidden == 0, "Switch should clear incompatible checked quality tokens."
                )

            run_check(
                "P5-01",
                "Phase 5",
                "Media-type switching enforces provider visibility and warning/clear behavior",
                check_phase5_media_behavior,
                page=page,
            )

            def check_phase5_rule_pattern_preview_parity() -> None:
                page.goto(
                    f"{app_base_url}/rules/new", wait_until="networkidle", timeout=args.timeout_ms
                )
                matching_section = page.locator("details:has(#pattern-preview)").first
                if not matching_section.evaluate("node => Boolean(node.open)"):
                    matching_section.locator("summary").click()
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

            def check_phase5_edit_rule_preserves_e00_floor() -> None:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import Session

                from app.models import MediaType, QualityProfile, Rule

                engine = create_engine(
                    f"sqlite:///{db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30},
                    future=True,
                )
                try:
                    with Session(engine) as session:
                        rule = Rule(
                            rule_name="QA E00 Floor Rule",
                            content_name="QA E00 Floor Rule",
                            normalized_title="QA E00 Floor Rule",
                            media_type=MediaType.SERIES,
                            quality_profile=QualityProfile.PLAIN,
                            start_season=2,
                            start_episode=0,
                            feed_urls=[DEFAULT_FEEDS[0]],
                            enabled=True,
                        )
                        session.add(rule)
                        session.commit()
                        rule_id = rule.id
                finally:
                    engine.dispose()

                page.goto(
                    f"{app_base_url}/rules/{rule_id}",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector('input[name="start_episode"]', timeout=args.timeout_ms)
                matching_section = page.locator("details:has(#pattern-preview)").first
                if not matching_section.evaluate("node => Boolean(node.open)"):
                    matching_section.locator("summary").click()
                start_episode_value = page.input_value('input[name="start_episode"]')
                preview = page.input_value("#pattern-preview")
                helper_text = page.locator('input[name="start_episode"]').locator("xpath=..").text_content()
                _expect(
                    start_episode_value == "0",
                    (
                        "Expected season-finale rules to keep the next-season E00 floor visible "
                        f"on the edit form; current={start_episode_value!r}."
                    ),
                )
                _expect(
                    bool(preview.strip()),
                    (
                        "Expected the generated pattern preview to stay populated for "
                        f"season-finale rules; preview={preview!r}."
                    ),
                )
                _expect(
                    helper_text is not None and "E00" in helper_text,
                    (
                        "Expected the start-episode helper text to keep the E00 guidance visible "
                        f"for season-finale rules; helper={helper_text!r}."
                    ),
                )

            run_check(
                "P5-03",
                "Phase 5",
                "Edit rule form preserves next-season E00 floors for season-finale rules",
                check_phase5_edit_rule_preserves_e00_floor,
                page=page,
            )

            def check_phase18_filter_profile_selection_updates_immediately() -> None:
                page.goto(
                    f"{app_base_url}/rules/new", wait_until="networkidle", timeout=args.timeout_ms
                )
                matching_section = page.locator("details:has-text('Matching And Quality')").first
                if not matching_section.evaluate("node => Boolean(node.open)"):
                    matching_section.locator("summary").click()
                page.wait_for_selector('select[name="filter_profile_key"]', timeout=args.timeout_ms)
                page.wait_for_selector("#pattern-preview", timeout=args.timeout_ms)
                profile_select = page.locator('select[name="filter_profile_key"]').first
                preview = page.locator("#pattern-preview").first
                quality_profile_input = page.locator('input[name="quality_profile"]').first
                initial_preview = preview.input_value()
                initial_quality_profile = quality_profile_input.input_value()
                target_profile = profile_select.evaluate(
                    """
                    (node) => {
                      const form = node.form;
                      const visibleKeys = Array.from(node.options).map((option) => option.value).filter(Boolean);
                      const profiles = JSON.parse(form.dataset.availableFilterProfiles || "[]");
                      const currentKey = node.value || "";
                      const currentQualityProfile = form.querySelector('input[name="quality_profile"]').value || "";
                      return profiles.find((profile) => (
                        visibleKeys.includes(profile.key)
                        && profile.key !== currentKey
                        && profile.quality_profile_value
                        && profile.quality_profile_value !== "custom"
                        && profile.quality_profile_value !== currentQualityProfile
                      )) || null;
                    }
                    """
                )
                _expect(
                    target_profile is not None,
                    "Expected at least one alternate visible filter profile.",
                )
                page.select_option('select[name="filter_profile_key"]', target_profile["key"])
                page.wait_for_function(
                    """
                    (expected) => {
                      const qualityProfile = document.querySelector('input[name="quality_profile"]');
                      return qualityProfile && qualityProfile.value === expected;
                    }
                    """,
                    arg=target_profile["quality_profile_value"],
                    timeout=args.timeout_ms,
                )
                updated_preview = preview.input_value()
                updated_quality_profile = quality_profile_input.input_value()
                _expect(
                    updated_quality_profile == target_profile["quality_profile_value"],
                    (
                        "Filter profile input should update immediately after the select changes; "
                        f"initial={initial_quality_profile!r} target={target_profile['quality_profile_value']!r} "
                        f"current={updated_quality_profile!r}"
                    ),
                )
                _expect(
                    updated_preview != initial_preview,
                    (
                        "Pattern preview should change immediately after filter profile selection; "
                        f"preview={updated_preview!r}"
                    ),
                )
                _expect(
                    target_profile["quality_profile_value"] in updated_preview,
                    (
                        "Updated preview should reflect the new filter profile's quality floor; "
                        f"preview={updated_preview!r}"
                    ),
                )

            run_check(
                "P18-01",
                "Phase 18",
                "Rule filter profile selection updates derived quality state immediately",
                check_phase18_filter_profile_selection_updates_immediately,
                page=page,
            )

            def check_phase19_inline_search_filter_profile_selection_updates_results_immediately() -> (
                None
            ):
                from sqlalchemy import create_engine, select
                from sqlalchemy.orm import Session

                from app.models import Rule

                target_profile_key = "qa-no-match-profile"
                engine = create_engine(
                    f"sqlite:///{db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30},
                    future=True,
                )
                try:
                    with Session(engine) as session:
                        rule_id = str(
                            session.scalar(
                                select(Rule.id).where(
                                    Rule.rule_name == "QA P19 Inline Search Profile"
                                )
                            )
                            or ""
                        )
                finally:
                    engine.dispose()
                _expect(bool(rule_id), "Expected the pre-seeded QA P19 inline-search rule to exist.")

                page.goto(
                    f"{app_base_url}/rules/{rule_id}/search",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector("[data-search-page]", timeout=args.timeout_ms)
                page.wait_for_selector('select[name="filter_profile_key"]', timeout=args.timeout_ms)
                page.wait_for_selector("[data-search-filtered-count]", timeout=args.timeout_ms)

                def total_inline_filtered_count() -> int:
                    return int(
                        page.evaluate(
                            """
                            () => Array
                              .from(document.querySelectorAll('[data-search-filtered-count]'))
                              .reduce((total, node) => {
                                const value = Number.parseInt((node.textContent || '0').trim(), 10);
                                return total + (Number.isFinite(value) ? value : 0);
                              }, 0)
                            """
                        )
                    )

                initial_count = total_inline_filtered_count()
                _expect(
                    initial_count > 0,
                    f"Expected inline search results before applying the QA profile; count={initial_count}.",
                )

                quality_profile_input = page.locator('input[name="quality_profile"]').first
                page.select_option('select[name="filter_profile_key"]', target_profile_key)

                page.wait_for_function(
                    """
                    () => {
                      const count = Array
                        .from(document.querySelectorAll('[data-search-filtered-count]'))
                        .reduce((total, node) => total + (Number.parseInt((node.textContent || '0').trim(), 10) || 0), 0);
                      return count === 0;
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                updated_count = total_inline_filtered_count()
                updated_quality_profile = quality_profile_input.input_value()

                _expect(
                    updated_count == 0,
                    f"Expected the QA no-match profile to hide all inline search results immediately; count={updated_count}.",
                )
                _expect(
                    updated_quality_profile == "custom",
                    (
                        "Inline search should update the derived quality profile immediately after selecting the QA profile; "
                        f"current={updated_quality_profile!r}"
                    ),
                )

            run_check(
                "P19-01",
                "Phase 19",
                "Inline search results re-filter immediately after choosing a filter profile",
                check_phase19_inline_search_filter_profile_selection_updates_results_immediately,
                page=page,
            )

            def check_phase19_static_asset_version_refreshes_on_file_change() -> None:
                app_js_path = project_dir / "app" / "static" / "app.js"
                original_stat = app_js_path.stat()

                def asset_script_src() -> str:
                    page.goto(
                        f"{app_base_url}/rules/new",
                        wait_until="networkidle",
                        timeout=args.timeout_ms,
                    )
                    page.wait_for_selector(
                        'script[src*="app.js"]', state="attached", timeout=args.timeout_ms
                    )
                    src = page.locator('script[src*="app.js"]').first.get_attribute("src")
                    _expect(
                        bool(src),
                        "Expected the app.js asset URL to be present in the rendered page.",
                    )
                    return str(src)

                initial_src = asset_script_src()
                bumped_mtime_ns = max(original_stat.st_mtime_ns, time.time_ns()) + 1_000_000_000
                os.utime(app_js_path, ns=(original_stat.st_atime_ns, bumped_mtime_ns))
                try:
                    updated_src = asset_script_src()
                finally:
                    os.utime(app_js_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

                _expect(
                    initial_src != updated_src,
                    (
                        "Expected the rendered frontend asset URL to change after the app.js timestamp changed; "
                        f"initial={initial_src!r} updated={updated_src!r}"
                    ),
                )
                _expect(
                    "v=" in updated_src,
                    f"Expected the updated asset URL to include a cache-busting version token; src={updated_src!r}",
                )

            run_check(
                "P19-02",
                "Phase 19",
                "Frontend asset URLs refresh when local static files change",
                check_phase19_static_asset_version_refreshes_on_file_change,
                page=page,
            )

            def check_phase23_precise_results_matrix_and_rules_page_filter_memory() -> None:
                from sqlalchemy import create_engine, select
                from sqlalchemy.orm import Session

                from app.models import Rule

                target_names = [
                    "QA P23 Series Exact",
                    "QA P23 Series Special Exact",
                    "QA P23 Movie Exact",
                    "QA P23 Movie Direct Exact",
                    "QA P23 Movie BDRip Exact",
                ]
                engine = create_engine(
                    f"sqlite:///{db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30},
                    future=True,
                )
                try:
                    with Session(engine) as session:
                        rows = session.execute(
                            select(Rule.rule_name, Rule.id).where(Rule.rule_name.in_(target_names))
                        ).all()
                finally:
                    engine.dispose()
                rule_ids = {str(rule_name): str(rule_id) for rule_name, rule_id in rows}
                _expect(
                    set(rule_ids) == set(target_names),
                    f"Expected seeded phase-23 QA rules; found={sorted(rule_ids)}.",
                )

                page.goto(
                    f"{app_base_url}/rules/{rule_ids['QA P23 Series Exact']}?run_search=1#inline-search-results",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                series_precise_titles = search_visible_titles("primary")
                series_fallback_titles = search_visible_titles("fallback")
                normalized_series_precise_titles = [title.casefold() for title in series_precise_titles]
                _expect(
                    len(series_precise_titles) >= 2,
                    (
                        "Expected multiple visible precise series rows for the QA phase-23 series rule; "
                        f"titles={series_precise_titles}"
                    ),
                )
                _expect(
                    any("young sherlock" in title for title in normalized_series_precise_titles),
                    (
                        "Expected at least one visible precise series row to keep the searched title text; "
                        f"titles={series_precise_titles}"
                    ),
                )
                _expect(
                    all(
                        "hdrezka" not in title
                        and "documentary" not in title
                        and "test cut" not in title
                        and " ts " not in f" {title} "
                        for title in normalized_series_precise_titles
                    ),
                    (
                        "Expected precise series rows to reject fallback-only title refinements and obvious "
                        "non-precise variants; "
                        f"titles={series_precise_titles}"
                    ),
                )
                _expect(
                    len(series_fallback_titles) == 1
                    and "test cut" in series_fallback_titles[0].casefold(),
                    (
                        "Expected one visible title-fallback row narrowed by the fallback-only text filter; "
                        f"titles={series_fallback_titles}"
                    ),
                )

                page.goto(
                    f"{app_base_url}/rules/{rule_ids['QA P23 Series Special Exact']}?run_search=1#inline-search-results",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                series_special_titles = search_visible_titles("primary")
                _expect(
                    any("Ghosts 2019" in title for title in series_special_titles),
                    f"Expected the Ghosts GB rule to keep the correct precise special row; titles={series_special_titles}",
                )
                _expect(
                    all("Ghosts US" not in title for title in series_special_titles),
                    (
                        "Expected precise title identity to reject the wrong same-title franchise row; "
                        f"titles={series_special_titles}"
                    ),
                )

                page.goto(
                    f"{app_base_url}/rules/{rule_ids['QA P23 Movie Exact']}?run_search=1#inline-search-results",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                movie_exact_titles = search_visible_titles("primary")
                _expect(
                    len(movie_exact_titles) >= 1,
                    f"Expected visible precise movie rows for Knives Out; titles={movie_exact_titles}",
                )
                _expect(
                    all("Mystery" not in title for title in movie_exact_titles),
                    (
                        "Expected precise movie rows to reject franchise-subtitle false positives; "
                        f"titles={movie_exact_titles}"
                    ),
                )

                page.goto(
                    f"{app_base_url}/rules/{rule_ids['QA P23 Movie Direct Exact']}?run_search=1#inline-search-results",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                movie_direct_titles = search_visible_titles("primary")
                _expect(
                    len(movie_direct_titles) >= 1,
                    f"Expected visible precise movie rows for The Creator; titles={movie_direct_titles}",
                )

                page.goto(
                    f"{app_base_url}/rules/{rule_ids['QA P23 Movie BDRip Exact']}?run_search=1#inline-search-results",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                movie_bdrip_titles = search_visible_titles("primary")
                _expect(
                    any("What Lies Beneath" in title for title in movie_bdrip_titles),
                    (
                        "Expected the precise movie lane to keep the BDRip row when only bluray and "
                        f"bdremux are excluded; titles={movie_bdrip_titles}"
                    ),
                )
                _expect(
                    any("BDRip" in title for title in movie_bdrip_titles),
                    (
                        "Expected the visible precise movie row to preserve the BDRip source label "
                        f"for the taxonomy split check; titles={movie_bdrip_titles}"
                    ),
                )

                try:
                    page.goto(
                        f"{app_base_url}/",
                        wait_until="commit",
                        timeout=args.timeout_ms,
                    )
                except playwright_sync_api.TimeoutError:
                    pass
                page.goto(
                    (
                        f"{app_base_url}/?search=QA+P23&media=&sync=&enabled=&release=&exact=exact"
                        "&sort=updated_at&direction=desc&view=table"
                    ),
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector("[data-rules-filter-form]", timeout=args.timeout_ms)
                page.wait_for_selector("[data-rules-row]", timeout=args.timeout_ms)
                page.wait_for_function(
                    """
                    () => {
                      const form = document.querySelector('[data-rules-filter-form]');
                      const search = form?.querySelector('input[name="search"]');
                      const exact = form?.querySelector('select[name="exact"]');
                      return Boolean(search && exact && search.value === 'QA P23' && exact.value === 'exact');
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                filtered_rule_names = page.eval_on_selector_all(
                    "[data-rules-row]",
                    "rows => rows.map((row) => row.dataset.ruleName || '').filter(Boolean)",
                )
                _expect(
                    set(filtered_rule_names) == set(target_names),
                    (
                        "Expected the rules-page exact filter to keep only the seeded exact QA rules; "
                        f"names={filtered_rule_names}"
                    ),
                )
                _expect(
                    page.locator("text=Exact found").count() >= len(target_names),
                    "Expected the rules table to show Exact found chips for the seeded QA rules.",
                )

                try:
                    page.goto(
                        f"{app_base_url}/rules/new",
                        wait_until="commit",
                        timeout=args.timeout_ms,
                    )
                except playwright_sync_api.TimeoutError:
                    pass
                page.wait_for_selector("[data-rule-form]", timeout=args.timeout_ms)
                try:
                    page.goto(
                        f"{app_base_url}/",
                        wait_until="commit",
                        timeout=args.timeout_ms,
                    )
                except playwright_sync_api.TimeoutError:
                    pass
                page.wait_for_selector("[data-rules-filter-form]", timeout=args.timeout_ms)
                page.wait_for_function(
                    """
                    () => {
                      const form = document.querySelector('[data-rules-filter-form]');
                      const search = form?.querySelector('input[name="search"]');
                      const exact = form?.querySelector('select[name="exact"]');
                      return Boolean(search && exact && search.value === 'QA P23' && exact.value === 'exact');
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                restored_rule_names = page.eval_on_selector_all(
                    "[data-rules-row]",
                    "rows => rows.map((row) => row.dataset.ruleName || '').filter(Boolean)",
                )
                _expect(
                    set(restored_rule_names) == set(target_names),
                    (
                        "Expected the rules-page filter state to restore from local memory on revisit; "
                        f"names={restored_rule_names}"
                    ),
                )

            run_check(
                "P23-01",
                "Phase 23",
                "Precise movie/series rules stay exact, fallback stays separate, and rules-page exact filters restore",
                check_phase23_precise_results_matrix_and_rules_page_filter_memory,
                page=page,
            )

            search_url = (
                f"{app_base_url}/search?query=Young+Sherlock&media_type=series&indexer=all"
                "&imdb_id=tt8599532&include_release_year=on&release_year=2026"
                "&additional_includes=Young+Sherlock"
                "&quality_include_tokens=2160p&quality_include_tokens=hdr"
            )

            def check_phase6_controls() -> None:
                page.goto(search_url, wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector("[data-search-controls]", timeout=args.timeout_ms)
                controls = page.locator("[data-search-controls]")
                _expect(
                    controls.count() == 1,
                    "Expected one compact result-view panel for unified results.",
                )
                _expect(
                    controls.first.locator("[data-search-view-mode]").count() == 0,
                    "Search panel should stay table-only in compact mode.",
                )
                _expect(
                    page.locator('[data-search-table-wrap="combined"]').first.evaluate(
                        "node => !node.hidden"
                    ),
                    "Table view should be visible by default.",
                )
                _expect(
                    page.locator('[data-search-results="combined"]').first.evaluate(
                        "node => Boolean(node.hidden)"
                    ),
                    "Card container should remain hidden in table-only mode.",
                )

                title_sort = page.locator('[data-search-table-sort-field="title"]').first
                title_sort.click()
                page.wait_for_timeout(140)
                asc_pairs = search_visible_title_source_pairs("combined")
                asc_titles = [title for title, _source in asc_pairs]
                if len(asc_pairs) >= 2:
                    _expect(
                        asc_pairs == _sorted_combined_title_pairs(asc_pairs, reverse=False),
                        f"Expected ascending title sort from header click; titles={asc_titles}.",
                    )
                title_sort.click()
                page.wait_for_timeout(140)
                desc_pairs = search_visible_title_source_pairs("combined")
                desc_titles = [title for title, _source in desc_pairs]
                if len(desc_pairs) >= 2:
                    _expect(
                        desc_pairs == _sorted_combined_title_pairs(desc_pairs, reverse=True),
                        f"Expected descending title sort after second header click; titles={desc_titles}.",
                    )

                controls.first.locator("[data-search-save-defaults]").click()
                page.wait_for_function(
                    """
                    () => {
                      const node = document.querySelector('[data-search-default-status]');
                      return Boolean(node && (node.textContent || '').includes('Saved.'));
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                statuses = [
                    controls.first.locator("[data-search-default-status]").inner_text().strip()
                ]
                _expect(
                    all("Saved." in status for status in statuses),
                    f"Unexpected save-default statuses: {statuses}",
                )

            run_check(
                "P6-01",
                "Phase 6",
                "Unified result-view panel stays table-only while preserving header sort and defaults save",
                check_phase6_controls,
                page=page,
            )

            def check_phase6_local_filters() -> None:
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
                primary_after_any = search_filtered_count("primary")
                fallback_after_any = search_filtered_count("fallback")
                _expect(
                    primary_after_any >= 1,
                    f"Expected at least one primary result after grouped any-of; got {primary_after_any}",
                )
                _expect(
                    fallback_after_any >= 1,
                    f"Expected at least one fallback result after grouped any-of; got {fallback_after_any}",
                )

                page.fill('textarea[name="must_not_contain"]', "ts")
                page.wait_for_timeout(180)
                fallback_after_ts = search_filtered_count("fallback")
                _expect(
                    fallback_after_ts <= fallback_after_any,
                    (
                        "Expected excluded short token to not increase fallback matches; "
                        f"before={fallback_after_any} after={fallback_after_ts}."
                    ),
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
                page.wait_for_selector(
                    '[data-search-filtered-count="combined"]', timeout=args.timeout_ms
                )

                baseline_requests = request_count()
                baseline_fallback = search_filtered_count("fallback")
                _expect(
                    baseline_fallback >= 1,
                    (
                        "Expected at least one fallback result with release-year filter enabled; "
                        f"got {baseline_fallback}"
                    ),
                )
                page.uncheck("input[data-search-include-year]")
                page.wait_for_timeout(200)
                _expect(
                    page.is_disabled("input[data-search-release-year]"),
                    "Release-year field should be disabled when toggle is unchecked.",
                )
                fallback_without_year = search_filtered_count("fallback")
                _expect(
                    fallback_without_year >= baseline_fallback,
                    (
                        "Expected fallback results to stay the same or expand when release-year filter is off; "
                        f"before={baseline_fallback} after={fallback_without_year}."
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
                page.wait_for_selector(
                    '[data-search-filtered-count="combined"]', timeout=args.timeout_ms
                )
                baseline_requests = request_count()
                baseline_fallback_count = search_filtered_count("fallback")

                token_slider = page.locator(
                    '[data-search-quality-option="true"][data-quality-token="cam"] [data-quality-token-slider-control]'
                )
                _expect(token_slider.count() == 1, "Expected cam quality token slider on /search.")
                pattern_preview = page.locator("#search-pattern-preview")
                _expect(
                    pattern_preview.count() == 1,
                    "Expected generated pattern preview textarea on /search.",
                )

                # Regression guard: include slider must override conflicting manual excluded text terms.
                page.fill('textarea[name="additional_includes"]', "young sherlock")
                page.wait_for_timeout(220)
                fallback_with_include_phrase = search_filtered_count("fallback")
                _expect(
                    fallback_with_include_phrase <= baseline_fallback_count,
                    (
                        "Expected adding an explicit include phrase to not increase fallback count "
                        f"(baseline={baseline_fallback_count}, now={fallback_with_include_phrase})."
                    ),
                )
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
                fallback_after_cam_excluded = search_filtered_count("fallback")
                _expect(
                    fallback_after_cam_excluded <= baseline_fallback_count,
                    (
                        "Expected manual excluded keyword cam to not increase fallback count "
                        f"(baseline={baseline_fallback_count}, now={fallback_after_cam_excluded})."
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
                fallback_with_cam_include = search_filtered_count("fallback")
                _expect(
                    search_filtered_count("combined") >= 1,
                    (
                        "Expected cam Include slider to keep the local result set usable after removing the "
                        "conflicting manual cam exclusion; "
                        f"fallback={fallback_with_cam_include} combined={search_filtered_count('combined')}."
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
                    search_filtered_count("fallback") == fallback_with_include_phrase,
                    (
                        "Expected clearing excluded keywords and resetting slider to Off to restore the "
                        "explicit include-phrase fallback count "
                        f"{fallback_with_include_phrase}; got {search_filtered_count('fallback')}."
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
                fallback_with_cam_out = search_filtered_count("fallback")
                _expect(
                    fallback_with_cam_out <= baseline_fallback_count,
                    (
                        "Expected quality Out toggle to not increase fallback count "
                        f"(baseline={baseline_fallback_count}, now={fallback_with_cam_out})."
                    ),
                )
                token_slider.first.press("Home")
                page.fill('textarea[name="additional_includes"]', "")
                wait_for_filtered_count("fallback", baseline_fallback_count)
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
                _expect(
                    delta_indexer_option.count() == 1,
                    "Expected delta indexer option in indexer multiselect.",
                )
                delta_indexer_option.check()
                page.wait_for_function(
                    """
                    () => {
                      const input = document.querySelector('input[data-search-multiselect-storage="indexers"]');
                      return Boolean(input && (input.value || "").toLowerCase().includes("delta"));
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                wait_for_filtered_count("combined", 1)
                _expect(
                    search_filtered_count("combined") == 1,
                    (
                        "Expected exactly one visible combined row for delta indexer after local filtering; "
                        f"got {search_filtered_count('combined')}."
                    ),
                )
                delta_titles = search_visible_titles("combined")
                _expect(
                    len(delta_titles) == 1 and " TS " in f" {delta_titles[0]} ",
                    f"Expected delta indexer filter to keep the TS row only; titles={delta_titles}",
                )
                delta_indexer_option.uncheck()
                page.wait_for_function(
                    """
                    () => {
                      const input = document.querySelector('input[data-search-multiselect-storage="indexers"]');
                      return Boolean(input) && !(input.value || "").toLowerCase().includes("delta");
                    }
                    """,
                    timeout=args.timeout_ms,
                )
                wait_for_filtered_count("fallback", baseline_fallback_count)

                page.click('[data-search-multiselect-summary="categories"]')
                documentary_category_option = page.locator(
                    '[data-search-multiselect-options="categories"] label:has-text("TV/Documentary") input[type="checkbox"]'
                )
                if documentary_category_option.count() == 0:
                    documentary_category_option = page.locator(
                        '[data-search-multiselect-options="categories"] label:has-text("Documentary") input[type="checkbox"]'
                    )
                _expect(
                    documentary_category_option.count() >= 1,
                    "Expected a Documentary category option in category multiselect.",
                )
                documentary_category_option.first.check()
                page.wait_for_timeout(220)
                _expect(
                    search_filtered_count("fallback") == 1,
                    (
                        "Expected category dropdown Documentary filter to keep one fallback row; "
                        f"got {search_filtered_count('fallback')}."
                    ),
                )
                documentary_titles = search_visible_titles("fallback")
                _expect(
                    len(documentary_titles) == 1 and "Test Cut" in documentary_titles[0],
                    f"Expected Documentary filter to keep Test Cut only; titles={documentary_titles}",
                )
                page.fill('input[name="keywords_any"]', "cam")
                page.wait_for_timeout(220)
                category_scope_status = (
                    page.text_content("[data-search-category-scope-status]") or ""
                )
                _expect(
                    "currently have no cached matches" in category_scope_status,
                    (
                        "Expected stale category scope warning when selected category has no matches "
                        f"under other filters; status={category_scope_status!r}."
                    ),
                )
                _expect(
                    search_filtered_count("fallback") == 0,
                    (
                        "Expected stale category + keyword combination to yield zero fallback rows; "
                        f"got {search_filtered_count('fallback')}."
                    ),
                )
                page.fill('input[name="keywords_any"]', "")
                page.wait_for_timeout(220)
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
                page.wait_for_selector('[data-search-summary="combined"]', timeout=args.timeout_ms)
                page.fill('input[name="keywords_any"]', "2160p | hdr10")
                page.wait_for_timeout(180)
                filter_impact_count = page.eval_on_selector_all(
                    "[data-filter-impact-list] li",
                    "els => els.length",
                )
                _expect(
                    filter_impact_count == 0,
                    "Standalone filter-impact panels should not render in unified flow.",
                )
                active_filter_chips = page.eval_on_selector_all(
                    "[data-search-active-filter-list] .search-active-filter-chip",
                    "els => els.length",
                )
                _expect(
                    active_filter_chips >= 1,
                    "Expected active local-filter chips to appear after applying filters.",
                )
                page.click("[data-search-clear-filters]")
                page.wait_for_timeout(180)
                _expect(
                    page.eval_on_selector_all(
                        "[data-search-active-filter-list] .search-active-filter-chip",
                        "els => els.length",
                    )
                    == 0,
                    "Clear local filters should remove active-filter chips.",
                )

                page.fill('textarea[name="must_not_contain"]', "")
                page.wait_for_timeout(120)
                use_link = page.locator(
                    '[data-search-row="combined"]:not([hidden]) a.button-link:has-text("Use In New Rule")'
                ).first
                _expect(
                    use_link.count() == 1,
                    "Expected a visible Use In New Rule link in unified results.",
                )
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
                matching_section = page.locator("details:has-text('Matching And Quality')").first
                if not matching_section.evaluate("node => Boolean(node.open)"):
                    matching_section.locator("summary").click()
                # Keep downstream inline-search assertions deterministic by clearing
                # prefilled exclusions from handoff query state, while preserving the
                # broad-only include term so fallback rows remain available for the
                # inline local-recompute checks.
                page.fill('textarea[name="must_not_contain"]', "")
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
                _expect(
                    "/rules/" in current_url,
                    f"Expected redirect to created rule page, got {current_url}",
                )
                run_search_here = page.locator('a.button-link:has-text("Run Search Here")').first
                _expect(
                    run_search_here.count() == 1,
                    "Expected Run Search Here action on the rule page.",
                )
                run_search_here.click()
                page.wait_for_url(
                    re.compile(r".*/rules/[^/?#]+\?.*run_search=1.*"),
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                page_text = page.content()
                _expect(
                    "Results on this page" in page_text,
                    "Rule-derived run should render inline results on the rule page.",
                )
                _expect(
                    "Precise results" in page_text,
                    "Rule-derived movie/series search should use precise-result labeling.",
                )
                advanced_link = page.locator(
                    '#inline-search-results a.button-link:has-text("Open Advanced Search Workspace")'
                ).first
                _expect(
                    advanced_link.count() == 1,
                    "Inline results section should expose Advanced Search workspace link.",
                )
                advanced_href = advanced_link.get_attribute("href") or ""
                _expect(
                    advanced_href.startswith("/search?rule_id="),
                    f"Unexpected advanced workspace href: {advanced_href}",
                )
                phase7_context["inline_rule_url"] = page.url

            run_check(
                "P6-05",
                "Phase 6",
                "Unified results UX, search-to-rule handoff, and rule-derived search flow",
                check_phase6_filter_impact_and_handoff,
                page=page,
            )

            def check_phase7_inline_pattern_local_recompute() -> None:
                inline_rule_url = phase7_context.get("inline_rule_url")
                _expect(
                    bool(inline_rule_url),
                    "Missing inline rule URL context from P6-05 handoff check.",
                )
                page.goto(str(inline_rule_url), wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                reset_inline_local_filters_for_visibility()
                baseline_requests = request_count()
                active_section = "combined"
                baseline_primary = search_filtered_count(active_section)
                baseline_fallback = search_filtered_count("fallback")
                _expect(
                    baseline_primary >= 1,
                    (
                        "Expected inline results before generated-pattern recompute check; "
                        f"section={active_section} count={baseline_primary}; "
                        f"fetched_primary={search_fetched_count('primary')} "
                        f"fetched_fallback={search_fetched_count('fallback')}."
                    ),
                )
                _expect(
                    baseline_fallback >= 1,
                    (
                        "Expected inline fallback rows before generated-pattern recompute check so "
                        "mustNotContain can exercise the fallback-only local filter lane; "
                        f"fallback={baseline_fallback}."
                    ),
                )
                page.fill('textarea[name="must_not_contain"]', "young sherlock")
                page.wait_for_timeout(260)
                _expect(
                    search_filtered_count(active_section) < baseline_primary,
                    (
                        "Expected generated-pattern mustNotContain edit to locally reduce visible inline rows; "
                        f"section={active_section} baseline={baseline_primary} now={search_filtered_count(active_section)}."
                    ),
                )
                _expect(
                    request_count() == baseline_requests,
                    (
                        "Inline generated-pattern recompute should be network-free. "
                        f"before={baseline_requests} after={request_count()}"
                    ),
                )
                page.fill('textarea[name="must_not_contain"]', "")
                page.wait_for_timeout(240)
                _expect(
                    search_filtered_count(active_section) >= 1,
                    "Expected inline results to return after clearing generated-pattern exclusion.",
                )

            run_check(
                "P7-10",
                "Phase 7",
                "Inline generated-pattern edits recompute cached results without remote requests",
                check_phase7_inline_pattern_local_recompute,
                page=page,
            )

            def check_phase7_inline_queue_paused_semantics() -> None:
                inline_rule_url = phase7_context.get("inline_rule_url")
                _expect(
                    bool(inline_rule_url),
                    "Missing inline rule URL context from P6-05 handoff check.",
                )
                page.goto(str(inline_rule_url), wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                reset_inline_local_filters_for_visibility()
                queue_buttons = page.locator(
                    "#inline-search-results "
                    '[data-search-row="combined"]:not([hidden]) [data-result-queue-button]'
                )
                _expect(
                    queue_buttons.count() >= 1,
                    (
                        "Expected a visible inline queue button. "
                        f"fetched_primary={search_fetched_count('primary')} "
                        f"fetched_fallback={search_fetched_count('fallback')} "
                        f"filtered_primary={search_filtered_count('primary')} "
                        f"filtered_fallback={search_filtered_count('fallback')}"
                    ),
                )
                queue_button = queue_buttons.first
                paused_toggle = page.locator(
                    '#inline-search-results input[data-result-queue-option="paused"]'
                ).first
                _expect(paused_toggle.count() == 1, "Expected inline Add paused toggle.")

                if paused_toggle.is_checked():
                    paused_toggle.uncheck()
                add_call_start = len(qb_state.torrent_add_calls)
                queue_button.click()
                wait_for_torrent_add_calls(add_call_start + 1)
                latest_unpaused = qb_state.torrent_add_calls[-1]
                _expect(
                    latest_unpaused.get("paused") == "false"
                    and latest_unpaused.get("stopped") == "false",
                    (
                        "Expected unchecked Add paused to send paused=false and stopped=false; "
                        f"payload={latest_unpaused}"
                    ),
                )

                paused_toggle.check()
                add_call_start = len(qb_state.torrent_add_calls)
                queue_button.click()
                wait_for_torrent_add_calls(add_call_start + 1)
                latest_paused = qb_state.torrent_add_calls[-1]
                _expect(
                    latest_paused.get("paused") == "true"
                    and latest_paused.get("stopped") == "true",
                    (
                        "Expected checked Add paused to send paused=true and stopped=true; "
                        f"payload={latest_paused}"
                    ),
                )

            run_check(
                "P7-11",
                "Phase 7",
                "Inline queue actions propagate Add paused semantics to qB payload flags",
                check_phase7_inline_queue_paused_semantics,
                page=page,
            )

            def check_phase7_inline_table_sort_parity() -> None:
                inline_rule_url = phase7_context.get("inline_rule_url")
                _expect(
                    bool(inline_rule_url),
                    "Missing inline rule URL context from P6-05 handoff check.",
                )
                page.goto(str(inline_rule_url), wait_until="networkidle", timeout=args.timeout_ms)
                page.wait_for_selector(
                    '#inline-search-results [data-search-summary="combined"]',
                    timeout=args.timeout_ms,
                )
                reset_inline_local_filters_for_visibility()
                section = "combined"
                section_titles = search_visible_titles(section)
                _expect(
                    len(section_titles) >= 1,
                    (
                        "Expected at least one visible inline row for sort parity check; "
                        f"combined={section_titles}."
                    ),
                )

                table_wrap = page.locator(
                    f'#inline-search-results [data-search-table-wrap="{section}"]'
                ).first
                _expect(table_wrap.count() == 1, f"Expected inline {section} table wrapper.")
                _expect(
                    not table_wrap.evaluate("node => node.hidden"),
                    "Inline results should default to table view.",
                )
                card_wrap = page.locator(
                    f'#inline-search-results [data-search-results="{section}"]'
                ).first
                _expect(
                    card_wrap.evaluate("node => node.hidden"),
                    "Inline card view should be hidden when table view is defaulted.",
                )

                sort_controls = page.locator("#inline-search-results [data-search-controls]").first
                _expect(sort_controls.count() == 1, "Expected inline sort controls.")
                baseline_requests = request_count()
                page.locator(
                    '#inline-search-results [data-search-table-sort-field="title"]'
                ).first.click()
                page.wait_for_timeout(220)
                asc_pairs = search_visible_title_source_pairs(section)
                asc_titles = [title for title, _source in asc_pairs]
                if len(asc_pairs) >= 2:
                    _expect(
                        asc_pairs == _sorted_combined_title_pairs(asc_pairs, reverse=False),
                        f"Expected inline {section} titles sorted ascending by title; titles={asc_titles}.",
                    )
                page.locator(
                    '#inline-search-results [data-search-table-sort-field="title"]'
                ).first.click()
                page.wait_for_timeout(220)
                desc_pairs = search_visible_title_source_pairs(section)
                desc_titles = [title for title, _source in desc_pairs]
                if len(desc_pairs) >= 2:
                    _expect(
                        desc_pairs == _sorted_combined_title_pairs(desc_pairs, reverse=True),
                        f"Expected inline {section} titles sorted descending by title; titles={desc_titles}.",
                    )
                _expect(
                    request_count() == baseline_requests,
                    (
                        "Inline sort/view toggles should be local-only. "
                        f"before={baseline_requests} after={request_count()}"
                    ),
                )

            run_check(
                "P7-12",
                "Phase 7",
                "Inline rule-page results default to table view and keep local sort parity",
                check_phase7_inline_table_sort_parity,
                page=page,
            )

            def check_phase6_non_latin() -> None:
                page.goto(
                    f"{app_base_url}/search?query=%D0%9F%D0%B5%D0%BB%D0%B5%D0%B2%D0%B8%D0%BD&media_type=audiobook&indexer=all",
                    wait_until="networkidle",
                    timeout=args.timeout_ms,
                )
                page.wait_for_selector('[data-search-summary="combined"]', timeout=args.timeout_ms)
                _expect(
                    search_filtered_count("combined") >= 1,
                    (
                        "Expected non-Latin query local matching to keep at least one relevant result; "
                        f"got {search_filtered_count('combined')}"
                    ),
                )
                visible_titles = search_visible_titles("combined")
                _expect(
                    any("Пелевин" in title for title in visible_titles),
                    f"Expected visible non-Latin title to include query term; titles={visible_titles}",
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
            if debug_log_before is None or debug_after is None:
                return
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
            "p9_hover_screenshots": p9_hover_artifacts,
            "p9_hover_manifest": p9_hover_manifest_path,
            "p9_hover_video": p9_hover_video_path,
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
        f"# Phase 4/5/6/7/9 Browser Closeout QA ({run_stamp})\n\n"
        f"- Total checks: **{len(checks)}**\n"
        f"- Passed: **{passed}**\n"
        f"- Failed: **{len(failures)}**\n"
        f"- App URL: `{app_base_url}`\n"
        f"- Mock qB URL: `{qb_base_url}`\n"
        f"- Mock Jackett URL: `{jackett_base_url}`\n"
        f"- Jackett requests observed: **{jackett_state.request_count}**\n\n"
    )
    artifact_lines: list[str] = []
    if p9_hover_artifacts or p9_hover_manifest_path or p9_hover_video_path:
        artifact_lines.extend(["## Hover Overlay Evidence", ""])
        if p9_hover_manifest_path:
            artifact_lines.append(f"- Manifest: `{p9_hover_manifest_path}`")
        for screenshot_path in p9_hover_artifacts:
            artifact_lines.append(f"- Screenshot: `{screenshot_path}`")
        if p9_hover_video_path:
            artifact_lines.append(f"- Video: `{p9_hover_video_path}`")
        artifact_lines.append("")
    report_md_path.write_text(
        headline + markdown_table(checks) + "\n\n" + "\n".join(artifact_lines),
        encoding="utf-8",
    )

    print(f"Saved closeout report: {report_json_path}")
    print(f"Saved closeout summary: {report_md_path}")
    if failures:
        print(f"{len(failures)} check(s) failed.", file=sys.stderr)
        return 1
    print("All browser closeout checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.db import get_session_factory
from app.models import AppSettings
from app.services.stremio_addon import StremioAddonService, reset_stremio_addon_caches

DEFAULT_ITEMS = (
    ("series", "tt33517752:1:1"),
    ("series", "tt33517752:1:4"),
)


@dataclass(slots=True)
class StreamProbeSummary:
    item_type: str
    item_id: str
    cold_ms: float
    warm_ms: float
    streams_count: int
    info_hashes: list[str]
    tags: list[str]
    has_4k: bool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test qB RSS Stremio addon responses without manual browser checks.",
    )
    parser.add_argument(
        "--mode",
        choices=("service", "http"),
        default="service",
        help="Exercise the addon directly in-process or via the live HTTP endpoint.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for HTTP mode.",
    )
    parser.add_argument(
        "--item",
        action="append",
        dest="items",
        help="Item in the form <type>:<id>. Can be repeated. Defaults to The Beauty episodes 1 and 4.",
    )
    parser.add_argument(
        "--min-streams",
        type=int,
        default=1,
        help="Minimum number of streams each item must return for the script to exit successfully.",
    )
    parser.add_argument(
        "--require-4k",
        action="store_true",
        help="Require each item to include at least one 2160p/4K-tagged stream.",
    )
    parser.add_argument(
        "--max-cold-ms",
        type=float,
        default=4000.0,
        help="Fail if a cold lookup exceeds this threshold in milliseconds.",
    )
    parser.add_argument(
        "--max-warm-ms",
        type=float,
        default=500.0,
        help="Fail if a warm lookup exceeds this threshold in milliseconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final report as JSON only.",
    )
    return parser.parse_args()


def _selected_items(raw_items: list[str] | None) -> list[tuple[str, str]]:
    if not raw_items:
        return list(DEFAULT_ITEMS)
    parsed_items: list[tuple[str, str]] = []
    for raw_item in raw_items:
        item_type, sep, item_id = str(raw_item or "").partition(":")
        if not sep or not item_type or not item_id:
            raise SystemExit(f"Invalid --item value: {raw_item!r}. Expected <type>:<id>.")
        parsed_items.append((item_type, item_id))
    return parsed_items


def _timed(func) -> tuple[float, Any]:
    started = time.perf_counter()
    payload = func()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return elapsed_ms, payload


def _service() -> StremioAddonService:
    session = get_session_factory()()
    try:
        settings = session.get(AppSettings, "default")
    finally:
        session.close()
    return StremioAddonService(settings)


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "stremio-addon-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - defensive
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc


def _stream_summary(
    item_type: str, item_id: str, cold_ms: float, warm_ms: float, payload: dict[str, Any]
) -> StreamProbeSummary:
    streams = list(payload.get("streams") or [])
    tags = [str(stream.get("tag") or "") for stream in streams]
    info_hashes = [
        str(stream.get("infoHash") or "") for stream in streams if stream.get("infoHash")
    ]
    has_4k = any(tag.casefold() in {"2160p", "4k"} for tag in tags)
    return StreamProbeSummary(
        item_type=item_type,
        item_id=item_id,
        cold_ms=cold_ms,
        warm_ms=warm_ms,
        streams_count=len(streams),
        info_hashes=info_hashes,
        tags=tags,
        has_4k=has_4k,
    )


def _probe_service_item(
    service: StremioAddonService,
    *,
    item_type: str,
    item_id: str,
    base_url: str,
) -> StreamProbeSummary:
    reset_stremio_addon_caches()
    cold_ms, cold_payload = _timed(
        lambda: service.stream_lookup(item_type=item_type, item_id=item_id, base_url=base_url)
    )
    warm_ms, warm_payload = _timed(
        lambda: service.stream_lookup(item_type=item_type, item_id=item_id, base_url=base_url)
    )
    if cold_payload != warm_payload:
        raise RuntimeError(f"Cold/warm payload mismatch for {item_type}:{item_id}")
    return _stream_summary(item_type, item_id, cold_ms, warm_ms, cold_payload)


def _probe_http_item(base_url: str, *, item_type: str, item_id: str) -> StreamProbeSummary:
    url = f"{base_url.rstrip('/')}/stremio/stream/{item_type}/{item_id}.json"
    cold_ms, cold_payload = _timed(lambda: _http_get_json(url))
    warm_ms, warm_payload = _timed(lambda: _http_get_json(url))
    if cold_payload != warm_payload:
        raise RuntimeError(f"Cold/warm payload mismatch for {item_type}:{item_id}")
    return _stream_summary(item_type, item_id, cold_ms, warm_ms, cold_payload)


def _probe_manifest_http(base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/stremio/manifest.json"
    return _http_get_json(url)


def _format_report(
    mode: str, manifest: dict[str, Any] | None, summaries: list[StreamProbeSummary]
) -> dict[str, Any]:
    return {
        "mode": mode,
        "manifest": manifest,
        "items": [asdict(summary) for summary in summaries],
    }


def _check_thresholds(
    summaries: list[StreamProbeSummary],
    *,
    min_streams: int,
    require_4k: bool,
    max_cold_ms: float,
    max_warm_ms: float,
) -> list[str]:
    failures: list[str] = []
    for summary in summaries:
        label = f"{summary.item_type}:{summary.item_id}"
        if summary.streams_count < min_streams:
            failures.append(f"{label} returned {summary.streams_count} streams (< {min_streams})")
        if require_4k and not summary.has_4k:
            failures.append(f"{label} did not include a 4K stream")
        if summary.cold_ms > max_cold_ms:
            failures.append(f"{label} cold lookup took {summary.cold_ms} ms (> {max_cold_ms} ms)")
        if summary.warm_ms > max_warm_ms:
            failures.append(f"{label} warm lookup took {summary.warm_ms} ms (> {max_warm_ms} ms)")
    return failures


def main() -> int:
    args = _parse_args()
    items = _selected_items(args.items)
    manifest: dict[str, Any] | None = None

    if args.mode == "service":
        service = _service()
        summaries = [
            _probe_service_item(
                service,
                item_type=item_type,
                item_id=item_id,
                base_url=args.base_url,
            )
            for item_type, item_id in items
        ]
    else:
        manifest = _probe_manifest_http(args.base_url)
        summaries = [
            _probe_http_item(args.base_url, item_type=item_type, item_id=item_id)
            for item_type, item_id in items
        ]

    report = _format_report(args.mode, manifest, summaries)
    failures = _check_thresholds(
        summaries,
        min_streams=args.min_streams,
        require_4k=args.require_4k,
        max_cold_ms=args.max_cold_ms,
        max_warm_ms=args.max_warm_ms,
    )

    if args.json:
        print(json.dumps({"report": report, "failures": failures}, indent=2))
    else:
        if manifest is not None:
            print(f"Manifest: id={manifest.get('id')} version={manifest.get('version')}")
        for summary in summaries:
            print(
                f"{summary.item_type}:{summary.item_id} cold={summary.cold_ms}ms warm={summary.warm_ms}ms "
                f"streams={summary.streams_count} tags={summary.tags} hashes={summary.info_hashes}"
            )
        if failures:
            print("Failures:")
            for failure in failures:
                print(f"- {failure}")
        else:
            print("Smoke test passed.")

    return 1 if failures else 0


if __name__ == "__main__":
    if not __package__:
        import subprocess

        raise SystemExit(
            subprocess.call(
                [sys.executable, "-m", "scripts.stremio_addon_smoke", *sys.argv[1:]]
            )
        )
    raise SystemExit(main())

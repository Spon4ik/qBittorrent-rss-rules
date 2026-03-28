from __future__ import annotations

import argparse
import json
import subprocess
import threading
import urllib.parse
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DETAIL_URL = "https://web.stremio.com/#/detail/series/tt33517752/tt33517752%3A1%3A1"
DEFAULT_QB_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_JACKETT_BASE_URL = "http://127.0.0.1:7000"
DEFAULT_ADDON_NAME = "Stremio QA Mock"
DEFAULT_VARIANTS = (
    "jackett_live",
    "qbrss_live",
    "qbrss_minimal",
    "qbrss_first_stream_only",
)


@dataclass(slots=True)
class VariantResult:
    variant: str
    manifest_url: str
    smoke_exit_code: int
    failures: list[str]
    visible_sources: list[str]
    hash_overlap: dict[str, Any]
    artifacts_dir: str | None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real-desktop Stremio smoke tests against multiple mock addon payload variants.",
    )
    parser.add_argument("--detail-url", default=DEFAULT_DETAIL_URL)
    parser.add_argument("--qb-base-url", default=DEFAULT_QB_BASE_URL)
    parser.add_argument("--jackett-base-url", default=DEFAULT_JACKETT_BASE_URL)
    parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        help=f"Variant to run. Defaults to: {', '.join(DEFAULT_VARIANTS)}",
    )
    parser.add_argument("--addon-name", default=DEFAULT_ADDON_NAME)
    parser.add_argument("--wait-seconds", type=float, default=12.0)
    parser.add_argument("--debug-port", type=int, default=9223)
    parser.add_argument("--artifacts-dir", default=str(PROJECT_DIR / "logs" / "qa"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-hidden", action="store_true")
    return parser.parse_args()


def _selected_variants(values: list[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_VARIANTS)
    unsupported = sorted(set(values) - set(DEFAULT_VARIANTS))
    if unsupported:
        raise SystemExit(f"Unsupported variants: {', '.join(unsupported)}")
    return values


def _detail_stream_target(detail_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(detail_url)
    fragment = parsed.fragment or ""
    if "#/detail/" in detail_url:
        fragment = detail_url.split("#", 1)[1]
    parts = [part for part in fragment.split("/") if part]
    if len(parts) < 3 or parts[0] != "detail":
        raise SystemExit(f"Could not derive stream target from detail URL: {detail_url}")
    item_type = parts[1]
    item_id = urllib.parse.unquote(parts[2])
    return item_type, item_id


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "stremio-desktop-variant-matrix"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _artifact_run_dir(root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"stremio-variant-matrix-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _display_suffix(stream: dict[str, Any]) -> str:
    name = str(stream.get("name") or "").strip()
    if name:
        lines = [line.strip() for line in name.splitlines() if line.strip()]
        if len(lines) > 1:
            return "\n".join(lines[1:])
    tag = str(stream.get("tag") or "").strip()
    if tag:
        return tag
    return "Torrent"


def _rewrite_stream_name(stream: dict[str, Any], addon_name: str) -> dict[str, Any]:
    rewritten = deepcopy(stream)
    rewritten["name"] = f"{addon_name}\n{_display_suffix(rewritten)}"
    return rewritten


def _qbrss_minimal_stream(stream: dict[str, Any], addon_name: str) -> dict[str, Any]:
    rewritten = _rewrite_stream_name(stream, addon_name)
    info_hash = str(rewritten.get("infoHash") or "").strip()
    title = str(rewritten.get("title") or rewritten.get("description") or "").strip()
    minimal: dict[str, Any] = {
        "name": rewritten["name"],
        "tag": str(rewritten.get("tag") or "").strip() or "Torrent",
        "type": str(rewritten.get("type") or "series").strip() or "series",
        "infoHash": info_hash,
        "sources": list(rewritten.get("sources") or []),
        "title": title,
        "seeders": rewritten.get("seeders"),
        "behaviorHints": {
            "bingieGroup": f"{addon_name}|{info_hash}",
        },
    }
    return {key: value for key, value in minimal.items() if value not in (None, "", [])}


def _variant_payloads(
    *,
    qb_payload: dict[str, Any],
    jackett_payload: dict[str, Any],
    addon_name: str,
) -> dict[str, dict[str, Any]]:
    qbrss_live_streams = [
        _rewrite_stream_name(stream, addon_name)
        for stream in list(qb_payload.get("streams") or [])
    ]
    jackett_live_streams = [
        _rewrite_stream_name(stream, addon_name)
        for stream in list(jackett_payload.get("streams") or [])
    ]
    qbrss_minimal_streams = [
        _qbrss_minimal_stream(stream, addon_name)
        for stream in list(qb_payload.get("streams") or [])
    ]
    return {
        "jackett_live": {"streams": jackett_live_streams},
        "qbrss_live": {"streams": qbrss_live_streams},
        "qbrss_minimal": {"streams": qbrss_minimal_streams},
        "qbrss_first_stream_only": {"streams": qbrss_live_streams[:1]},
    }


class _MockAddonServer:
    def __init__(
        self,
        *,
        addon_name: str,
        payload: dict[str, Any],
        item_type: str,
        item_id: str,
        variant: str,
    ) -> None:
        self._addon_name = addon_name
        self._payload = payload
        self._item_type = item_type
        self._item_id = item_id
        self._variant = variant
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handler_class(self):
        addon_name = self._addon_name
        payload = self._payload
        item_type = self._item_type
        item_id = self._item_id
        variant = self._variant

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, body: dict[str, Any], *, status: int = 200) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()
                self.wfile.write(encoded)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlsplit(self.path)
                decoded_path = urllib.parse.unquote(parsed.path)
                if parsed.path == "/manifest.json":
                    self._write_json(
                        {
                            "id": "org.qbrssrules.stremio.qa.mock",
                            "version": f"0.0.0+{variant}",
                            "name": addon_name,
                            "description": f"QA mock addon variant: {variant}",
                            "resources": [
                                {
                                    "name": "stream",
                                    "types": ["movie", "series"],
                                    "idPrefixes": ["tt"],
                                }
                            ],
                            "behaviorHints": {
                                "p2p": True,
                                "configurable": False,
                                "configurationRequired": False,
                            },
                            "types": ["movie", "series"],
                            "idPrefixes": ["tt"],
                            "catalogs": [],
                        }
                    )
                    return
                expected_stream_path = f"/stream/{item_type}/{item_id}.json"
                if decoded_path == expected_stream_path:
                    self._write_json(payload)
                    return
                if parsed.path.startswith("/stream/"):
                    self._write_json({"streams": []})
                    return
                self._write_json({"error": "Not found"}, status=404)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        return Handler

    @property
    def manifest_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/manifest.json"

    def __enter__(self) -> _MockAddonServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _run_smoke(
    *,
    manifest_url: str,
    addon_name: str,
    detail_url: str,
    wait_seconds: float,
    debug_port: int,
) -> tuple[int, dict[str, Any]]:
    command = [
        str(PROJECT_DIR / ".venv" / "Scripts" / "python.exe"),
        str(PROJECT_DIR / "scripts" / "stremio_desktop_smoke.py"),
        "--manifest-url",
        manifest_url,
        "--addon-name",
        addon_name,
        "--expect-source",
        addon_name,
        "--detail-url",
        detail_url,
        "--wait-seconds",
        str(wait_seconds),
        "--debug-port",
        str(debug_port),
        "--json",
    ]
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout.strip():
        payload = json.loads(completed.stdout)
    else:
        raise RuntimeError(
            f"Desktop smoke returned no JSON output for {manifest_url!r}: {completed.stderr}"
        )
    return completed.returncode, payload


def main() -> int:
    args = _parse_args()
    variants = _selected_variants(args.variants)
    item_type, item_id = _detail_stream_target(args.detail_url)
    qb_payload = _fetch_json(
        f"{args.qb_base_url.rstrip('/')}/stremio/stream/{item_type}/{item_id}.json"
    )
    jackett_payload = _fetch_json(
        f"{args.jackett_base_url.rstrip('/')}/stream/{item_type}/{item_id}.json"
    )
    payloads = _variant_payloads(
        qb_payload=qb_payload,
        jackett_payload=jackett_payload,
        addon_name=args.addon_name,
    )
    artifacts_dir = _artifact_run_dir(Path(args.artifacts_dir))

    results: list[VariantResult] = []
    for variant in variants:
        with _MockAddonServer(
            addon_name=args.addon_name,
            payload=payloads[variant],
            item_type=item_type,
            item_id=item_id,
            variant=variant,
        ) as server:
            exit_code, smoke_payload = _run_smoke(
                manifest_url=server.manifest_url,
                addon_name=args.addon_name,
                detail_url=args.detail_url,
                wait_seconds=args.wait_seconds,
                debug_port=args.debug_port,
            )
        report = smoke_payload.get("report") or {}
        detail_result = report.get("detail_result") or {}
        results.append(
            VariantResult(
                variant=variant,
                manifest_url=server.manifest_url,
                smoke_exit_code=exit_code,
                failures=list(smoke_payload.get("failures") or []),
                visible_sources=list(detail_result.get("visible_streams", {}).get("sources") or []),
                hash_overlap=dict(detail_result.get("hash_overlap") or {}),
                artifacts_dir=str(report.get("artifacts_dir") or ""),
            )
        )

    output = {
        "detail_url": args.detail_url,
        "addon_name": args.addon_name,
        "variants": [asdict(result) for result in results],
    }
    (artifacts_dir / "report.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Artifacts: {artifacts_dir}")
        for result in results:
            print(
                f"{result.variant}: exit={result.smoke_exit_code} "
                f"visible_sources={result.visible_sources} failures={result.failures}"
            )

    if args.fail_on_hidden and any(result.smoke_exit_code != 0 for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

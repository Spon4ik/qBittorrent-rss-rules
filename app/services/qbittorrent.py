from __future__ import annotations

import json
from types import TracebackType
from typing import Any, cast

import httpx

from app.config import get_environment_settings
from app.schemas import FeedOption


class QbittorrentClientError(RuntimeError):
    pass


class QbittorrentAuthError(QbittorrentClientError):
    pass


class QbittorrentConfigError(QbittorrentClientError):
    pass


class QbittorrentClient:
    def __init__(
        self,
        base_url: str | None,
        username: str | None,
        password: str | None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.username = username
        self.password = password
        self.timeout = (
            timeout if timeout is not None else get_environment_settings().request_timeout
        )
        self._authenticated = False
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> QbittorrentClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def login(self) -> None:
        if not (self.base_url and self.username and self.password):
            raise QbittorrentConfigError("qBittorrent WebUI connection is not fully configured.")
        try:
            response = self._client.post(
                "/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise QbittorrentClientError(f"Unable to connect to qBittorrent: {exc}") from exc
        login_succeeded = response.text.strip() == "Ok." or (
            response.status_code == 204 and bool(response.cookies)
        )
        if not login_succeeded:
            raise QbittorrentAuthError("qBittorrent rejected the provided credentials.")
        self._authenticated = True

    def test_connection(self) -> None:
        self.login()

    def get_rules(self) -> dict[str, dict[str, object]]:
        payload = self._request("GET", "/api/v2/rss/rules")
        if not isinstance(payload, dict):
            raise QbittorrentClientError("Unexpected qBittorrent rules payload.")
        return payload

    def get_feeds(self) -> list[FeedOption]:
        payload = self._request(
            "GET",
            "/api/v2/rss/items",
            params={"include_feed_data": "true"},
        )
        return self.flatten_feed_tree(payload)

    def add_feed(self, *, url: str, path: str) -> None:
        cleaned_url = str(url or "").strip()
        if not cleaned_url:
            return
        self._request(
            "POST",
            "/api/v2/rss/addFeed",
            data={"url": cleaned_url, "path": str(path or "").strip()},
            expect_json=False,
            allowed_status_codes={409},
        )

    def remove_feed(self, path: str) -> None:
        cleaned_path = str(path or "").strip()
        if not cleaned_path:
            return
        self._request(
            "POST",
            "/api/v2/rss/removeItem",
            data={"path": cleaned_path},
            expect_json=False,
            allowed_status_codes={404},
        )

    def create_category(self, name: str) -> None:
        if not name.strip():
            return
        self._request(
            "POST",
            "/api/v2/torrents/createCategory",
            data={"category": name},
            expect_json=False,
            allowed_status_codes={409},
        )

    def set_rule(self, rule_name: str, rule_def: dict[str, object]) -> None:
        self._request(
            "POST",
            "/api/v2/rss/setRule",
            data={"ruleName": rule_name, "ruleDef": json.dumps(rule_def)},
            expect_json=False,
        )

    def remove_rule(self, rule_name: str) -> None:
        self._request(
            "POST",
            "/api/v2/rss/removeRule",
            data={"ruleName": rule_name},
            expect_json=False,
        )

    def add_torrent_url(
        self,
        *,
        link: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        payload: dict[str, str] = {
            "urls": link,
            "paused": "true" if paused else "false",
            # qBittorrent switched add-torrent pause semantics to `stopped`
            # in newer WebUI API builds; keep `paused` for older versions.
            "stopped": "true" if paused else "false",
            "sequentialDownload": "true" if sequential_download else "false",
            "firstLastPiecePrio": "true" if first_last_piece_prio else "false",
        }
        if category.strip():
            payload["category"] = category.strip()
        if save_path.strip():
            payload["savepath"] = save_path.strip()
        self._request(
            "POST",
            "/api/v2/torrents/add",
            data=payload,
            expect_json=False,
        )

    def add_torrent_file(
        self,
        *,
        torrent_bytes: bytes,
        filename: str = "queued-result.torrent",
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        payload: dict[str, str] = {
            "paused": "true" if paused else "false",
            "stopped": "true" if paused else "false",
            "sequentialDownload": "true" if sequential_download else "false",
            "firstLastPiecePrio": "true" if first_last_piece_prio else "false",
        }
        if category.strip():
            payload["category"] = category.strip()
        if save_path.strip():
            payload["savepath"] = save_path.strip()
        self._request(
            "POST",
            "/api/v2/torrents/add",
            data=payload,
            files={"torrents": (filename, torrent_bytes, "application/x-bittorrent")},
            expect_json=False,
        )

    def get_torrent_files(self, info_hash: str) -> list[dict[str, object]]:
        payload = self._request(
            "GET",
            "/api/v2/torrents/files",
            params={"hash": info_hash},
        )
        if not isinstance(payload, list):
            raise QbittorrentClientError("Unexpected qBittorrent torrent files payload.")
        return [item for item in payload if isinstance(item, dict)]

    def get_torrent(self, info_hash: str) -> dict[str, object] | None:
        cleaned_hash = str(info_hash or "").strip()
        if not cleaned_hash:
            return None
        for item in self.get_torrents(hashes=cleaned_hash):
            return item
        return None

    def get_torrent_trackers(self, info_hash: str) -> list[dict[str, object]]:
        payload = self._request(
            "GET",
            "/api/v2/torrents/trackers",
            params={"hash": info_hash},
        )
        if not isinstance(payload, list):
            raise QbittorrentClientError("Unexpected qBittorrent torrent trackers payload.")
        return [item for item in payload if isinstance(item, dict)]

    def get_torrents(self, *, hashes: str | None = None) -> list[dict[str, object]]:
        params: dict[str, str] = {}
        cleaned_hashes = str(hashes or "").strip()
        if cleaned_hashes:
            params["hashes"] = cleaned_hashes
        payload = self._request(
            "GET",
            "/api/v2/torrents/info",
            params=params or None,
        )
        if not isinstance(payload, list):
            raise QbittorrentClientError("Unexpected qBittorrent torrents info payload.")
        return [item for item in payload if isinstance(item, dict)]

    def set_file_priority(self, info_hash: str, file_ids: list[int], priority: int) -> None:
        if not file_ids:
            return
        payload = {
            "hash": info_hash,
            "id": "|".join(str(file_id) for file_id in file_ids),
            "priority": str(int(priority)),
        }
        try:
            self._request(
                "POST",
                "/api/v2/torrents/filePrio",
                data=payload,
                expect_json=False,
            )
        except QbittorrentClientError as exc:
            if not self._is_missing_file_priority_endpoint_error(exc):
                raise
            self._set_file_priority_legacy(
                info_hash=info_hash,
                file_ids=file_ids,
                priority=int(priority),
            )

    def add_trackers(self, info_hash: str, tracker_urls: list[str]) -> None:
        cleaned_urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_url in tracker_urls:
            candidate = str(raw_url or "").strip()
            key = candidate.casefold()
            if not candidate or key in seen_urls:
                continue
            seen_urls.add(key)
            cleaned_urls.append(candidate)
        if not cleaned_urls:
            return
        self._request(
            "POST",
            "/api/v2/torrents/addTrackers",
            data={
                "hash": info_hash,
                "urls": "\n".join(cleaned_urls),
            },
            expect_json=False,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool = True,
        allowed_status_codes: set[int] | None = None,
        **kwargs: Any,
    ) -> object | None:
        if not self._authenticated:
            self.login()
        allowed_status_codes = allowed_status_codes or set()
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise QbittorrentClientError(f"qBittorrent request failed: {exc}") from exc
        if response.status_code not in allowed_status_codes:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise QbittorrentClientError(f"qBittorrent request failed: {exc}") from exc
        if not expect_json:
            return None
        return cast(object, response.json())

    def _set_file_priority_legacy(self, *, info_hash: str, file_ids: list[int], priority: int) -> None:
        for file_id in file_ids:
            self._request(
                "POST",
                "/command/setFilePrio",
                data={
                    "hash": info_hash,
                    "id": str(int(file_id)),
                    "priority": str(int(priority)),
                },
                expect_json=False,
            )

    @staticmethod
    def _is_missing_file_priority_endpoint_error(exc: QbittorrentClientError) -> bool:
        message = str(exc)
        return (
            "/api/v2/torrents/filePrio" in message
            and "404 Not Found" in message
        )

    @classmethod
    def flatten_feed_tree(cls, payload: object) -> list[FeedOption]:
        entries: list[FeedOption] = []
        seen: set[str] = set()

        def walk(node: object, prefix: str = "") -> None:
            if isinstance(node, dict):
                label = node.get("name")
                url = node.get("url")
                if isinstance(url, str) and url and url not in seen:
                    seen.add(url)
                    entries.append(FeedOption(label=prefix or label or url, url=url))
                for key, value in node.items():
                    if key in {"url", "uid", "articles"}:
                        continue
                    next_prefix = prefix
                    if isinstance(key, str) and key not in {"children", "data"}:
                        next_prefix = key if not prefix else f"{prefix} / {key}"
                    walk(value, next_prefix)
            elif isinstance(node, list):
                for item in node:
                    walk(item, prefix)

        walk(payload)
        entries.sort(key=lambda item: item.label.lower())
        return entries

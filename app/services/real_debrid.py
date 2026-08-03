from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

REAL_DEBRID_API_BASE_URL = "https://api.real-debrid.com/rest/1.0"
REAL_DEBRID_OAUTH_BASE_URL = "https://api.real-debrid.com/oauth/v2"
REAL_DEBRID_DEVICE_CLIENT_ID = "X245A4XAIBGVM"
REAL_DEBRID_DEVICE_GRANT_TYPE = "http://oauth.net/grant_type/device/1.0"


class RealDebridError(RuntimeError):
    pass


class RealDebridAuthError(RealDebridError):
    pass


class RealDebridAuthorizationPendingError(RealDebridError):
    pass


@dataclass(frozen=True, slots=True)
class RealDebridDeviceCode:
    flow_id: str
    client_id: str
    device_code: str
    user_code: str
    verification_url: str
    direct_verification_url: str | None
    interval_seconds: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RealDebridDeviceCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True, slots=True)
class RealDebridToken:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RealDebridAccount:
    username: str
    account_type: str
    premium_until: datetime | None

    @property
    def is_premium(self) -> bool:
        return self.account_type.casefold() == "premium" and (
            self.premium_until is None or self.premium_until > datetime.now(UTC)
        )


class RealDebridDeviceFlowRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flows: dict[str, RealDebridDeviceCode] = {}

    def create(self, flow: RealDebridDeviceCode) -> None:
        with self._lock:
            self._prune_locked()
            self._flows[flow.flow_id] = flow

    def get(self, flow_id: str) -> RealDebridDeviceCode | None:
        with self._lock:
            self._prune_locked()
            return self._flows.get(str(flow_id or "").strip())

    def remove(self, flow_id: str) -> None:
        with self._lock:
            self._flows.pop(str(flow_id or "").strip(), None)

    def reset(self) -> None:
        with self._lock:
            self._flows.clear()

    def _prune_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [flow_id for flow_id, flow in self._flows.items() if flow.expires_at <= now]
        for flow_id in expired:
            self._flows.pop(flow_id, None)


DEVICE_FLOW_REGISTRY = RealDebridDeviceFlowRegistry()


class RealDebridClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.access_token = str(access_token or "").strip() or None
        self._sleep = sleep
        headers = {"User-Agent": "qBittorrent-RSS-Rules/1.4"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        self._client = httpx.Client(
            base_url=REAL_DEBRID_API_BASE_URL,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> RealDebridClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def start_device_flow(self) -> RealDebridDeviceCode:
        payload = self._request_json(
            "GET",
            f"{REAL_DEBRID_OAUTH_BASE_URL}/device/code",
            params={"client_id": REAL_DEBRID_DEVICE_CLIENT_ID, "new_credentials": "yes"},
            require_auth=False,
        )
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned an invalid device authorization response.")
        device_code = _required_text(payload, "device_code", "device authorization")
        user_code = _required_text(payload, "user_code", "device authorization")
        verification_url = _required_text(payload, "verification_url", "device authorization")
        expires_in = _positive_int(payload.get("expires_in"), default=600)
        interval = max(1, _positive_int(payload.get("interval"), default=5))
        flow = RealDebridDeviceCode(
            flow_id=secrets.token_urlsafe(24),
            client_id=REAL_DEBRID_DEVICE_CLIENT_ID,
            device_code=device_code,
            user_code=user_code,
            verification_url=verification_url,
            direct_verification_url=_optional_text(payload.get("direct_verification_url")),
            interval_seconds=interval,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        )
        DEVICE_FLOW_REGISTRY.create(flow)
        return flow

    def poll_device_credentials(
        self, flow: RealDebridDeviceCode
    ) -> RealDebridDeviceCredentials:
        try:
            payload = self._request_json(
                "GET",
                f"{REAL_DEBRID_OAUTH_BASE_URL}/device/credentials",
                params={"client_id": flow.client_id, "code": flow.device_code},
                require_auth=False,
            )
        except RealDebridError as exc:
            if "authorization_pending" in str(exc).casefold() or "not authorized" in str(
                exc
            ).casefold():
                raise RealDebridAuthorizationPendingError(
                    "Real-Debrid device authorization is still pending."
                ) from exc
            raise
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned invalid device credentials.")
        return RealDebridDeviceCredentials(
            client_id=_required_text(payload, "client_id", "device credentials"),
            client_secret=_required_text(payload, "client_secret", "device credentials"),
        )

    def exchange_device_code(
        self,
        flow: RealDebridDeviceCode,
        credentials: RealDebridDeviceCredentials,
    ) -> RealDebridToken:
        return self._exchange_token(
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            code=flow.device_code,
        )

    def refresh_token(
        self, *, client_id: str, client_secret: str, refresh_token: str
    ) -> RealDebridToken:
        return self._exchange_token(
            client_id=client_id,
            client_secret=client_secret,
            code=refresh_token,
        )

    def get_account(self) -> RealDebridAccount:
        payload = self._request_json("GET", "/user")
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned an invalid account response.")
        return RealDebridAccount(
            username=_required_text(payload, "username", "account"),
            account_type=str(payload.get("type") or "unknown").strip(),
            premium_until=_parse_datetime(payload.get("expiration")),
        )

    def list_torrents(self, *, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET", "/torrents", params={"page": max(1, page), "limit": min(100, max(1, limit))}
        )
        return _dict_list(payload, context="torrent list")

    def get_torrent(self, torrent_id: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"/torrents/info/{torrent_id}")
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned invalid torrent information.")
        return payload

    def list_downloads(self, *, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET", "/downloads", params={"page": max(1, page), "limit": min(100, max(1, limit))}
        )
        return _dict_list(payload, context="download history")

    def add_magnet(self, magnet: str) -> dict[str, Any]:
        payload = self._request_json("POST", "/torrents/addMagnet", data={"magnet": magnet})
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned an invalid magnet submission response.")
        return payload

    def add_torrent(self, torrent_bytes: bytes, *, filename: str) -> dict[str, Any]:
        payload = self._request_json(
            "PUT",
            "/torrents/addTorrent",
            files={"file": (filename, torrent_bytes, "application/x-bittorrent")},
        )
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned an invalid torrent submission response.")
        return payload

    def select_files(self, torrent_id: str, file_ids: list[int] | str) -> None:
        if isinstance(file_ids, str):
            selected = file_ids.strip()
        else:
            selected = ",".join(str(int(file_id)) for file_id in file_ids)
        if not selected:
            raise RealDebridError("At least one Real-Debrid file must be selected.")
        self._request_json(
            "POST",
            f"/torrents/selectFiles/{torrent_id}",
            data={"files": selected},
            expect_json=False,
        )

    def delete_torrent(self, torrent_id: str) -> None:
        self._request_json("DELETE", f"/torrents/delete/{torrent_id}", expect_json=False)

    def unrestrict_link(self, link: str) -> dict[str, Any]:
        payload = self._request_json("POST", "/unrestrict/link", data={"link": link})
        if not isinstance(payload, dict):
            raise RealDebridError("Real-Debrid returned an invalid unrestricted-link response.")
        return payload

    def _exchange_token(self, *, client_id: str, client_secret: str, code: str) -> RealDebridToken:
        payload = self._request_json(
            "POST",
            f"{REAL_DEBRID_OAUTH_BASE_URL}/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": REAL_DEBRID_DEVICE_GRANT_TYPE,
            },
            require_auth=False,
        )
        if not isinstance(payload, dict):
            raise RealDebridAuthError("Real-Debrid returned an invalid OAuth token response.")
        expires_in = _positive_int(payload.get("expires_in"), default=3600)
        return RealDebridToken(
            access_token=_required_text(payload, "access_token", "OAuth token"),
            refresh_token=_required_text(payload, "refresh_token", "OAuth token"),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        require_auth: bool = True,
        expect_json: bool = True,
        **kwargs: Any,
    ) -> object | None:
        if require_auth and not self.access_token:
            raise RealDebridAuthError("Real-Debrid is not connected.")
        for attempt in range(3):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise RealDebridError(f"Real-Debrid request failed: {exc}") from exc
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"), attempt)
                self._sleep(retry_after)
                continue
            if response.status_code in {401, 403} and require_auth:
                raise RealDebridAuthError(_provider_error_message(response, "authentication failed"))
            if response.is_error:
                raise RealDebridError(_provider_error_message(response, "request failed"))
            if not expect_json or response.status_code == 204 or not response.content:
                return None
            try:
                payload: object = response.json()
                return payload
            except ValueError as exc:
                raise RealDebridError("Real-Debrid returned a non-JSON response.") from exc
        raise RealDebridError("Real-Debrid request retry budget was exhausted.")


def _provider_error_message(response: httpx.Response, fallback: str) -> str:
    code = ""
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = str(payload.get("error_code") or payload.get("error") or "").strip()
        message = str(payload.get("error") or payload.get("message") or "").strip()
    detail = message or fallback
    if code and code.casefold() != detail.casefold():
        detail = f"{detail} ({code})"
    return f"Real-Debrid {detail}."


def _required_text(payload: dict[str, Any], key: str, context: str) -> str:
    value = _optional_text(payload.get(key))
    if value:
        return value
    raise RealDebridError(f"Real-Debrid {context} response is missing {key}.")


def _optional_text(value: object | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _positive_int(value: object | None, *, default: int) -> int:
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return default
    return numeric if numeric > 0 else default


def _retry_after_seconds(value: str | None, attempt: int) -> float:
    try:
        parsed = float(str(value or "").strip())
    except ValueError:
        parsed = 0.5 * (2**attempt)
    return max(0.0, min(10.0, parsed))


def _dict_list(payload: object, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise RealDebridError(f"Real-Debrid returned an invalid {context} response.")
    return [item for item in payload if isinstance(item, dict)]


def _parse_datetime(value: object | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.services.real_debrid import (
    DEVICE_FLOW_REGISTRY,
    RealDebridAuthorizationPendingError,
    RealDebridClient,
)


@pytest.fixture(autouse=True)
def reset_device_flows() -> None:
    DEVICE_FLOW_REGISTRY.reset()
    yield
    DEVICE_FLOW_REGISTRY.reset()


def test_device_oauth_flow_exchanges_credentials_and_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/device/code"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD",
                    "verification_url": "https://real-debrid.com/device",
                    "direct_verification_url": "https://real-debrid.com/device?code=ABCD",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        if request.url.path.endswith("/device/credentials"):
            return httpx.Response(200, json={"client_id": "client", "client_secret": "secret"})
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                },
            )
        raise AssertionError(request.url)

    with RealDebridClient(transport=httpx.MockTransport(handler)) as client:
        flow = client.start_device_flow()
        credentials = client.poll_device_credentials(flow)
        token = client.exchange_device_code(flow, credentials)

    assert flow.user_code == "ABCD"
    assert DEVICE_FLOW_REGISTRY.get(flow.flow_id) == flow
    assert credentials.client_id == "client"
    assert token.access_token == "access"
    assert token.expires_at > datetime.now(UTC)
    assert len(requests) == 3


def test_pending_device_authorization_has_specific_state() -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD",
                    "verification_url": "https://real-debrid.com/device",
                    "expires_in": 600,
                    "interval": 5,
                },
            ),
            httpx.Response(403, json={"error": "authorization_pending"}),
        ]
    )

    with RealDebridClient(transport=httpx.MockTransport(lambda _request: next(responses))) as client:
        flow = client.start_device_flow()
        with pytest.raises(RealDebridAuthorizationPendingError):
            client.poll_device_credentials(flow)


def test_authenticated_torrent_and_download_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer access"
        if request.url.path.endswith("/torrents"):
            return httpx.Response(200, json=[{"id": "torrent-1", "hash": "a" * 40}])
        if request.url.path.endswith("/downloads"):
            return httpx.Response(200, json=[{"id": "download-1", "filename": "movie.mkv"}])
        if request.url.path.endswith("/unrestrict/link"):
            return httpx.Response(200, json={"download": "https://download.invalid/file"})
        raise AssertionError(request.url)

    with RealDebridClient(
        "access", transport=httpx.MockTransport(handler)
    ) as client:
        torrents = client.list_torrents()
        downloads = client.list_downloads()
        unrestricted = client.unrestrict_link("https://provider.invalid/link")

    assert torrents[0]["id"] == "torrent-1"
    assert downloads[0]["id"] == "download-1"
    assert unrestricted["download"] == "https://download.invalid/file"


def test_transient_rate_limit_retries_without_exposing_response_body() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow_down"})
        return httpx.Response(200, json=[])

    with RealDebridClient(
        "access", transport=httpx.MockTransport(handler), sleep=sleeps.append
    ) as client:
        assert client.list_torrents() == []

    assert calls == 2
    assert sleeps == [0.0]

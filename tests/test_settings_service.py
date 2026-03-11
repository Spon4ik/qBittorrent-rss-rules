from __future__ import annotations

import pytest

from app.config import get_environment_settings, obfuscate_secret
from app.models import AppSettings
from app.services.settings_service import (
    SettingsService,
    _rewrite_localhost_url_for_wsl,
)


def _clear_env_cache() -> None:
    get_environment_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_environment_cache_fixture() -> None:
    _clear_env_cache()
    yield
    _clear_env_cache()


def test_rewrite_localhost_url_for_wsl_updates_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    assert _rewrite_localhost_url_for_wsl("http://localhost:8080/") == "http://host.docker.internal:8080/"
    assert (
        _rewrite_localhost_url_for_wsl("http://127.0.0.1:8080/path?x=1")
        == "http://host.docker.internal:8080/path?x=1"
    )


def test_rewrite_localhost_url_for_wsl_keeps_non_loopback_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    assert _rewrite_localhost_url_for_wsl("http://host.docker.internal:8080/") == "http://host.docker.internal:8080/"
    assert _rewrite_localhost_url_for_wsl("http://192.168.1.51:8080/") == "http://192.168.1.51:8080/"


def test_rewrite_localhost_url_for_wsl_is_noop_outside_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.8.0-generic")
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "#1 SMP PREEMPT_DYNAMIC")

    assert _rewrite_localhost_url_for_wsl("http://localhost:8080/") == "http://localhost:8080/"


def test_resolve_qb_connection_rewrites_settings_localhost_in_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    monkeypatch.delenv("QB_RULES_QB_BASE_URL", raising=False)
    monkeypatch.delenv("QB_RULES_QB_USERNAME", raising=False)
    monkeypatch.delenv("QB_RULES_QB_PASSWORD", raising=False)
    _clear_env_cache()

    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080/",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )

    resolved = SettingsService.resolve_qb_connection(settings)

    assert resolved.base_url == "http://host.docker.internal:8080/"
    assert resolved.username == "admin"
    assert resolved.password == "secret"


def test_resolve_qb_connection_rewrites_env_localhost_in_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    monkeypatch.setenv("QB_RULES_QB_BASE_URL", "http://localhost:18080/")
    monkeypatch.setenv("QB_RULES_QB_USERNAME", "env-user")
    monkeypatch.setenv("QB_RULES_QB_PASSWORD", "env-pass")
    _clear_env_cache()

    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080/",
        qb_username="settings-user",
        qb_password_encrypted=obfuscate_secret("settings-pass"),
    )

    resolved = SettingsService.resolve_qb_connection(settings)

    assert resolved.base_url == "http://host.docker.internal:18080/"
    assert resolved.username == "env-user"
    assert resolved.password == "env-pass"

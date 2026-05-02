from __future__ import annotations

from pathlib import Path

import pytest

import app.config as app_config
from app.config import get_environment_settings, obfuscate_secret
from app.models import AppSettings
from app.schemas import SettingsFormPayload
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


def test_rewrite_localhost_url_for_wsl_updates_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2"
    )
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    assert (
        _rewrite_localhost_url_for_wsl("http://localhost:8080/")
        == "http://host.docker.internal:8080/"
    )
    assert (
        _rewrite_localhost_url_for_wsl("http://127.0.0.1:8080/path?x=1")
        == "http://host.docker.internal:8080/path?x=1"
    )


def test_rewrite_localhost_url_for_wsl_keeps_non_loopback_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2"
    )
    monkeypatch.setattr("app.services.settings_service.platform.version", lambda: "WSL2")

    assert (
        _rewrite_localhost_url_for_wsl("http://host.docker.internal:8080/")
        == "http://host.docker.internal:8080/"
    )
    assert (
        _rewrite_localhost_url_for_wsl("http://192.168.1.51:8080/") == "http://192.168.1.51:8080/"
    )


def test_rewrite_localhost_url_for_wsl_is_noop_outside_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.settings_service.platform.release", lambda: "6.8.0-generic")
    monkeypatch.setattr(
        "app.services.settings_service.platform.version", lambda: "#1 SMP PREEMPT_DYNAMIC"
    )

    assert _rewrite_localhost_url_for_wsl("http://localhost:8080/") == "http://localhost:8080/"


def test_ensure_runtime_dirs_touches_relative_sqlite_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QB_RULES_DATABASE_URL", "sqlite:///./data/qb_rules.db")
    monkeypatch.setattr(app_config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(app_config, "DATA_DIR", tmp_path / "data")
    _clear_env_cache()

    app_config.ensure_runtime_dirs()

    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "data" / "qb_rules.db").exists()


def test_resolve_qb_connection_rewrites_settings_localhost_in_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2"
    )
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


def test_resolve_qb_connection_rewrites_env_localhost_in_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.settings_service.platform.release", lambda: "6.6.87.2-microsoft-standard-WSL2"
    )
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


def test_resolve_jellyfin_prefers_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QB_RULES_JELLYFIN_DB_PATH", r"D:\Env\jellyfin.db")
    monkeypatch.setenv("QB_RULES_JELLYFIN_USER_NAME", "EnvUser")
    _clear_env_cache()

    settings = AppSettings(
        id="default",
        jellyfin_db_path=r"C:\ProgramData\Jellyfin\Server\data\jellyfin.db",
        jellyfin_user_name="SavedUser",
        jellyfin_auto_sync_enabled=True,
        jellyfin_auto_sync_interval_seconds=30,
    )

    resolved = SettingsService.resolve_jellyfin(settings)

    assert resolved.db_path == r"D:\Env\jellyfin.db"
    assert resolved.user_name == "EnvUser"
    assert resolved.auto_sync_enabled is True
    assert resolved.auto_sync_interval_seconds == 30


def test_get_or_create_normalizes_jellyfin_settings(db_session) -> None:
    settings = AppSettings(
        id="default",
        jellyfin_db_path="  C:\\ProgramData\\Jellyfin\\Server\\data\\jellyfin.db  ",
        jellyfin_user_name="  Spon4ik  ",
        jellyfin_auto_sync_enabled=True,
        jellyfin_auto_sync_interval_seconds=1,
        jellyfin_auto_sync_last_status="",
    )
    db_session.add(settings)
    db_session.commit()

    normalized = SettingsService.get_or_create(db_session)

    assert normalized.jellyfin_db_path == r"C:\ProgramData\Jellyfin\Server\data\jellyfin.db"
    assert normalized.jellyfin_user_name == "Spon4ik"
    assert normalized.jellyfin_auto_sync_enabled is True
    assert normalized.jellyfin_auto_sync_interval_seconds == 5
    assert normalized.jellyfin_auto_sync_last_status == "idle"


def test_get_or_create_normalizes_rules_page_and_schedule_defaults(db_session) -> None:
    settings = AppSettings(
        id="default",
        rules_page_view_mode="unsupported",
        rules_page_sort_field="unknown-field",
        rules_page_sort_direction="up",
        rules_fetch_schedule_interval_minutes=1,
        rules_fetch_schedule_scope="invalid",
        rules_fetch_schedule_last_status="",
    )
    db_session.add(settings)
    db_session.commit()

    normalized = SettingsService.get_or_create(db_session)

    assert normalized.rules_page_view_mode == "table"
    assert normalized.rules_page_sort_field == "updated_at"
    assert normalized.rules_page_sort_direction == "desc"
    assert normalized.rules_fetch_schedule_interval_minutes == 5
    assert normalized.rules_fetch_schedule_scope == "enabled"
    assert normalized.rules_fetch_schedule_last_status == "idle"


def test_settings_persist_jackett_language_overrides(db_session) -> None:
    settings = SettingsService.get_or_create(db_session)
    payload = SettingsFormPayload(
        jackett_language_overrides_text="noname-clubl=ru;thepiratebay=en,multi",
    )

    SettingsService.apply_payload(settings, payload)
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)

    assert settings.jackett_language_overrides == {
        "noname-clubl": ["ru"],
        "thepiratebay": ["en", "multi"],
    }
    assert SettingsService.to_form_dict(settings)["jackett_language_overrides_text"] == (
        "noname-clubl=ru\nthepiratebay=en,multi"
    )

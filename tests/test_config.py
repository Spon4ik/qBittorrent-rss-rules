from __future__ import annotations

from pathlib import Path

from app.config import ROOT_DIR, get_environment_settings, resolve_runtime_path


def test_relative_sqlite_database_url_resolves_from_app_root(monkeypatch) -> None:
    monkeypatch.setenv("QB_RULES_DATABASE_URL", "sqlite:///./data/qb_rules.db")
    get_environment_settings.cache_clear()

    try:
        settings = get_environment_settings()
    finally:
        get_environment_settings.cache_clear()

    expected_path = (ROOT_DIR / "data" / "qb_rules.db").resolve()
    assert settings.database_url == f"sqlite:///{expected_path.as_posix()}"


def test_absolute_sqlite_database_url_is_preserved(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "custom.db"
    monkeypatch.setenv("QB_RULES_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_environment_settings.cache_clear()

    try:
        settings = get_environment_settings()
    finally:
        get_environment_settings.cache_clear()

    assert settings.database_url == f"sqlite:///{database_path.as_posix()}"


def test_jackett_language_overrides_parse_json(monkeypatch) -> None:
    monkeypatch.setenv(
        "QB_RULES_JACKETT_LANGUAGE_OVERRIDES",
        '{"noname-clubl":["ru"],"thepiratebay":"en, multi"}',
    )
    get_environment_settings.cache_clear()

    try:
        settings = get_environment_settings()
    finally:
        get_environment_settings.cache_clear()

    assert settings.jackett_language_overrides == {
        "noname-clubl": ["ru"],
        "thepiratebay": ["en", "multi"],
    }


def test_jackett_language_overrides_parse_assignment_list(monkeypatch) -> None:
    monkeypatch.setenv(
        "QB_RULES_JACKETT_LANGUAGE_OVERRIDES",
        "noname-clubl=ru;thepiratebay=en,multi",
    )
    get_environment_settings.cache_clear()

    try:
        settings = get_environment_settings()
    finally:
        get_environment_settings.cache_clear()

    assert settings.jackett_language_overrides == {
        "noname-clubl": ["ru"],
        "thepiratebay": ["en", "multi"],
    }


def test_windows_host_path_translates_to_container_mount_root() -> None:
    resolved_path = resolve_runtime_path(
        r"C:\Users\nucc\AppData\Local\Programs\Stremio\leveldb",
        windows_mount_root="/host",
    )

    assert resolved_path == Path("/host/C/Users/nucc/AppData/Local/Programs/Stremio/leveldb")


def test_relative_runtime_path_resolves_from_app_root() -> None:
    resolved_path = resolve_runtime_path("data/qb_rules.db")

    assert resolved_path == (ROOT_DIR / "data" / "qb_rules.db").resolve()

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
WINDOWS_DRIVE_PATH_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<tail>.*)$")


def _get_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_jackett_language_overrides(raw_value: str | None) -> dict[str, list[str]]:
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return {}

    raw_map: dict[str, object]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        raw_map = {}
        for segment in re.split(r"[;\n]+", cleaned):
            if not segment.strip() or "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            raw_map[key.strip()] = value
    else:
        if not isinstance(parsed, dict):
            return {}
        raw_map = parsed

    overrides: dict[str, list[str]] = {}
    for raw_indexer, raw_languages in raw_map.items():
        indexer = str(raw_indexer or "").strip().casefold()
        if not indexer:
            continue
        if isinstance(raw_languages, str):
            language_values = re.split(r"[\s,|]+", raw_languages)
        elif isinstance(raw_languages, list):
            language_values = [str(item or "") for item in raw_languages]
        else:
            continue
        languages: list[str] = []
        seen: set[str] = set()
        for raw_language in language_values:
            language = str(raw_language or "").strip().casefold()
            if not language or language in seen:
                continue
            seen.add(language)
            languages.append(language)
        if languages:
            overrides[indexer] = languages
    return overrides


def _normalize_sqlite_database_url(database_url: str) -> str:
    value = database_url.strip()
    if not value.startswith("sqlite:///"):
        return value

    raw_path = value.removeprefix("sqlite:///").strip()
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        return value

    database_path = Path(unquote(raw_path))
    if database_path.is_absolute():
        return value

    resolved_path = (ROOT_DIR / database_path).resolve()
    return f"sqlite:///{resolved_path.as_posix()}"


@dataclass(frozen=True, slots=True)
class EnvironmentSettings:
    app_env: str
    host: str
    port: int
    database_url: str
    request_timeout: float
    qb_base_url: str | None
    qb_username: str | None
    qb_password: str | None
    jackett_api_url: str | None
    jackett_qb_url: str | None
    jackett_api_key: str | None
    jellyfin_db_path: str | None
    jellyfin_user_name: str | None
    enable_jellyfin_auto_sync_scheduler: bool
    stremio_local_storage_path: str | None
    stremio_auth_key: str | None
    enable_stremio_auto_sync_scheduler: bool
    omdb_api_key: str | None
    save_secrets_to_db: bool
    enable_rule_fetch_scheduler: bool
    rule_fetch_scheduler_poll_seconds: float
    sync_rules_on_startup: bool
    windows_host_mount_root: str
    jackett_language_overrides: dict[str, list[str]]


@lru_cache
def get_environment_settings() -> EnvironmentSettings:
    database_url = _normalize_sqlite_database_url(
        os.getenv("QB_RULES_DATABASE_URL", "sqlite:///./data/qb_rules.db")
    )
    return EnvironmentSettings(
        app_env=os.getenv("QB_RULES_APP_ENV", "development"),
        host=os.getenv("QB_RULES_HOST", "127.0.0.1"),
        port=int(os.getenv("QB_RULES_PORT", "8000")),
        database_url=database_url,
        request_timeout=float(os.getenv("QB_RULES_REQUEST_TIMEOUT", "10")),
        qb_base_url=os.getenv("QB_RULES_QB_BASE_URL") or None,
        qb_username=os.getenv("QB_RULES_QB_USERNAME") or None,
        qb_password=os.getenv("QB_RULES_QB_PASSWORD") or None,
        jackett_api_url=os.getenv("QB_RULES_JACKETT_API_URL") or None,
        jackett_qb_url=os.getenv("QB_RULES_JACKETT_QB_URL") or None,
        jackett_api_key=os.getenv("QB_RULES_JACKETT_API_KEY") or None,
        jellyfin_db_path=os.getenv("QB_RULES_JELLYFIN_DB_PATH") or None,
        jellyfin_user_name=os.getenv("QB_RULES_JELLYFIN_USER_NAME") or None,
        enable_jellyfin_auto_sync_scheduler=_get_bool(
            os.getenv("QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER"),
            True,
        ),
        stremio_local_storage_path=os.getenv("QB_RULES_STREMIO_LOCAL_STORAGE_PATH") or None,
        stremio_auth_key=os.getenv("QB_RULES_STREMIO_AUTH_KEY") or None,
        enable_stremio_auto_sync_scheduler=_get_bool(
            os.getenv("QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER"),
            True,
        ),
        omdb_api_key=os.getenv("QB_RULES_OMDB_API_KEY") or None,
        save_secrets_to_db=_get_bool(os.getenv("QB_RULES_SAVE_SECRETS_TO_DB"), False),
        enable_rule_fetch_scheduler=_get_bool(
            os.getenv("QB_RULES_ENABLE_RULE_FETCH_SCHEDULER"), True
        ),
        rule_fetch_scheduler_poll_seconds=float(
            os.getenv("QB_RULES_RULE_FETCH_SCHEDULER_POLL_SECONDS", "30")
        ),
        sync_rules_on_startup=_get_bool(os.getenv("QB_RULES_SYNC_RULES_ON_STARTUP"), True),
        windows_host_mount_root=os.getenv("QB_RULES_WINDOWS_HOST_MOUNT_ROOT", "/host").strip()
        or "/host",
        jackett_language_overrides=_parse_jackett_language_overrides(
            os.getenv("QB_RULES_JACKETT_LANGUAGE_OVERRIDES")
        ),
    )


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_environment_settings()
    database_url = str(settings.database_url or "").strip()
    if not database_url.startswith("sqlite:///"):
        return

    raw_path = database_url.removeprefix("sqlite:///").strip()
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        return

    database_path = Path(unquote(raw_path))
    if not database_path.is_absolute():
        database_path = (ROOT_DIR / database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.touch(exist_ok=True)


def resolve_runtime_path(
    raw_path: str | None,
    *,
    relative_base: Path = ROOT_DIR,
    windows_mount_root: str | None = None,
) -> Path | None:
    cleaned = str(raw_path or "").strip()
    if not cleaned:
        return None

    expanded = os.path.expanduser(cleaned)
    windows_match = WINDOWS_DRIVE_PATH_RE.match(expanded)
    if windows_match and (os.name != "nt" or windows_mount_root is not None):
        mount_root = (
            windows_mount_root
            if windows_mount_root is not None
            else get_environment_settings().windows_host_mount_root
        )
        drive = windows_match.group("drive").upper()
        tail = windows_match.group("tail").replace("\\", "/")
        translated_path = Path(mount_root) / drive / tail
        if os.name == "nt" and windows_mount_root is not None:
            return translated_path
        return translated_path.resolve()

    path = Path(expanded)
    if not path.is_absolute():
        path = relative_base / path
    return path.resolve()


def obfuscate_secret(value: str) -> str:
    raw = value.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def reveal_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception:
        return None

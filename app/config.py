from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def _get_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


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


@lru_cache
def get_environment_settings() -> EnvironmentSettings:
    return EnvironmentSettings(
        app_env=os.getenv("QB_RULES_APP_ENV", "development"),
        host=os.getenv("QB_RULES_HOST", "127.0.0.1"),
        port=int(os.getenv("QB_RULES_PORT", "8000")),
        database_url=os.getenv("QB_RULES_DATABASE_URL", "sqlite:///./data/qb_rules.db"),
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

    database_path = Path(raw_path)
    if not database_path.is_absolute():
        database_path = (Path.cwd() / database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.touch(exist_ok=True)


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

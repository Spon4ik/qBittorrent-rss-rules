from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_environment_settings


class Base(DeclarativeBase):
    pass


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False, "timeout": 30}
    return {}


def _configure_sqlite_engine(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()


@lru_cache
def get_engine() -> Engine:
    settings = get_environment_settings()
    engine = create_engine(
        settings.database_url,
        connect_args=_connect_args(settings.database_url),
        future=True,
    )
    _configure_sqlite_engine(engine)
    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_db_caches() -> None:
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def init_db() -> None:
    import app.models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_rule_columns()


def _ensure_rule_columns() -> None:
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return

    expected_rule_columns = {
        "release_year": "VARCHAR(16) NOT NULL DEFAULT ''",
        "include_release_year": "BOOLEAN NOT NULL DEFAULT 0",
        "additional_includes": "TEXT NOT NULL DEFAULT ''",
        "quality_include_tokens": "JSON NOT NULL DEFAULT '[]'",
        "quality_exclude_tokens": "JSON NOT NULL DEFAULT '[]'",
        "start_season": "INTEGER",
        "start_episode": "INTEGER",
        "jellyfin_search_existing_unseen": "BOOLEAN NOT NULL DEFAULT 0",
        "jellyfin_auto_disabled": "BOOLEAN NOT NULL DEFAULT 0",
        "jellyfin_known_episode_numbers": "JSON NOT NULL DEFAULT '[]'",
        "jellyfin_watched_episode_numbers": "JSON NOT NULL DEFAULT '[]'",
        "jellyfin_existing_episode_numbers": "JSON NOT NULL DEFAULT '[]'",
        "movie_completion_sources": "JSON NOT NULL DEFAULT '[]'",
        "movie_completion_auto_disabled": "BOOLEAN NOT NULL DEFAULT 0",
        "stremio_library_item_id": "VARCHAR(128)",
        "stremio_library_item_type": "VARCHAR(32)",
        "stremio_managed": "BOOLEAN NOT NULL DEFAULT 0",
        "stremio_auto_disabled": "BOOLEAN NOT NULL DEFAULT 0",
        "poster_url": "VARCHAR(512)",
        "language": "VARCHAR(32) NOT NULL DEFAULT ''",
    }
    expected_settings_columns = {
        "jackett_api_url": "VARCHAR(255)",
        "jackett_qb_url": "VARCHAR(255)",
        "jackett_api_key_encrypted": "TEXT",
        "jackett_language_overrides": "JSON NOT NULL DEFAULT '{}'",
        "jellyfin_db_path": "VARCHAR(512)",
        "jellyfin_user_name": "VARCHAR(255)",
        "jellyfin_auto_sync_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        "jellyfin_auto_sync_interval_seconds": "INTEGER NOT NULL DEFAULT 30",
        "jellyfin_auto_sync_last_run_at": "DATETIME",
        "jellyfin_auto_sync_last_status": "VARCHAR(32) NOT NULL DEFAULT 'idle'",
        "jellyfin_auto_sync_last_message": "TEXT NOT NULL DEFAULT ''",
        "stremio_local_storage_path": "VARCHAR(512)",
        "stremio_preferred_languages": "VARCHAR(255)",
        "stremio_stream_provider_manifests": "TEXT",
        "stremio_auto_sync_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        "stremio_auto_sync_interval_seconds": "INTEGER NOT NULL DEFAULT 30",
        "stremio_auto_sync_last_run_at": "DATETIME",
        "stremio_auto_sync_last_status": "VARCHAR(32) NOT NULL DEFAULT 'idle'",
        "stremio_auto_sync_last_message": "TEXT NOT NULL DEFAULT ''",
        "quality_profile_rules": "JSON NOT NULL DEFAULT '{}'",
        "saved_quality_profiles": "JSON NOT NULL DEFAULT '{}'",
        "default_feed_urls": "JSON NOT NULL DEFAULT '[]'",
        "default_sequential_download": "BOOLEAN NOT NULL DEFAULT 1",
        "default_first_last_piece_prio": "BOOLEAN NOT NULL DEFAULT 1",
        "search_result_view_mode": "VARCHAR(16) NOT NULL DEFAULT 'table'",
        "search_sort_criteria": "JSON NOT NULL DEFAULT '[]'",
        "rules_fetch_schedule_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "rules_fetch_schedule_interval_minutes": "INTEGER NOT NULL DEFAULT 360",
        "rules_fetch_schedule_scope": "VARCHAR(32) NOT NULL DEFAULT 'enabled'",
        "rules_fetch_schedule_last_run_at": "DATETIME",
        "rules_fetch_schedule_next_run_at": "DATETIME",
        "rules_fetch_schedule_last_status": "VARCHAR(32) NOT NULL DEFAULT 'idle'",
        "rules_fetch_schedule_last_message": "TEXT NOT NULL DEFAULT ''",
        "rules_page_view_mode": "VARCHAR(16) NOT NULL DEFAULT 'table'",
        "rules_page_sort_field": "VARCHAR(64) NOT NULL DEFAULT 'updated_at'",
        "rules_page_sort_direction": "VARCHAR(8) NOT NULL DEFAULT 'desc'",
    }
    expected_snapshot_columns = {
        "release_filter_cache_key": "TEXT",
        "release_filtered_count": "INTEGER",
        "release_fetched_count": "INTEGER",
        "exact_filtered_count": "INTEGER",
        "exact_fetched_count": "INTEGER",
    }

    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        if "rules" in existing_tables:
            existing_rule_columns = {item["name"] for item in inspector.get_columns("rules")}
            for column_name, column_def in expected_rule_columns.items():
                if column_name in existing_rule_columns:
                    continue
                connection.execute(text(f"ALTER TABLE rules ADD COLUMN {column_name} {column_def}"))
        if "app_settings" in existing_tables:
            existing_settings_columns = {
                item["name"] for item in inspector.get_columns("app_settings")
            }
            for column_name, column_def in expected_settings_columns.items():
                if column_name in existing_settings_columns:
                    continue
                connection.execute(
                    text(f"ALTER TABLE app_settings ADD COLUMN {column_name} {column_def}")
                )
        if "rule_search_snapshots" in existing_tables:
            existing_snapshot_columns = {
                item["name"] for item in inspector.get_columns("rule_search_snapshots")
            }
            for column_name, column_def in expected_snapshot_columns.items():
                if column_name in existing_snapshot_columns:
                    continue
                connection.execute(
                    text(f"ALTER TABLE rule_search_snapshots ADD COLUMN {column_name} {column_def}")
                )

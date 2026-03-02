from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_environment_settings


class Base(DeclarativeBase):
    pass


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


@lru_cache
def get_engine():
    settings = get_environment_settings()
    return create_engine(
        settings.database_url,
        connect_args=_connect_args(settings.database_url),
        future=True,
    )


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
    }
    expected_settings_columns = {
        "quality_profile_rules": "JSON NOT NULL DEFAULT '{}'",
        "saved_quality_profiles": "JSON NOT NULL DEFAULT '{}'",
        "default_feed_urls": "JSON NOT NULL DEFAULT '[]'",
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
            existing_settings_columns = {item["name"] for item in inspector.get_columns("app_settings")}
            for column_name, column_def in expected_settings_columns.items():
                if column_name in existing_settings_columns:
                    continue
                connection.execute(text(f"ALTER TABLE app_settings ADD COLUMN {column_name} {column_def}"))

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import _ensure_rule_columns, get_engine


def test_existing_rules_table_gains_snapshot_retry_columns(configured_app_env) -> None:
    del configured_app_env
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE rules (id VARCHAR(36) PRIMARY KEY)"))

    _ensure_rule_columns()

    columns = {column["name"] for column in inspect(engine).get_columns("rules")}
    assert {
        "snapshot_fetch_failure_count",
        "snapshot_fetch_next_attempt_at",
        "snapshot_fetch_last_attempt_at",
        "snapshot_fetch_last_error",
    }.issubset(columns)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO rules (id) VALUES ('legacy-rule')"))
        retries = connection.scalar(
            text(
                "SELECT snapshot_fetch_failure_count "
                "FROM rules WHERE id = 'legacy-rule'"
            )
        )
    assert retries == 0

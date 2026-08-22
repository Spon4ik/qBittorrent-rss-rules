from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.services.sqlite_maintenance import (
    _corrupt_objects_from_integrity,
    _is_reconstructible_acceleration,
    _print_report,
    analyze_database,
)


def _create_sample_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE rules (
            id TEXT PRIMARY KEY,
            rule_name TEXT NOT NULL,
            created_at DATETIME NOT NULL
        );

        CREATE TABLE rule_search_snapshots (
            rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,
            payload JSON NOT NULL,
            inline_search JSON NOT NULL,
            fetched_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );

        CREATE TABLE download_acceleration_jobs (
            id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL UNIQUE,
            info_hash TEXT,
            webseed_token TEXT UNIQUE,
            state TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );

        CREATE INDEX ix_download_acceleration_jobs_info_hash
        ON download_acceleration_jobs(info_hash);
        """
    )
    connection.execute(
        "INSERT INTO rules (id, rule_name, created_at) VALUES (?, ?, ?)",
        ("rule-1", "Тестовое правило", "2026-08-23T00:00:00+00:00"),
    )
    connection.execute(
        """
        INSERT INTO rule_search_snapshots
        (rule_id, payload, inline_search, fetched_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-1",
            json.dumps({"query": "Японский тест"}, ensure_ascii=False),
            "{}",
            "2026-08-23T00:00:00+00:00",
            "2026-08-23T00:00:00+00:00",
            "2026-08-23T00:00:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO download_acceleration_jobs
        (id, identity_key, info_hash, webseed_token, state, created_at, updated_at)
        VALUES (?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            "job-1",
            "qb:" + "a" * 40,
            "a" * 40,
            "discovered",
            "2026-08-23T00:00:00+00:00",
            "2026-08-23T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()


def test_analyze_healthy_database_returns_compact_healthy_report(tmp_path: Path) -> None:
    database = tmp_path / "healthy.db"
    _create_sample_database(database)

    report = analyze_database(database, full=True)

    assert report["status"] == "healthy"
    assert report["recommended_action"] == "none"
    assert report["physical_integrity"]["integrity_check_ok"] is True
    assert report["foreign_keys"]["count"] == 0
    assert report["orphan_snapshots"]["count"] == 0
    assert report["malformed_datetimes"]["count"] == 0
    assert report["critical_tables"]["rules"]["rows"] == 1
    assert report["download_acceleration_jobs"]["rows"] == 1
    assert report["download_acceleration_jobs"]["unreadable"] == 0


def test_analyze_reports_orphan_snapshot_and_malformed_datetime(tmp_path: Path) -> None:
    database = tmp_path / "logical-defects.db"
    _create_sample_database(database)
    connection = sqlite3.connect(database)
    connection.execute(
        """
        INSERT INTO rule_search_snapshots
        (rule_id, payload, inline_search, fetched_at, created_at, updated_at)
        VALUES (?, '{}', '{}', ?, ?, ?)
        """,
        ("missing-rule", "bad-fetched-at", "bad-created-at", "bad-updated-at"),
    )
    connection.commit()
    connection.close()

    report = analyze_database(database, full=True)

    assert report["status"] == "repairable_logical"
    assert report["recommended_action"] == "logical_cleanup"
    assert report["foreign_keys"]["count"] == 1
    assert report["orphan_snapshots"]["count"] == 1
    assert report["orphan_snapshots"]["sample"][0]["rule_id"] == "missing-rule"
    assert report["malformed_datetimes"]["count"] == 3
    malformed_columns = {
        item["column"] for item in report["malformed_datetimes"]["sample"]
    }
    assert malformed_columns == {"fetched_at", "created_at", "updated_at"}


def test_integrity_tree_root_is_attributed_to_schema_object(tmp_path: Path) -> None:
    database = tmp_path / "root-map.db"
    _create_sample_database(database)
    connection = sqlite3.connect(database)
    root_page = int(
        connection.execute(
            "SELECT rootpage FROM sqlite_schema WHERE name = 'download_acceleration_jobs'"
        ).fetchone()[0]
    )

    objects = _corrupt_objects_from_integrity(
        connection,
        [f"*** in database main ***\nTree {root_page} page 99 cell 0: 2nd reference to page 42"],
    )
    connection.close()

    assert objects == [
        {
            "type": "table",
            "name": "download_acceleration_jobs",
            "table": "download_acceleration_jobs",
            "root_page": root_page,
        }
    ]


def test_reconstructible_acceleration_requires_qb_identity_and_no_webseed() -> None:
    info_hash = "1" * 40
    assert _is_reconstructible_acceleration(
        {
            "identity_key": f"qb:{info_hash}",
            "info_hash": info_hash,
            "webseed_token": None,
        }
    ) is True
    assert _is_reconstructible_acceleration(
        {
            "identity_key": f"qb:{info_hash}",
            "info_hash": info_hash,
            "webseed_token": "active-token",
        }
    ) is False
    assert _is_reconstructible_acceleration(
        {
            "identity_key": "other",
            "info_hash": info_hash,
            "webseed_token": None,
        }
    ) is False


def test_print_report_escapes_non_ascii_for_console_safety(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "report.json"
    report = {"status": "healthy", "message": "Японский тест"}

    _print_report(report, output=output)

    captured = capsys.readouterr().out
    assert "Японский" not in captured
    assert "\\u042f" in captured
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["message"] == "Японский тест"

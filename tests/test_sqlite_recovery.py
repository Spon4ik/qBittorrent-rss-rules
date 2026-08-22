from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import app.services.sqlite_recovery as recovery
from app.services.sqlite_recovery import activate_candidate, rebuild_database
from app.services.sqlite_state_bundle import verify_bundle


def _create_database(path: Path, *, orphan_snapshot: bool = False) -> None:
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
    timestamp = "2026-08-23T00:00:00+00:00"
    connection.execute(
        "INSERT INTO rules (id, rule_name, created_at) VALUES (?, ?, ?)",
        ("rule-1", "Тестовое правило", timestamp),
    )
    connection.execute(
        """
        INSERT INTO rule_search_snapshots
        (rule_id, payload, inline_search, fetched_at, created_at, updated_at)
        VALUES (?, ?, '{}', ?, ?, ?)
        """,
        ("rule-1", json.dumps({"query": "Японский тест"}, ensure_ascii=False), timestamp, timestamp, timestamp),
    )
    if orphan_snapshot:
        connection.execute(
            """
            INSERT INTO rule_search_snapshots
            (rule_id, payload, inline_search, fetched_at, created_at, updated_at)
            VALUES (?, '{}', '{}', ?, ?, ?)
            """,
            ("missing-rule", timestamp, timestamp, timestamp),
        )
    info_hash = "a" * 40
    connection.execute(
        """
        INSERT INTO download_acceleration_jobs
        (id, identity_key, info_hash, webseed_token, state, created_at, updated_at)
        VALUES (?, ?, ?, NULL, 'discovered', ?, ?)
        """,
        ("job-1", f"qb:{info_hash}", info_hash, timestamp, timestamp),
    )
    connection.commit()
    connection.close()


def _count(path: Path, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    finally:
        connection.close()


def test_rebuild_database_creates_valid_new_candidate(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _create_database(source)

    report = rebuild_database(source, candidate)

    assert report["status"] == "candidate_ready"
    assert report["skipped_rows"] == []
    assert report["source_counts"] == report["candidate_counts"]
    assert report["validation"]["status"] == "healthy"
    assert report["validation"]["integrity_check_ok"] is True
    assert report["validation"]["foreign_key_violations"] == 0
    assert report["validation"]["malformed_datetimes"] == 0
    assert candidate.is_file()
    assert source.read_bytes() != b""


def test_rebuild_database_omits_only_proven_orphan_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _create_database(source, orphan_snapshot=True)

    report = rebuild_database(source, candidate)

    assert report["source_counts"]["rule_search_snapshots"] == 2
    assert report["candidate_counts"]["rule_search_snapshots"] == 1
    assert report["skipped_rows"] == [
        {
            "table": "rule_search_snapshots",
            "rowid": 2,
            "rule_id": "missing-rule",
            "reason": "orphan_missing_rule",
            "reconstructible": True,
        }
    ]
    assert report["validation"]["foreign_key_violations"] == 0
    assert _count(candidate, "rules") == 1
    assert _count(candidate, "rule_search_snapshots") == 1


def test_rebuild_database_refuses_existing_candidate(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _create_database(source)
    candidate.write_bytes(b"do-not-overwrite")

    with pytest.raises(FileExistsError):
        rebuild_database(source, candidate)

    assert candidate.read_bytes() == b"do-not-overwrite"


def test_rebuild_database_refuses_nonempty_wal_source(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    _create_database(source)
    Path(str(source) + "-wal").write_bytes(b"uncheckpointed")

    with pytest.raises(RuntimeError, match="non-empty SQLite WAL/journal"):
        rebuild_database(source, candidate)

    assert not candidate.exists()


def test_activate_candidate_creates_verified_rollback_and_replaces_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    target = tmp_path / "production.db"
    rollback = tmp_path / "rollback"
    _create_database(source)
    rebuild_database(source, candidate)

    _create_database(target, orphan_snapshot=True)
    old_target = target.read_bytes()

    report = activate_candidate(candidate, target, rollback_dir=rollback)

    assert report["status"] == "activated"
    assert report["validation"]["status"] == "healthy"
    assert report["validation"]["foreign_key_violations"] == 0
    assert target.read_bytes() == candidate.read_bytes()
    assert target.read_bytes() != old_target
    verification = verify_bundle(rollback)
    assert verification["status"] == "verified"


def test_activate_candidate_restores_target_if_post_swap_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    target = tmp_path / "production.db"
    rollback = tmp_path / "rollback"
    _create_database(source)
    rebuild_database(source, candidate)
    _create_database(target, orphan_snapshot=True)
    original_family = {
        suffix: Path(str(target) + suffix).read_bytes()
        for suffix in ("", "-wal", "-shm", "-journal")
        if Path(str(target) + suffix).exists()
    }

    real_analyze = recovery.analyze_database
    calls = 0

    def fail_after_swap(path: Path, *, full: bool, immutable: bool):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_analyze(path, full=full, immutable=immutable)
        return {
            "status": "needs_investigation",
            "recommended_action": "inspect_corruption",
            "physical_integrity": {"integrity_check_ok": False},
            "foreign_keys": {"count": 0},
            "malformed_datetimes": {"count": 0},
        }

    monkeypatch.setattr(recovery, "analyze_database", fail_after_swap)

    with pytest.raises(RuntimeError, match="verified pre-change SQLite state was restored"):
        activate_candidate(candidate, target, rollback_dir=rollback)

    restored_family = {
        suffix: Path(str(target) + suffix).read_bytes()
        for suffix in ("", "-wal", "-shm", "-journal")
        if Path(str(target) + suffix).exists()
    }
    assert restored_family == original_family
    assert verify_bundle(rollback)["status"] == "verified"

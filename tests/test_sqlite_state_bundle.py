from __future__ import annotations

from pathlib import Path

import pytest

from app.services import sqlite_state_bundle


def _write_family(database: Path, values: dict[str, bytes]) -> None:
    for suffix, content in values.items():
        Path(str(database) + suffix).write_bytes(content)


def test_backup_captures_and_verifies_sqlite_file_family(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    _write_family(
        database,
        {
            "": b"main-database",
            "-wal": b"wal-data",
            "-shm": b"shm-data",
        },
    )
    bundle = tmp_path / "rollback"

    report = sqlite_state_bundle.create_bundle(database, bundle)
    verification = sqlite_state_bundle.verify_bundle(bundle)

    assert report["status"] == "verified"
    assert verification["status"] == "verified"
    assert {item["suffix"] for item in verification["files"]} == {"", "-wal", "-shm"}
    assert (bundle / "manifest.json").is_file()


def test_backup_refuses_to_overwrite_existing_bundle(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    database.write_bytes(b"database")
    bundle = tmp_path / "rollback"
    bundle.mkdir()

    with pytest.raises(FileExistsError):
        sqlite_state_bundle.create_bundle(database, bundle)


def test_verify_rejects_tampered_bundle(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    database.write_bytes(b"database")
    bundle = tmp_path / "rollback"
    sqlite_state_bundle.create_bundle(database, bundle)

    (bundle / "database").write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="verification failed"):
        sqlite_state_bundle.verify_bundle(bundle)


def test_restore_replaces_exact_sqlite_family(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _write_family(source, {"": b"old-main", "-wal": b"old-wal"})
    bundle = tmp_path / "rollback"
    sqlite_state_bundle.create_bundle(source, bundle)

    target = tmp_path / "target.db"
    _write_family(target, {"": b"new-main", "-shm": b"new-shm"})

    report = sqlite_state_bundle.restore_bundle(bundle, target)

    assert report["status"] == "restored"
    assert target.read_bytes() == b"old-main"
    assert Path(str(target) + "-wal").read_bytes() == b"old-wal"
    assert not Path(str(target) + "-shm").exists()
    assert not Path(str(target) + "-journal").exists()


def test_failed_restore_restores_pre_restore_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.db"
    _write_family(source, {"": b"backup-main", "-wal": b"backup-wal"})
    bundle = tmp_path / "rollback"
    sqlite_state_bundle.create_bundle(source, bundle)

    target = tmp_path / "target.db"
    _write_family(target, {"": b"current-main", "-shm": b"current-shm"})

    original_copy2 = sqlite_state_bundle.shutil.copy2

    def fail_restore_copy(source_path: Path, target_path: Path):
        if str(target_path).endswith(".restore.tmp"):
            raise OSError("simulated restore copy failure")
        return original_copy2(source_path, target_path)

    monkeypatch.setattr(sqlite_state_bundle.shutil, "copy2", fail_restore_copy)

    with pytest.raises(OSError, match="simulated restore copy failure"):
        sqlite_state_bundle.restore_bundle(bundle, target)

    assert target.read_bytes() == b"current-main"
    assert Path(str(target) + "-shm").read_bytes() == b"current-shm"
    assert not Path(str(target) + "-wal").exists()


def test_bundle_handles_non_ascii_paths(tmp_path: Path) -> None:
    database = tmp_path / "данные.db"
    database.write_bytes("значение".encode())
    bundle = tmp_path / "резерв"

    report = sqlite_state_bundle.create_bundle(database, bundle)

    assert report["status"] == "verified"
    assert sqlite_state_bundle.verify_bundle(bundle)["status"] == "verified"

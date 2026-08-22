from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, cast

from app.services.sqlite_maintenance import (
    _indexed_values_for_rowid,
    _is_reconstructible_acceleration,
    _primary_key_index,
    _quote,
    analyze_database,
)
from app.services.sqlite_state_bundle import create_bundle, restore_bundle, verify_bundle

_ACCELERATION_TABLE = "download_acceleration_jobs"
_SNAPSHOT_TABLE = "rule_search_snapshots"
_RULES_TABLE = "rules"
_SIDECAR_SUFFIXES = ("", "-wal", "-shm", "-journal")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_source(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _source_sidecars(path: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for suffix in _SIDECAR_SUFFIXES[1:]:
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            items.append({"suffix": suffix, "size": candidate.stat().st_size})
    return items


def _assert_immutable_source_is_self_contained(path: Path) -> None:
    unsafe = [
        item
        for item in _source_sidecars(path)
        if item["suffix"] in {"-wal", "-journal"} and int(cast(int, item["size"])) > 0
    ]
    if unsafe:
        raise RuntimeError(
            "Recovery source has a non-empty SQLite WAL/journal. "
            "Checkpoint or capture it through the owning runtime before immutable recovery."
        )


def _schema_rows(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = connection.execute(
        """
        SELECT type, name, sql
        FROM sqlite_schema
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
        ORDER BY
          CASE type
            WHEN 'table' THEN 0
            WHEN 'index' THEN 1
            WHEN 'view' THEN 2
            WHEN 'trigger' THEN 3
            ELSE 4
          END,
          name
        """
    ).fetchall()
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


def _table_names(schema: list[tuple[str, str, str]]) -> list[str]:
    return [name for item_type, name, _sql in schema if item_type == "table"]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_xinfo({_quote(table)})").fetchall()
    return [str(row[1]) for row in rows if int(row[6] or 0) == 0]


def _insert_row(
    destination: sqlite3.Connection,
    table: str,
    columns: list[str],
    values: tuple[Any, ...],
) -> None:
    selected = ", ".join(_quote(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    destination.execute(
        f"INSERT INTO {_quote(table)} ({selected}) VALUES ({placeholders})",
        values,
    )


def _copy_ordinary_table(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    table: str,
) -> tuple[int, list[dict[str, object]]]:
    columns = _columns(source, table)
    selected = ", ".join(_quote(column) for column in columns)
    copied = 0
    try:
        rows = source.execute(f"SELECT {selected} FROM {_quote(table)}")
        for values in rows:
            _insert_row(destination, table, columns, tuple(values))
            copied += 1
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            f"Unclassified corruption while reading table {table}: {type(exc).__name__}: {exc}"
        ) from exc
    return copied, []


def _copy_snapshots(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
) -> tuple[int, list[dict[str, object]]]:
    columns = _columns(source, _SNAPSHOT_TABLE)
    selected = ", ".join(_quote(column) for column in columns)
    rule_id_index = columns.index("rule_id")
    copied = 0
    skipped: list[dict[str, object]] = []
    try:
        rows = source.execute(f"SELECT rowid, {selected} FROM {_quote(_SNAPSHOT_TABLE)}")
        for row in rows:
            rowid = int(row[0])
            values = tuple(row[1:])
            rule_id = values[rule_id_index]
            parent = source.execute(
                f"SELECT 1 FROM {_quote(_RULES_TABLE)} WHERE id = ?",
                (rule_id,),
            ).fetchone()
            if parent is None:
                skipped.append(
                    {
                        "table": _SNAPSHOT_TABLE,
                        "rowid": rowid,
                        "rule_id": str(rule_id),
                        "reason": "orphan_missing_rule",
                        "reconstructible": True,
                    }
                )
                continue
            _insert_row(destination, _SNAPSHOT_TABLE, columns, values)
            copied += 1
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            f"Unclassified corruption while reading {_SNAPSHOT_TABLE}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return copied, skipped


def _copy_acceleration_jobs(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
) -> tuple[int, list[dict[str, object]], int]:
    columns = _columns(source, _ACCELERATION_TABLE)
    selected = ", ".join(_quote(column) for column in columns)
    pk_index = _primary_key_index(source, _ACCELERATION_TABLE)
    if not pk_index:
        raise RuntimeError("download_acceleration_jobs primary-key index not found")
    try:
        identities = list(
            source.execute(
                f"SELECT rowid, id FROM {_quote(_ACCELERATION_TABLE)} "
                f"INDEXED BY {_quote(pk_index)} ORDER BY id"
            )
        )
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            "Cannot enumerate download_acceleration_jobs through its primary-key index"
        ) from exc

    copied = 0
    skipped: list[dict[str, object]] = []
    for raw_rowid, raw_id in identities:
        rowid = int(raw_rowid)
        try:
            values = source.execute(
                f"SELECT {selected} FROM {_quote(_ACCELERATION_TABLE)} WHERE rowid = ?",
                (rowid,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            indexed = _indexed_values_for_rowid(
                source,
                table=_ACCELERATION_TABLE,
                rowid=rowid,
            )
            indexed.setdefault("id", raw_id)
            reconstructible = _is_reconstructible_acceleration(indexed)
            if not reconstructible:
                raise RuntimeError(
                    "Unreadable download_acceleration_jobs row is not proven reconstructible: "
                    f"rowid={rowid} id={raw_id}"
                ) from exc
            skipped.append(
                {
                    "table": _ACCELERATION_TABLE,
                    "rowid": rowid,
                    "id": str(raw_id),
                    "identity_key": indexed.get("identity_key"),
                    "info_hash": indexed.get("info_hash"),
                    "webseed_token": indexed.get("webseed_token"),
                    "reason": "unreadable_reconstructible_qb_job",
                    "reconstructible": True,
                }
            )
            continue
        if values is None:
            indexed = _indexed_values_for_rowid(
                source,
                table=_ACCELERATION_TABLE,
                rowid=rowid,
            )
            indexed.setdefault("id", raw_id)
            if not _is_reconstructible_acceleration(indexed):
                raise RuntimeError(
                    "Missing download_acceleration_jobs row is not proven reconstructible: "
                    f"rowid={rowid} id={raw_id}"
                )
            skipped.append(
                {
                    "table": _ACCELERATION_TABLE,
                    "rowid": rowid,
                    "id": str(raw_id),
                    "identity_key": indexed.get("identity_key"),
                    "info_hash": indexed.get("info_hash"),
                    "webseed_token": indexed.get("webseed_token"),
                    "reason": "missing_reconstructible_qb_job",
                    "reconstructible": True,
                }
            )
            continue
        _insert_row(destination, _ACCELERATION_TABLE, columns, tuple(values))
        copied += 1
    return copied, skipped, len(identities)


def _source_table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Cannot count source table {table}") from exc
    return int(row[0]) if row is not None else 0


def _candidate_table_count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()
    return int(row[0]) if row is not None else 0


def _validate_candidate(
    candidate: Path,
    expected_counts: dict[str, int],
) -> dict[str, object]:
    report = analyze_database(candidate, full=True, immutable=True)
    if report["status"] != "healthy":
        raise RuntimeError(
            "Recovered candidate failed deterministic DB QA: "
            f"status={report['status']} action={report['recommended_action']}"
        )
    connection = _open_source(candidate)
    try:
        actual_counts = {
            table: _candidate_table_count(connection, table)
            for table in sorted(expected_counts)
        }
    finally:
        connection.close()
    if actual_counts != expected_counts:
        raise RuntimeError(
            f"Recovered candidate row counts differ from expected counts: "
            f"expected={expected_counts!r} actual={actual_counts!r}"
        )
    physical = cast(dict[str, object], report["physical_integrity"])
    foreign_keys = cast(dict[str, object], report["foreign_keys"])
    malformed_datetimes = cast(dict[str, object], report["malformed_datetimes"])
    return {
        "status": report["status"],
        "integrity_check_ok": physical["integrity_check_ok"],
        "foreign_key_violations": foreign_keys["count"],
        "malformed_datetimes": malformed_datetimes["count"],
        "table_counts": actual_counts,
    }


def rebuild_database(source_path: Path, candidate_path: Path) -> dict[str, object]:
    source_path = source_path.resolve()
    candidate_path = candidate_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if candidate_path.exists():
        raise FileExistsError(candidate_path)
    if source_path == candidate_path:
        raise ValueError("Recovery source and candidate must be different files")
    _assert_immutable_source_is_self_contained(source_path)

    source_hash_before = _sha256(source_path)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    source = _open_source(source_path)
    destination = sqlite3.connect(candidate_path)
    destination.execute("PRAGMA foreign_keys = OFF")
    skipped: list[dict[str, object]] = []
    copied_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    expected_counts: dict[str, int] = {}
    try:
        schema = _schema_rows(source)
        tables = _table_names(schema)
        for item_type, _name, sql in schema:
            if item_type == "table":
                destination.execute(sql)

        for table in tables:
            if table == _ACCELERATION_TABLE:
                copied, table_skipped, source_count = _copy_acceleration_jobs(
                    source,
                    destination,
                )
            elif table == _SNAPSHOT_TABLE and _RULES_TABLE in tables:
                source_count = _source_table_count(source, table)
                copied, table_skipped = _copy_snapshots(source, destination)
            else:
                source_count = _source_table_count(source, table)
                copied, table_skipped = _copy_ordinary_table(source, destination, table)
            copied_counts[table] = copied
            source_counts[table] = source_count
            skipped.extend(table_skipped)
            expected_counts[table] = source_count - len(table_skipped)
            if copied != expected_counts[table]:
                raise RuntimeError(
                    f"Unexpected row delta while rebuilding {table}: "
                    f"source={source_count} copied={copied} skipped={len(table_skipped)}"
                )

        for item_type, _name, sql in schema:
            if item_type != "table":
                destination.execute(sql)
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        candidate_path.unlink(missing_ok=True)
        raise
    destination.close()
    source.close()

    source_hash_after = _sha256(source_path)
    if source_hash_before != source_hash_after:
        candidate_path.unlink(missing_ok=True)
        raise RuntimeError("Recovery source changed while logical rebuild was running")

    try:
        validation = _validate_candidate(candidate_path, expected_counts)
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise

    return {
        "status": "candidate_ready",
        "action": "logical_rebuild",
        "source": str(source_path),
        "candidate": str(candidate_path),
        "source_sha256": source_hash_before,
        "candidate_sha256": _sha256(candidate_path),
        "source_counts": source_counts,
        "candidate_counts": copied_counts,
        "skipped_rows": skipped,
        "validation": validation,
    }


def _family_hashes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for suffix in _SIDECAR_SUFFIXES:
        item = Path(str(path) + suffix)
        if item.exists():
            result[suffix] = _sha256(item)
    return result


def _assert_target_matches_bundle(target: Path, bundle: Path) -> None:
    verification = verify_bundle(bundle)
    files = cast(list[dict[str, object]], verification["files"])
    expected = {
        str(item["suffix"]): str(item["sha256"])
        for item in files
    }
    actual = _family_hashes(target)
    if actual != expected:
        raise RuntimeError(
            "Production SQLite state changed after rollback bundle creation; "
            "refusing activation"
        )


def activate_candidate(
    candidate_path: Path,
    target_path: Path,
    *,
    rollback_dir: Path | None = None,
) -> dict[str, object]:
    candidate_path = candidate_path.resolve()
    target_path = target_path.resolve()
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    if not target_path.is_file():
        raise FileNotFoundError(target_path)
    if candidate_path == target_path:
        raise ValueError("Candidate and production target must be different files")

    candidate_report = analyze_database(candidate_path, full=True, immutable=True)
    if candidate_report["status"] != "healthy":
        raise RuntimeError(
            f"Refusing to activate unhealthy candidate: {candidate_report['status']}"
        )

    rollback = create_bundle(target_path, rollback_dir)
    rollback_path = Path(str(rollback["bundle"]))
    _assert_target_matches_bundle(target_path, rollback_path)

    staged = target_path.parent / f".{target_path.name}.recovery-candidate.tmp"
    staged.unlink(missing_ok=True)
    shutil.copy2(candidate_path, staged)
    candidate_hash = _sha256(candidate_path)
    if _sha256(staged) != candidate_hash:
        staged.unlink(missing_ok=True)
        raise RuntimeError("Staged recovery candidate hash mismatch")

    try:
        for suffix in _SIDECAR_SUFFIXES:
            Path(str(target_path) + suffix).unlink(missing_ok=True)
        os.replace(staged, target_path)
        activated = analyze_database(target_path, full=True, immutable=True)
        if activated["status"] != "healthy":
            raise RuntimeError(
                f"Activated database failed deterministic DB QA: {activated['status']}"
            )
        if _sha256(target_path) != candidate_hash:
            raise RuntimeError("Activated database hash differs from validated candidate")
    except Exception as exc:
        staged.unlink(missing_ok=True)
        try:
            restore_bundle(rollback_path, target_path)
        except Exception as rollback_exc:
            raise RuntimeError(
                "Recovery activation failed and automatic rollback also failed"
            ) from rollback_exc
        raise RuntimeError(
            "Recovery activation failed; verified pre-change SQLite state was restored"
        ) from exc

    physical = cast(dict[str, object], activated["physical_integrity"])
    foreign_keys = cast(dict[str, object], activated["foreign_keys"])
    malformed_datetimes = cast(dict[str, object], activated["malformed_datetimes"])
    return {
        "status": "activated",
        "action": "activate_candidate",
        "candidate": str(candidate_path),
        "target": str(target_path),
        "candidate_sha256": candidate_hash,
        "rollback_bundle": str(rollback_path),
        "validation": {
            "status": activated["status"],
            "integrity_check_ok": physical["integrity_check_ok"],
            "foreign_key_violations": foreign_keys["count"],
            "malformed_datetimes": malformed_datetimes["count"],
        },
    }


def _print_report(report: dict[str, object], output: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic logical rebuild and reversible activation for SQLite."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("candidate", type=Path)
    prepare.add_argument("--output", type=Path)

    activate = subparsers.add_parser("activate")
    activate.add_argument("candidate", type=Path)
    activate.add_argument("target", type=Path)
    activate.add_argument("--rollback-dir", type=Path)
    activate.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        report = rebuild_database(args.source, args.candidate)
    else:
        report = activate_candidate(
            args.candidate,
            args.target,
            rollback_dir=args.rollback_dir,
        )
    _print_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

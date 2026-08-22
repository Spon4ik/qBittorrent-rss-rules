from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

_TREE_ROOT_RE = re.compile(r"\bTree\s+(\d+)\b")
_CRITICAL_TABLES = ("rules", "rule_search_snapshots", "download_acceleration_jobs")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _open_read_only(path: Path, *, immutable: bool) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    if immutable:
        uri += "&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _pragma_rows(connection: sqlite3.Connection, pragma: str) -> tuple[list[tuple[Any, ...]], str | None]:
    try:
        return connection.execute(pragma).fetchall(), None
    except sqlite3.DatabaseError as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _integrity_messages(rows: list[tuple[Any, ...]]) -> list[str]:
    return [str(row[0]) for row in rows if row]


def _schema_object_for_root(
    connection: sqlite3.Connection,
    root_page: int,
) -> dict[str, object] | None:
    row = connection.execute(
        "SELECT type, name, tbl_name, rootpage FROM sqlite_schema WHERE rootpage = ?",
        (root_page,),
    ).fetchone()
    if row is None:
        return None
    return {
        "type": str(row[0]),
        "name": str(row[1]),
        "table": str(row[2]),
        "root_page": int(row[3]),
    }


def _corrupt_objects_from_integrity(
    connection: sqlite3.Connection,
    messages: list[str],
) -> list[dict[str, object]]:
    roots: set[int] = set()
    for message in messages:
        roots.update(int(value) for value in _TREE_ROOT_RE.findall(message))
    objects: list[dict[str, object]] = []
    for root_page in sorted(roots):
        item = _schema_object_for_root(connection, root_page)
        if item is None:
            item = {"type": "unknown", "name": "", "table": "", "root_page": root_page}
        objects.append(item)
    return objects


def _table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_count(connection: sqlite3.Connection, table: str) -> tuple[int | None, str | None]:
    try:
        value = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()
        return int(value[0]) if value is not None else 0, None
    except sqlite3.DatabaseError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _foreign_key_violations(connection: sqlite3.Connection) -> tuple[list[dict[str, object]], str | None]:
    rows, error = _pragma_rows(connection, "PRAGMA foreign_key_check")
    violations = [
        {
            "table": str(row[0]),
            "rowid": row[1],
            "parent": str(row[2]),
            "foreign_key": row[3],
        }
        for row in rows
    ]
    return violations, error


def _orphan_snapshots(connection: sqlite3.Connection, *, limit: int = 10) -> tuple[dict[str, object], str | None]:
    try:
        count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM rule_search_snapshots AS snapshot
                LEFT JOIN rules AS rule ON rule.id = snapshot.rule_id
                WHERE rule.id IS NULL
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT snapshot.rowid, snapshot.rule_id, CAST(snapshot.fetched_at AS TEXT)
            FROM rule_search_snapshots AS snapshot
            LEFT JOIN rules AS rule ON rule.id = snapshot.rule_id
            WHERE rule.id IS NULL
            ORDER BY snapshot.rowid
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {
            "count": count,
            "sample": [
                {"rowid": row[0], "rule_id": str(row[1]), "fetched_at": str(row[2])}
                for row in rows
            ],
        }, None
    except sqlite3.DatabaseError as exc:
        return {"count": None, "sample": []}, f"{type(exc).__name__}: {exc}"


def _datetime_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_xinfo({_quote(table)})").fetchall()
    columns: list[str] = []
    for row in rows:
        declared_type = str(row[2] or "").upper()
        if "DATE" in declared_type or "TIME" in declared_type:
            columns.append(str(row[1]))
    return columns


def _malformed_datetime_values(
    connection: sqlite3.Connection,
    *,
    sample_limit: int = 10,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    malformed: list[dict[str, object]] = []
    read_errors: list[dict[str, str]] = []
    total = 0
    for table in _table_names(connection):
        for column in _datetime_columns(connection, table):
            try:
                rows = connection.execute(
                    f"SELECT rowid, CAST({_quote(column)} AS TEXT) "
                    f"FROM {_quote(table)} WHERE {_quote(column)} IS NOT NULL"
                )
                for rowid, raw in rows:
                    try:
                        datetime.fromisoformat(str(raw))
                    except (TypeError, ValueError):
                        total += 1
                        if len(malformed) < sample_limit:
                            malformed.append(
                                {
                                    "table": table,
                                    "column": column,
                                    "rowid": rowid,
                                    "value_prefix": str(raw)[:80],
                                }
                            )
            except sqlite3.DatabaseError as exc:
                read_errors.append(
                    {
                        "table": table,
                        "column": column,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return {"count": total, "sample": malformed}, read_errors


def _primary_key_index(connection: sqlite3.Connection, table: str) -> str | None:
    for row in connection.execute(f"PRAGMA index_list({_quote(table)})"):
        if str(row[3]) == "pk":
            return str(row[1])
    return None


def _indexed_values_for_rowid(
    connection: sqlite3.Connection,
    *,
    table: str,
    rowid: int,
) -> dict[str, object]:
    values: dict[str, object] = {}
    for index_row in connection.execute(f"PRAGMA index_list({_quote(table)})"):
        index_name = str(index_row[1])
        columns = [
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({_quote(index_name)})")
            if row[2] is not None
        ]
        if not columns:
            continue
        selected = ", ".join(_quote(column) for column in columns)
        try:
            row = connection.execute(
                f"SELECT {selected} FROM {_quote(table)} INDEXED BY {_quote(index_name)} "
                "WHERE rowid = ?",
                (rowid,),
            ).fetchone()
        except sqlite3.DatabaseError:
            continue
        if row is not None:
            values.update(dict(zip(columns, row, strict=True)))
    return values


def _is_reconstructible_acceleration(values: dict[str, object]) -> bool:
    info_hash = str(values.get("info_hash") or "").strip().casefold()
    identity_key = str(values.get("identity_key") or "").strip().casefold()
    webseed_token = str(values.get("webseed_token") or "").strip()
    return bool(info_hash and identity_key == f"qb:{info_hash}" and not webseed_token)


def _acceleration_salvage(connection: sqlite3.Connection, *, sample_limit: int = 10) -> dict[str, object]:
    table = "download_acceleration_jobs"
    if table not in _table_names(connection):
        return {"rows": 0, "readable": 0, "unreadable": 0, "sample": []}
    pk_index = _primary_key_index(connection, table)
    if not pk_index:
        return {
            "rows": None,
            "readable": None,
            "unreadable": None,
            "sample": [],
            "error": "primary-key index not found",
        }
    try:
        keys = list(
            connection.execute(
                f"SELECT rowid, id FROM {_quote(table)} INDEXED BY {_quote(pk_index)} ORDER BY id"
            )
        )
    except sqlite3.DatabaseError as exc:
        return {
            "rows": None,
            "readable": None,
            "unreadable": None,
            "sample": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    readable = 0
    unreadable: list[dict[str, object]] = []
    for rowid, item_id in keys:
        try:
            row = connection.execute(
                f"SELECT * FROM {_quote(table)} WHERE rowid = ?",
                (rowid,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            values = _indexed_values_for_rowid(connection, table=table, rowid=int(rowid))
            values.setdefault("id", item_id)
            if len(unreadable) < sample_limit:
                unreadable.append(
                    {
                        "rowid": int(rowid),
                        "id": str(item_id),
                        "identity_key": values.get("identity_key"),
                        "info_hash": values.get("info_hash"),
                        "webseed_token": values.get("webseed_token"),
                        "reconstructible": _is_reconstructible_acceleration(values),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            continue
        if row is None:
            if len(unreadable) < sample_limit:
                unreadable.append(
                    {
                        "rowid": int(rowid),
                        "id": str(item_id),
                        "reconstructible": False,
                        "error": "row missing",
                    }
                )
            continue
        readable += 1
    return {
        "rows": len(keys),
        "readable": readable,
        "unreadable": len(keys) - readable,
        "sample": unreadable,
    }


def analyze_database(
    path: Path,
    *,
    full: bool = False,
    immutable: bool = True,
) -> dict[str, object]:
    path = path.resolve()
    connection = _open_read_only(path, immutable=immutable)
    try:
        quick_rows, quick_error = _pragma_rows(connection, "PRAGMA quick_check")
        quick_messages = _integrity_messages(quick_rows)
        if full:
            integrity_rows, integrity_error = _pragma_rows(connection, "PRAGMA integrity_check")
            integrity_messages = _integrity_messages(integrity_rows)
        else:
            integrity_error = quick_error
            integrity_messages = quick_messages
        corrupt_objects = _corrupt_objects_from_integrity(connection, integrity_messages)
        foreign_keys, foreign_key_error = _foreign_key_violations(connection)
        orphan_snapshots, orphan_error = _orphan_snapshots(connection)
        malformed_datetimes, datetime_read_errors = _malformed_datetime_values(connection)
        table_counts: dict[str, dict[str, object]] = {}
        for table in _CRITICAL_TABLES:
            if table not in _table_names(connection):
                continue
            count, error = _table_count(connection, table)
            table_counts[table] = {"rows": count, "error": error}
        acceleration = _acceleration_salvage(connection)

        physical_ok = (
            quick_error is None
            and quick_messages == ["ok"]
            and integrity_error is None
            and integrity_messages == ["ok"]
        )
        logical_ok = not foreign_keys and int(malformed_datetimes["count"]) == 0
        unreadable = acceleration.get("unreadable")
        sample = acceleration.get("sample")
        reconstructible = bool(
            isinstance(unreadable, int)
            and unreadable > 0
            and isinstance(sample, list)
            and len(sample) == unreadable
            and all(bool(item.get("reconstructible")) for item in sample if isinstance(item, dict))
        )
        if physical_ok and logical_ok:
            status = "healthy"
            recommended_action = "none"
        elif not physical_ok and reconstructible:
            status = "recoverable"
            recommended_action = "logical_rebuild"
        elif not physical_ok:
            status = "needs_investigation"
            recommended_action = "inspect_corruption"
        else:
            status = "repairable_logical"
            recommended_action = "logical_cleanup"

        return {
            "status": status,
            "recommended_action": recommended_action,
            "database": str(path),
            "physical_integrity": {
                "quick_check_ok": quick_error is None and quick_messages == ["ok"],
                "integrity_check_ok": integrity_error is None and integrity_messages == ["ok"],
                "quick_check_error": quick_error,
                "integrity_check_error": integrity_error,
                "messages": integrity_messages[:20],
                "corrupt_objects": corrupt_objects,
            },
            "foreign_keys": {
                "count": len(foreign_keys),
                "sample": foreign_keys[:10],
                "error": foreign_key_error,
            },
            "orphan_snapshots": {**orphan_snapshots, "error": orphan_error},
            "malformed_datetimes": malformed_datetimes,
            "datetime_read_errors": datetime_read_errors[:10],
            "critical_tables": table_counts,
            "download_acceleration_jobs": acceleration,
        }
    finally:
        connection.close()


def _print_report(report: dict[str, object], *, output: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic SQLite integrity diagnostics.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--full", action="store_true", help="Run full PRAGMA integrity_check.")
    parser.add_argument(
        "--no-immutable",
        action="store_true",
        help="Do not use SQLite immutable read-only mode. Intended only inside the owning runtime.",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = analyze_database(
        args.database,
        full=bool(args.full),
        immutable=not bool(args.no_immutable),
    )
    _print_report(report, output=args.output)
    return 0 if report["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())

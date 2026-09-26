from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy.engine import make_url


def assert_test_database_is_temporary(database_url: str) -> None:
    """Reject file-backed SQLite URLs outside the OS temporary directory."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return

    database = url.database or ""
    if database == ":memory:" or url.query.get("mode") == "memory":
        return
    if database.startswith("file:"):
        database = database.removeprefix("file:")
        if database.startswith(":memory:"):
            return
    if not database:
        raise RuntimeError("Tests may only open SQLite databases in a temporary directory")

    database_path = Path(unquote(database)).resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    try:
        database_path.relative_to(temporary_root)
    except ValueError as exc:
        raise RuntimeError(
            "Tests may only open SQLite databases in a temporary directory; "
            f"refused {database_path}"
        ) from exc

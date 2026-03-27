from __future__ import annotations

from pathlib import Path

STATIC_ASSET_FILENAMES: tuple[str, ...] = ("app.css", "app.js")
STATIC_ASSET_DIR = Path(__file__).resolve().parent.parent / "static"


def compute_static_asset_version(static_dir: Path | None = None) -> str:
    resolved_static_dir = static_dir or STATIC_ASSET_DIR
    version_parts: list[str] = []
    for filename in STATIC_ASSET_FILENAMES:
        file_path = resolved_static_dir / filename
        if not file_path.exists():
            continue
        version_parts.append(str(file_path.stat().st_mtime_ns))
    return "-".join(version_parts)

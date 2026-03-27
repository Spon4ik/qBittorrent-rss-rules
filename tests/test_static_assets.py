from __future__ import annotations

import os

from app.services.static_assets import compute_static_asset_version


def test_compute_static_asset_version_tracks_app_asset_mtime(tmp_path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    css_path = static_dir / "app.css"
    js_path = static_dir / "app.js"
    css_path.write_text("body { color: #111; }\n", encoding="utf-8")
    js_path.write_text("console.log('initial');\n", encoding="utf-8")

    initial_version = compute_static_asset_version(static_dir)
    assert initial_version

    bumped_mtime_ns = js_path.stat().st_mtime_ns + 1_000_000_000
    os.utime(js_path, ns=(js_path.stat().st_atime_ns, bumped_mtime_ns))

    updated_version = compute_static_asset_version(static_dir)

    assert updated_version != initial_version

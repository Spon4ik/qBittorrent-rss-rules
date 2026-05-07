from __future__ import annotations

import os
from pathlib import Path

from app.services.static_assets import compute_static_asset_version

APP_CSS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "app.css"


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


def test_app_css_declares_responsive_shell_contract() -> None:
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    for token in (
        "--shell-gutter",
        "--shell-max",
        "--shell-wide-max",
        "--content-padding",
        "--content-padding-wide",
        "--density-gap",
        "--density-gap-tight",
    ):
        assert token in css

    assert "width: calc(100% - (2 * var(--shell-gutter)))" in css
    assert "max-width: var(--shell-max)" in css
    assert "max-width: var(--shell-wide-max)" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (min-width: 901px) and (max-width: 1400px)" in css

    for utility in (
        ".layout-stack",
        ".layout-stack--tight",
        ".layout-cluster",
        ".layout-density-compact",
    ):
        assert utility in css

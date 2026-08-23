from __future__ import annotations

from pathlib import Path

from app.services.static_assets import STATIC_ASSET_FILENAMES

ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "app" / "templates" / "base.html"
COMPONENT_CSS = ROOT / "app" / "static" / "components.css"


def test_shared_component_styles_are_loaded_and_cache_versioned() -> None:
    template = BASE_TEMPLATE.read_text(encoding="utf-8")

    assert "components.css" in template
    assert "components.css" in STATIC_ASSET_FILENAMES


def test_dropdown_family_uses_semantic_palette_instead_of_light_only_surfaces() -> None:
    css = COMPONENT_CSS.read_text(encoding="utf-8")

    assert ".checkbox-dropdown > summary" in css
    assert ".checkbox-dropdown-menu" in css
    assert ".search-multiselect-panel" in css
    assert ".feed-option-list" in css
    assert ".feed-option" in css
    assert "background: var(--surface-raised)" in css
    assert "background: var(--surface)" in css
    assert "color: var(--ink)" in css
    assert ':root[data-theme="dark"] .feed-option:hover' in css


def test_dropdown_family_has_shared_keyboard_focus_treatment() -> None:
    css = COMPONENT_CSS.read_text(encoding="utf-8")

    assert ".checkbox-dropdown > summary:focus-visible" in css
    assert ".search-multiselect > summary:focus-visible" in css
    assert "outline: 3px solid var(--accent)" in css

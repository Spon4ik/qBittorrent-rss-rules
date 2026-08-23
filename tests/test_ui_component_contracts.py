from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_component_contracts as components  # noqa: E402
import ui_interactions as interactions  # noqa: E402
import ui_invariants as ui  # noqa: E402
import ui_suite_qa as suite  # noqa: E402


def _metric(**overrides: object) -> dict[str, object]:
    metric: dict[str, object] = {
        "visible": True,
        "text": "Readable control",
        "disabled": False,
        "contrast": 7.0,
        "placeholderContrast": None,
        "clipsTextHorizontally": False,
        "clipsTextVertically": False,
        "insideHorizontalScroller": False,
        "escapesViewport": False,
        "keyboardFocusable": True,
    }
    metric.update(overrides)
    return metric


def test_component_coverage_rejects_visible_unclassified_controls() -> None:
    controls = [
        {"family": "button", "tag": "button", "text": "Save"},
        {"family": None, "tag": "div", "text": "Mystery control"},
    ]

    with pytest.raises(ui.UIInvariantError, match="not assigned"):
        components.assert_component_coverage(controls)


def test_component_family_counts_are_exhaustive_not_sampled() -> None:
    controls = [
        {"family": "checkbox-dropdown"},
        {"family": "checkbox-dropdown"},
        {"family": "native-select"},
    ]

    assert components.family_counts(controls) == {
        "checkbox-dropdown": 2,
        "native-select": 1,
    }
    assert suite.EXHAUSTIVE_INTERACTION_LIMIT >= 1000
    assert not hasattr(suite, "MAX_INTERACTIONS_PER_PAGE")


def test_dedicated_surface_exclusions_have_explicit_replacement_contracts() -> None:
    assert set(suite.DEDICATED_SURFACE_CONTRACTS) == set(
        interactions.DEDICATED_SURFACE_SELECTORS
    )
    assert suite.DEDICATED_SURFACE_CONTRACTS[".rule-diagnostics-disclosure"] == "UI-02"
    assert suite.DEDICATED_SURFACE_CONTRACTS["[data-result-toolbar-menu]"] == "UI-03"


def test_readability_rejects_low_contrast_clipping_and_viewport_escape() -> None:
    with pytest.raises(ui.UIInvariantError, match="contrast"):
        components.assert_control_readability(_metric(contrast=2.1), label="Language")

    with pytest.raises(ui.UIInvariantError, match="horizontally clipped"):
        components.assert_control_readability(
            _metric(clipsTextHorizontally=True),
            label="Language",
        )

    with pytest.raises(ui.UIInvariantError, match="escapes the viewport"):
        components.assert_control_readability(
            _metric(escapesViewport=True),
            label="Language",
        )


def test_readability_requires_keyboard_focus_for_enabled_interactive_controls() -> None:
    with pytest.raises(ui.UIInvariantError, match="keyboard-focusable"):
        components.assert_control_readability(
            _metric(keyboardFocusable=False),
            label="Dropdown",
        )

    components.assert_control_readability(
        _metric(disabled=True, keyboardFocusable=False, contrast=3.1),
        label="Disabled dropdown",
    )


def test_open_menu_contract_rejects_occlusion_and_unreadable_descendants() -> None:
    with pytest.raises(ui.UIInvariantError, match="occluded"):
        components.assert_open_menu_readability(
            {
                "open": True,
                "panelVisible": True,
                "panelEscapesViewport": False,
                "panelTopmost": False,
                "descendants": [],
            },
            label="Language dropdown",
        )

    with pytest.raises(ui.UIInvariantError, match="contrast"):
        components.assert_open_menu_readability(
            {
                "open": True,
                "panelVisible": True,
                "panelEscapesViewport": False,
                "panelTopmost": True,
                "descendants": [_metric(text="Russian", contrast=1.5)],
            },
            label="Language dropdown",
        )


def test_component_matrix_covers_light_dark_and_checkbox_dropdown_family() -> None:
    assert set(suite.COMPONENT_THEMES) == {"light", "dark"}
    assert len(suite.COMPONENT_VIEWPORTS) >= 3
    assert "checkbox-dropdown" in components.MENU_FAMILIES
    assert "search-multiselect" in components.MENU_FAMILIES
    assert "toolbar-menu" in components.MENU_FAMILIES

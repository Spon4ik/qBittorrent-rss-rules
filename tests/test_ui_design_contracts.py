from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_design_contracts as design  # noqa: E402
import ui_invariants as ui  # noqa: E402


def test_palette_bucket_groups_shared_family_by_theme_state_and_input_subtype() -> None:
    select = {"family": "native-select", "disabled": False}
    text_input = {"family": "input", "type": "text", "disabled": False}

    assert design.palette_bucket(select, theme="dark", state="normal") == (
        "dark:native-select:enabled:normal"
    )
    assert design.palette_bucket(text_input, theme="light", state="focus") == (
        "light:input:text:enabled:focus"
    )


def test_non_strict_presentation_family_does_not_force_pixel_identical_palette() -> None:
    assert design.palette_bucket(
        {"family": "button", "disabled": False},
        theme="dark",
        state="normal",
    ) is None


def test_shared_palette_accepts_same_computed_tokens_across_pages() -> None:
    observations = [
        design.PaletteObservation(
            bucket="dark:checkbox-dropdown:enabled:normal",
            signature=("rgb(236, 243, 241)", "rgba(36, 55, 59, 1.000)"),
            label="new-rule:Language",
        ),
        design.PaletteObservation(
            bucket="dark:checkbox-dropdown:enabled:normal",
            signature=("rgb(236, 243, 241)", "rgba(36, 55, 59, 1.000)"),
            label="edit-rule:Affected feeds",
        ),
    ]

    design.assert_palette_consistency(observations)


def test_shared_palette_rejects_page_specific_drift() -> None:
    observations = [
        design.PaletteObservation(
            bucket="dark:checkbox-dropdown:enabled:normal",
            signature=("rgb(236, 243, 241)", "rgba(36, 55, 59, 1.000)"),
            label="new-rule:Language",
        ),
        design.PaletteObservation(
            bucket="dark:checkbox-dropdown:enabled:normal",
            signature=("rgb(19, 37, 40)", "rgba(255, 252, 246, 1.000)"),
            label="edit-rule:Affected feeds",
        ),
    ]

    with pytest.raises(ui.UIInvariantError, match="palette drift"):
        design.assert_palette_consistency(observations)

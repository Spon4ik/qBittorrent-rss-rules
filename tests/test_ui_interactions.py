from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_interactions as interactions  # noqa: E402
import ui_invariants as ui  # noqa: E402


def _container(
    *,
    left: float,
    top: float = 10,
    text: str = "Actions",
) -> dict[str, object]:
    return {
        "left": left,
        "top": top,
        "right": left + 40,
        "bottom": top + 20,
        "width": 40,
        "height": 20,
        "text": text,
        "visible": True,
    }


def _action_group(
    key: str,
    *,
    left: float,
    top: float = 10,
    text: str = "Actions",
) -> dict[str, object]:
    return {
        "key": key,
        "container": _container(left=left, top=top, text=text),
    }


def _context(
    *,
    parent_left: float = 10,
    parent_top: float = 20,
    parent_width: float = 100,
    parent_height: float = 30,
) -> dict[str, object]:
    return {
        "parent": {
            "left": parent_left,
            "top": parent_top,
            "width": parent_width,
            "height": parent_height,
        },
        "previous": None,
        "next": {
            "left": 10,
            "top": 60,
            "width": 100,
            "height": 20,
        },
    }


def test_action_group_stability_allows_one_pixel_but_rejects_three() -> None:
    before = [_action_group("main>div:nth-of-type(1)", left=10, text="Save / Sync")]
    within = [_action_group("main>div:nth-of-type(1)", left=11, text="Save / Sync")]
    moved = [_action_group("main>div:nth-of-type(1)", left=13, text="Save / Sync")]

    interactions.assert_action_group_positions_stable(
        before,
        within,
        axes=("left",),
    )

    with pytest.raises(ui.UIInvariantError, match=r"\+3.0px"):
        interactions.assert_action_group_positions_stable(
            before,
            moved,
            axes=("left",),
        )


def test_action_group_stability_matches_only_same_dom_keys() -> None:
    before = [_action_group("old", left=10)]
    after = [_action_group("new", left=80)]

    interactions.assert_action_group_positions_stable(
        before,
        after,
        axes=("left", "top"),
    )


def test_overlay_context_reflow_is_reported() -> None:
    before = _context()
    stable = _context(parent_left=11)
    shifted = _context(parent_height=38)

    interactions.assert_surface_context_stable(before, stable)

    with pytest.raises(ui.UIInvariantError, match="parent.height"):
        interactions.assert_surface_context_stable(before, shifted)


def test_dedicated_surfaces_are_not_reaudited_by_generic_layer() -> None:
    assert ".rule-diagnostics-disclosure" in interactions.DEDICATED_SURFACE_SELECTORS
    assert "[data-result-toolbar-menu]" in interactions.DEDICATED_SURFACE_SELECTORS

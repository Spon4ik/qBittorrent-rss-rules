from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_invariants as ui  # noqa: E402


def _snapshot(
    *,
    width: float = 100,
    scroll_width: float = 100,
    elements: dict[str, dict[str, object]] | None = None,
    groups: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    return {
        "viewport": {"width": width, "height": 100},
        "document": {
            "scrollWidth": scroll_width,
            "clientWidth": width,
            "scrollHeight": 100,
            "clientHeight": 100,
        },
        "elements": elements or {},
        "groups": groups or {},
    }


def _rect(
    *,
    x: float,
    y: float = 0,
    width: float = 10,
    height: float = 10,
    text: str = "control",
) -> dict[str, object]:
    return {
        "x": x,
        "y": y,
        "left": x,
        "top": y,
        "right": x + width,
        "bottom": y + height,
        "width": width,
        "height": height,
        "visible": True,
        "text": text,
        "tag": "button",
        "id": "",
    }


def test_horizontal_overflow_tolerance_is_deterministic() -> None:
    ui.assert_no_page_horizontal_overflow(_snapshot(width=100, scroll_width=101))

    with pytest.raises(ui.UIInvariantError, match="horizontal overflow=3.0px"):
        ui.assert_no_page_horizontal_overflow(_snapshot(width=100, scroll_width=103))


def test_element_stability_catches_three_pixel_regression() -> None:
    before = _snapshot(elements={"toolbar": _rect(x=10)})
    within_tolerance = _snapshot(elements={"toolbar": _rect(x=11)})
    moved = _snapshot(elements={"toolbar": _rect(x=13)})

    ui.assert_element_stable(before, within_tolerance, "toolbar", axes=("x",))

    with pytest.raises(ui.UIInvariantError, match=r"\+3.0px"):
        ui.assert_element_stable(before, moved, "toolbar", axes=("x",))


def test_group_stability_reports_the_moved_control() -> None:
    before = _snapshot(
        groups={
            "actions": [
                _rect(x=10, text="Save"),
                _rect(x=30, text="Refresh"),
            ]
        }
    )
    after = _snapshot(
        groups={
            "actions": [
                _rect(x=10, text="Save"),
                _rect(x=34, text="Refresh"),
            ]
        }
    )

    with pytest.raises(ui.UIInvariantError, match="Refresh"):
        ui.assert_group_stable(before, after, "actions", axes=("x",))


def test_overlap_detection_ignores_touching_edges_but_rejects_real_overlap() -> None:
    touching = _snapshot(
        groups={
            "actions": [
                _rect(x=0, width=10, text="A"),
                _rect(x=10, width=10, text="B"),
            ]
        }
    )
    overlap = _snapshot(
        groups={
            "actions": [
                _rect(x=0, width=10, text="A"),
                _rect(x=9, width=10, text="B"),
            ]
        }
    )

    ui.assert_group_no_overlap(touching, "actions")

    with pytest.raises(ui.UIInvariantError, match="overlapping controls"):
        ui.assert_group_no_overlap(overlap, "actions")


def test_group_viewport_contract_rejects_clipped_controls() -> None:
    clipped = _snapshot(
        width=100,
        groups={
            "actions": [
                _rect(x=95, width=10, text="Delete"),
            ]
        },
    )

    with pytest.raises(ui.UIInvariantError, match="outside the viewport"):
        ui.assert_group_within_viewport_horizontally(clipped, "actions")

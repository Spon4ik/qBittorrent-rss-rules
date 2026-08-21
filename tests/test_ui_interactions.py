from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_interactions as interactions  # noqa: E402
import ui_invariants as ui  # noqa: E402
import ui_suite_qa as suite  # noqa: E402


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


class _FakeLocator:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    def is_visible(self) -> bool:
        self.page.visible_checks += 1
        return self.page.visible

    def is_enabled(self) -> bool:
        self.page.enabled_checks += 1
        return self.page.enabled

    def evaluate(self, _expression: str) -> object:
        self.page.locator_evaluate_calls += 1
        return "auto"

    def click(self, *, timeout: int) -> None:
        self.page.clicked = True
        self.page.click_timeout = timeout


class _FakePage:
    def __init__(
        self,
        *,
        actionable: bool | None = None,
        visible: bool = True,
        enabled: bool | None = None,
    ) -> None:
        if enabled is None:
            enabled = True if actionable is None else actionable
        self.visible = visible
        self.enabled = enabled
        self.clicked = False
        self.click_timeout: int | None = None
        self.wait_arg: str | None = None
        self.wait_timeout: int | None = None
        self.locator_requests = 0
        self.visible_checks = 0
        self.enabled_checks = 0
        self.locator_evaluate_calls = 0
        self.evaluate_calls = 0

    def evaluate(self, _expression: str, *, arg: object | None = None) -> object:
        self.evaluate_calls += 1
        return None

    def locator(self, _selector: str) -> _FakeLocator:
        self.locator_requests += 1
        return _FakeLocator(self)

    def wait_for_function(
        self,
        _expression: str,
        *,
        arg: object | None = None,
        timeout: int | None = None,
    ) -> None:
        self.wait_arg = str(arg) if arg is not None else None
        self.wait_timeout = timeout


def test_generic_surface_open_uses_keyword_arg_and_caps_action_timeout() -> None:
    page = _FakePage(actionable=True)

    opened, reason = suite._open_actionable_surface(
        page,
        "ui-surface-7",
        timeout_ms=25000,
    )

    assert opened is True
    assert reason == ""
    assert page.clicked is True
    assert page.wait_arg == "ui-surface-7"
    assert page.click_timeout == suite.INTERACTION_ACTION_TIMEOUT_MS
    assert page.wait_timeout == suite.INTERACTION_ACTION_TIMEOUT_MS
    assert page.visible_checks == 1
    assert page.enabled_checks == 1


def test_disabled_generic_surface_uses_playwright_enabled_state_and_skips_immediately() -> None:
    page = _FakePage(enabled=False)

    opened, reason = suite._open_actionable_surface(
        page,
        "ui-surface-2",
        timeout_ms=25000,
    )

    assert opened is False
    assert reason == "disabled"
    assert page.locator_requests == 1
    assert page.visible_checks == 1
    assert page.enabled_checks == 1
    assert page.locator_evaluate_calls == 0
    assert page.clicked is False
    assert page.wait_arg is None

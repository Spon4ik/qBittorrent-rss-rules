from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ui_component_behavior as behavior  # noqa: E402
import ui_invariants as ui  # noqa: E402


class _ChoiceLocator:
    def __init__(self, *, checked: bool, toggles: bool = True) -> None:
        self.checked = checked
        self.toggles = toggles
        self.click_timeouts: list[int] = []

    def click(self, *, timeout: int) -> None:
        self.click_timeouts.append(timeout)
        if self.toggles:
            self.checked = not self.checked

    def is_checked(self) -> bool:
        return self.checked


class _ChoicePage:
    def __init__(
        self,
        discovery: dict[str, object],
        *,
        toggles: bool = True,
    ) -> None:
        self.discovery = discovery
        self.locator_obj = _ChoiceLocator(
            checked=bool(discovery.get("initialChecked")),
            toggles=toggles,
        )
        self.evaluate_arg: str | None = None
        self.locator_selector: str | None = None

    def evaluate(self, _script: str, arg: str) -> dict[str, object]:
        self.evaluate_arg = arg
        return self.discovery

    def locator(self, selector: str) -> _ChoiceLocator:
        self.locator_selector = selector
        return self.locator_obj


def test_menu_choice_behavior_toggles_and_restores_without_business_literals() -> None:
    page = _ChoicePage(
        {
            "available": True,
            "id": "ui-control-4-choice",
            "initialChecked": False,
            "type": "checkbox",
        }
    )

    result = behavior.exercise_first_menu_choice(
        page,
        "ui-control-4",
        timeout_ms=25000,
    )

    assert result == {
        "exercised": True,
        "type": "checkbox",
        "initial_checked": False,
        "changed_checked": True,
        "restored_checked": False,
    }
    assert page.evaluate_arg == "ui-control-4"
    assert page.locator_selector == '[data-ui-qa-choice-id="ui-control-4-choice"]'
    assert page.locator_obj.click_timeouts == [3000, 3000]


def test_menu_without_enabled_choice_is_reported_without_false_failure() -> None:
    page = _ChoicePage(
        {
            "available": False,
            "reason": "no enabled visible choice",
        }
    )

    result = behavior.exercise_first_menu_choice(page, "ui-control-2", timeout_ms=1000)

    assert result == {
        "exercised": False,
        "reason": "no enabled visible choice",
    }


def test_menu_choice_behavior_fails_when_activation_does_not_change_state() -> None:
    page = _ChoicePage(
        {
            "available": True,
            "id": "ui-control-8-choice",
            "initialChecked": True,
            "type": "checkbox",
        },
        toggles=False,
    )

    with pytest.raises(ui.UIInvariantError, match="did not change state"):
        behavior.exercise_first_menu_choice(page, "ui-control-8", timeout_ms=1000)

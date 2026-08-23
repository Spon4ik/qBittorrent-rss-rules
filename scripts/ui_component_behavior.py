from __future__ import annotations

from typing import Any

import ui_invariants as ui


def exercise_first_menu_choice(page: Any, control_id: str, *, timeout_ms: int) -> dict[str, Any]:
    """Toggle one enabled checkbox in an open menu, then restore it.

    The interaction runs only against the isolated browser-QA app. It proves the
    common checkbox-menu family is actually actionable without encoding business-
    specific labels, languages, feeds, categories, or provider values. Radio
    groups intentionally need a separate group-selection contract because a radio
    cannot be restored by clicking the same choice twice.
    """

    choice = page.evaluate(
        """
        (controlId) => {
          const summary = document.querySelector(
            `[data-ui-qa-control-id="${CSS.escape(controlId)}"]`
          );
          const details = summary?.closest("details");
          if (!(details instanceof HTMLDetailsElement) || !details.open) {
            return {available: false, reason: "menu is not open"};
          }
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return (
              element.getClientRects().length > 0
              && rect.width > 0
              && rect.height > 0
              && style.display !== "none"
              && style.visibility !== "hidden"
            );
          };
          const input = Array.from(
            details.querySelectorAll('input[type="checkbox"]')
          ).find((candidate) => !candidate.disabled && visible(candidate));
          if (!input) return {available: false, reason: "no enabled visible checkbox choice"};
          if (!input.dataset.uiQaChoiceId) {
            input.dataset.uiQaChoiceId = `${controlId}-choice`;
          }
          return {
            available: true,
            id: input.dataset.uiQaChoiceId,
            initialChecked: Boolean(input.checked),
            type: "checkbox",
          };
        }
        """,
        control_id,
    )
    if not isinstance(choice, dict):
        raise ui.UIInvariantError(f"Menu choice discovery failed for {control_id!r}.")
    if not bool(choice.get("available")):
        return {
            "exercised": False,
            "reason": str(choice.get("reason") or "no actionable menu checkbox"),
        }

    choice_id = str(choice.get("id") or "")
    initial_checked = bool(choice.get("initialChecked"))
    selector = f'[data-ui-qa-choice-id="{choice_id}"]'
    locator = page.locator(selector)
    action_timeout_ms = min(max(1, timeout_ms), 3000)

    locator.click(timeout=action_timeout_ms)
    changed_checked = bool(locator.is_checked())
    if changed_checked == initial_checked:
        raise ui.UIInvariantError(
            f"Menu choice {choice_id!r} did not change state after activation."
        )

    # Restore the isolated form state so later component probes are independent.
    locator.click(timeout=action_timeout_ms)
    restored_checked = bool(locator.is_checked())
    if restored_checked != initial_checked:
        raise ui.UIInvariantError(
            f"Menu choice {choice_id!r} did not restore its original state."
        )

    return {
        "exercised": True,
        "type": "checkbox",
        "initial_checked": initial_checked,
        "changed_checked": changed_checked,
        "restored_checked": restored_checked,
    }

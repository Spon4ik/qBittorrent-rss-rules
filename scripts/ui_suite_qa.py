#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import Any

import browser_qa as core
import ui_interactions as interactions
import ui_invariant_qa as base
import ui_invariants as ui


INTERACTIVE_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1720, 1040),
)

MAX_INTERACTIONS_PER_PAGE = 8
MIN_EXERCISED_INTERACTIONS = 3
INTERACTION_ACTION_TIMEOUT_MS = 3000


def _surface_selector(surface_id: str) -> str:
    escaped = surface_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'[data-ui-qa-surface-id="{escaped}"]'


def _surface_actionability(page: Any, surface_id: str) -> dict[str, Any]:
    result = page.evaluate(
        """
        (surfaceId) => {
          const details = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          if (!(details instanceof HTMLDetailsElement)) {
            return {actionable: false, reason: "surface unavailable"};
          }
          const summary = details.querySelector(":scope > summary");
          if (!(summary instanceof HTMLElement)) {
            return {actionable: false, reason: "summary unavailable"};
          }
          const style = window.getComputedStyle(summary);
          const disabledAncestor = summary.closest('[disabled], [aria-disabled="true"]');
          if (disabledAncestor) {
            return {actionable: false, reason: "disabled"};
          }
          if (style.pointerEvents === "none") {
            return {actionable: false, reason: "pointer-events none"};
          }
          if (
            summary.getClientRects().length === 0
            || style.display === "none"
            || style.visibility === "hidden"
          ) {
            return {actionable: false, reason: "not visible"};
          }
          return {actionable: true, reason: ""};
        }
        """,
        arg=surface_id,
    )
    if not isinstance(result, dict):
        raise ui.UIInvariantError("Interactive actionability probe did not return structured data.")
    return result


def _open_actionable_surface(
    page: Any,
    surface_id: str,
    *,
    timeout_ms: int,
) -> tuple[bool, str]:
    actionability = _surface_actionability(page, surface_id)
    if not bool(actionability.get("actionable")):
        return False, str(actionability.get("reason") or "not actionable")

    selector = _surface_selector(surface_id)
    action_timeout_ms = min(max(1, timeout_ms), INTERACTION_ACTION_TIMEOUT_MS)
    summary = page.locator(f"{selector} > summary")
    summary.click(timeout=action_timeout_ms)
    page.wait_for_function(
        """
        (surfaceId) => {
          const details = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          return details instanceof HTMLDetailsElement && details.open === true;
        }
        """,
        arg=surface_id,
        timeout=action_timeout_ms,
    )
    page.evaluate(
        """
        () => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        })
        """
    )
    return True, ""


def check_ui_04(runtime: core.FocusedRuntime) -> None:
    """Audit generic interactive details/menu state transitions deterministically."""

    rule_id = base._seed_rule_id(runtime)
    page_matrix = (*base.CORE_PAGE_MATRIX, ("edit-rule", f"/rules/{rule_id}"))
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    total_discovered = 0
    total_exercised = 0
    total_skipped = 0
    failure_path = runtime.run_dir / "ui-04-failure.png"
    captured_failure = False

    for width, height in INTERACTIVE_VIEWPORTS:
        context = runtime.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            for page_name, relative_url in page_matrix:
                page_record: dict[str, Any] = {
                    "page": page_name,
                    "path": relative_url,
                    "viewport": {"width": width, "height": height},
                    "surfaces": [],
                }
                records.append(page_record)
                try:
                    response = page.goto(
                        f"{runtime.app_base_url}{relative_url}",
                        wait_until="load",
                        timeout=runtime.timeout_ms,
                    )
                    page.wait_for_selector("body", timeout=runtime.timeout_ms)
                    if response is not None and response.status >= 400:
                        raise ui.UIInvariantError(
                            f"HTTP {response.status} for {relative_url}."
                        )
                    surfaces = interactions.discover_interactive_surfaces(
                        page,
                        max_surfaces=MAX_INTERACTIONS_PER_PAGE,
                    )
                    page_record["discovered"] = len(surfaces)
                    total_discovered += len(surfaces)
                except Exception as exc:  # noqa: BLE001
                    base._record_failure(
                        failures,
                        label=f"{page_name}@{width}x{height}:discovery",
                        exc=exc,
                    )
                    if not captured_failure:
                        ui.capture_failure(page, failure_path)
                        captured_failure = True
                    continue

                for surface in surfaces:
                    surface_id = str(surface.get("id") or "")
                    summary_text = str(surface.get("summaryText") or surface_id)
                    label = (
                        f"{page_name}@{width}x{height}:"
                        f"{summary_text[:60] or surface_id}"
                    )
                    surface_record: dict[str, Any] = {
                        "surface": surface,
                    }
                    page_record["surfaces"].append(surface_record)
                    original_open = bool(surface.get("originallyOpen"))

                    try:
                        interactions.set_surface_open(page, surface_id, False)
                        actionability = _surface_actionability(page, surface_id)
                        surface_record["actionability"] = actionability
                        if not bool(actionability.get("actionable")):
                            surface_record["status"] = "skipped"
                            surface_record["skip_reason"] = str(
                                actionability.get("reason") or "not actionable"
                            )
                            total_skipped += 1
                            continue

                        before = interactions.capture_surface_state(page, surface_id)
                        surface_record["before"] = before

                        opened, skip_reason = _open_actionable_surface(
                            page,
                            surface_id,
                            timeout_ms=runtime.timeout_ms,
                        )
                        if not opened:
                            surface_record["status"] = "skipped"
                            surface_record["skip_reason"] = skip_reason
                            total_skipped += 1
                            continue

                        total_exercised += 1
                        after = interactions.capture_surface_state(page, surface_id)
                        surface_record["after"] = after

                        interactions.assert_interactive_transition(
                            before,
                            after,
                            surface,
                            viewport_width=float(width),
                        )
                        interactions.assert_semantic_close_behavior(
                            page,
                            surface,
                            timeout_ms=runtime.timeout_ms,
                        )
                        surface_record["status"] = "pass"
                    except Exception as exc:  # noqa: BLE001
                        surface_record["status"] = "fail"
                        surface_record["failure"] = (
                            f"{exc.__class__.__name__}: {exc}"
                        )
                        base._record_failure(failures, label=label, exc=exc)
                        if not captured_failure:
                            ui.capture_failure(page, failure_path)
                            captured_failure = True
                    finally:
                        try:
                            interactions.set_surface_open(
                                page,
                                surface_id,
                                original_open,
                            )
                        except Exception as exc:  # noqa: BLE001
                            surface_record["restore_failure"] = (
                                f"{exc.__class__.__name__}: {exc}"
                            )
                            base._record_failure(
                                failures,
                                label=f"{label}:restore",
                                exc=exc,
                            )
        finally:
            context.close()

    if total_exercised < MIN_EXERCISED_INTERACTIONS:
        failures.append(
            "coverage: exercised only "
            f"{total_exercised} actionable generic interactive surface(s); "
            f"expected at least {MIN_EXERCISED_INTERACTIONS}."
        )

    ui.write_metrics(
        runtime.run_dir / "ui-04-metrics.json",
        {
            "check": "UI-04",
            "contract": (
                "bounded generic details/menu interactions preserve horizontal safety; "
                "overlay-like surfaces do not reflow surrounding layout; unrelated "
                "desktop action groups keep their horizontal anchor"
            ),
            "matrix": {
                "viewports": [
                    {"width": width, "height": height}
                    for width, height in INTERACTIVE_VIEWPORTS
                ],
                "pages": [
                    {"name": name, "path": path}
                    for name, path in page_matrix
                ],
                "max_interactions_per_page": MAX_INTERACTIONS_PER_PAGE,
                "interaction_action_timeout_ms": INTERACTION_ACTION_TIMEOUT_MS,
                "dedicated_scenarios_excluded": list(
                    interactions.DEDICATED_SURFACE_SELECTORS
                ),
            },
            "discovered_interactions": total_discovered,
            "exercised_interactions": total_exercised,
            "skipped_interactions": total_skipped,
            "records": records,
            "failures": failures,
        },
    )
    if failures:
        suffix = "" if len(failures) <= 8 else f"; +{len(failures) - 8} more"
        raise ui.UIInvariantError("; ".join(failures[:8]) + suffix)


UI_CHECK_SPECS: dict[str, core.CheckSpec] = {
    **base.UI_CHECK_SPECS,
    "UI-04": core.CheckSpec(
        check_id="UI-04",
        phase="UI",
        title=(
            "Generic interactive disclosures/menus preserve layout and action-group invariants"
        ),
        dependencies=(),
        handler=check_ui_04,
    ),
}


def main() -> int:
    args = base.parse_args()
    original_specs = core.CHECK_SPECS
    core.CHECK_SPECS = UI_CHECK_SPECS
    try:
        return core.run_focused(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        core.CHECK_SPECS = original_specs


if __name__ == "__main__":
    raise SystemExit(main())

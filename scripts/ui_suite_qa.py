#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections import Counter
from typing import Any

import browser_qa as core
import ui_component_contracts as components
import ui_interactions as interactions
import ui_invariant_qa as base
import ui_invariants as ui

INTERACTIVE_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1720, 1040),
)
COMPONENT_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1180, 900),
    (1720, 1040),
)
COMPONENT_THEMES: tuple[str, ...] = ("light", "dark")

# This is a fail-safe ceiling, not a sampling budget. Reaching it is itself a
# coverage failure so new siblings cannot silently fall outside the audit.
EXHAUSTIVE_INTERACTION_LIMIT = 10_000
INTERACTION_ACTION_TIMEOUT_MS = 3000
DEDICATED_SURFACE_CONTRACTS: dict[str, str] = {
    ".rule-diagnostics-disclosure": "UI-02",
    "[data-result-toolbar-menu]": "UI-03",
}


def _surface_selector(surface_id: str) -> str:
    escaped = surface_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'[data-ui-qa-surface-id="{escaped}"]'


def _surface_actionability(page: Any, surface_id: str) -> dict[str, Any]:
    """Use Playwright's actionability semantics before attempting a click."""

    selector = _surface_selector(surface_id)
    summary = page.locator(f"{selector} > summary")
    if not summary.is_visible():
        return {"actionable": False, "reason": "not visible"}
    if not summary.is_enabled():
        return {"actionable": False, "reason": "disabled"}

    pointer_events = summary.evaluate(
        "(element) => window.getComputedStyle(element).pointerEvents"
    )
    if pointer_events == "none":
        return {"actionable": False, "reason": "pointer-events none"}
    return {"actionable": True, "reason": ""}


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


def _page_matrix(runtime: core.FocusedRuntime) -> tuple[tuple[str, str], ...]:
    rule_id = base._seed_rule_id(runtime)
    return (*base.CORE_PAGE_MATRIX, ("edit-rule", f"/rules/{rule_id}"))


def check_ui_04(runtime: core.FocusedRuntime) -> None:
    """Exhaustively audit generic details/menu state transitions."""

    page_matrix = _page_matrix(runtime)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    total_discovered = 0
    total_exercised = 0
    total_skipped = 0
    failure_path = runtime.run_dir / "ui-04-failure.png"
    captured_failure = False

    if set(DEDICATED_SURFACE_CONTRACTS) != set(interactions.DEDICATED_SURFACE_SELECTORS):
        raise ui.UIInvariantError(
            "Dedicated generic-surface exclusions must each map to a maintained UI contract."
        )

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
                        max_surfaces=EXHAUSTIVE_INTERACTION_LIMIT,
                    )
                    if len(surfaces) >= EXHAUSTIVE_INTERACTION_LIMIT:
                        raise ui.UIInvariantError(
                            "Generic interactive-surface discovery reached its fail-safe ceiling; "
                            "the audit is no longer exhaustive."
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
                    surface_record: dict[str, Any] = {"surface": surface}
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
                            failures.append(
                                f"{label}: visible generic surface was not actionable: "
                                f"{surface_record['skip_reason']}"
                            )
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
                            failures.append(
                                f"{label}: visible generic surface was not exercised: {skip_reason}"
                            )
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
                        surface_record["failure"] = f"{exc.__class__.__name__}: {exc}"
                        base._record_failure(failures, label=label, exc=exc)
                        if not captured_failure:
                            ui.capture_failure(page, failure_path)
                            captured_failure = True
                    finally:
                        try:
                            interactions.set_surface_open(page, surface_id, original_open)
                        except Exception as exc:  # noqa: BLE001
                            surface_record["restore_failure"] = f"{exc.__class__.__name__}: {exc}"
                            base._record_failure(
                                failures,
                                label=f"{label}:restore",
                                exc=exc,
                            )
        finally:
            context.close()

    if total_exercised + total_skipped != total_discovered:
        failures.append(
            "coverage accounting mismatch: "
            f"discovered={total_discovered}, exercised={total_exercised}, skipped={total_skipped}."
        )

    ui.write_metrics(
        runtime.run_dir / "ui-04-metrics.json",
        {
            "check": "UI-04",
            "contract": (
                "every visible generic details/menu surface is discovered and exercised; "
                "overlay-like surfaces preserve horizontal/layout safety; dedicated exclusions "
                "must map to an explicit maintained UI check"
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
                "fail_safe_interaction_ceiling": EXHAUSTIVE_INTERACTION_LIMIT,
                "interaction_action_timeout_ms": INTERACTION_ACTION_TIMEOUT_MS,
                "dedicated_surface_contracts": DEDICATED_SURFACE_CONTRACTS,
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


def check_ui_05(runtime: core.FocusedRuntime) -> None:
    """Audit every visible interactive component for family coverage and readability."""

    page_matrix = _page_matrix(runtime)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    aggregate_families: Counter[str] = Counter()
    total_discovered = 0
    total_exercised = 0
    total_menus_opened = 0
    failure_path = runtime.run_dir / "ui-05-failure.png"
    captured_failure = False

    for width, height in COMPONENT_VIEWPORTS:
        context = runtime.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            for theme in COMPONENT_THEMES:
                for page_name, relative_url in page_matrix:
                    label_prefix = f"{page_name}@{width}x{height}:{theme}"
                    record: dict[str, Any] = {
                        "page": page_name,
                        "path": relative_url,
                        "viewport": {"width": width, "height": height},
                        "theme": theme,
                        "controls": [],
                    }
                    records.append(record)
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
                        components.set_theme(page, theme)
                        controls = components.discover_interactive_components(page)
                        components.assert_component_coverage(controls)
                        record["family_counts"] = components.family_counts(controls)
                        total_discovered += len(controls)
                        aggregate_families.update(
                            str(item.get("family") or "unclassified") for item in controls
                        )
                    except Exception as exc:  # noqa: BLE001
                        base._record_failure(
                            failures,
                            label=f"{label_prefix}:discovery",
                            exc=exc,
                        )
                        if not captured_failure:
                            ui.capture_failure(page, failure_path)
                            captured_failure = True
                        continue

                    for control in controls:
                        control_id = str(control.get("id") or "")
                        family = str(control.get("family") or "unclassified")
                        control_label = (
                            f"{label_prefix}:{family}:"
                            f"{str(control.get('text') or control_id)[:60]}"
                        )
                        control_record: dict[str, Any] = {"control": control}
                        record["controls"].append(control_record)
                        try:
                            metric = components.capture_control_readability(page, control_id)
                            control_record["readability"] = metric
                            components.assert_control_readability(metric, label=control_label)
                            if not bool(control.get("disabled")):
                                components.focus_control(
                                    page,
                                    control_id,
                                    timeout_ms=runtime.timeout_ms,
                                )
                            if family in components.MENU_FAMILIES:
                                components.open_menu(
                                    page,
                                    control_id,
                                    timeout_ms=runtime.timeout_ms,
                                )
                                opened = components.capture_open_menu_readability(page, control_id)
                                control_record["open_readability"] = opened
                                components.assert_open_menu_readability(
                                    opened,
                                    label=control_label,
                                )
                                total_menus_opened += 1
                                components.close_menu(page, control_id)
                            control_record["status"] = "pass"
                            total_exercised += 1
                        except Exception as exc:  # noqa: BLE001
                            control_record["status"] = "fail"
                            control_record["failure"] = f"{exc.__class__.__name__}: {exc}"
                            base._record_failure(failures, label=control_label, exc=exc)
                            try:
                                if family in components.MENU_FAMILIES:
                                    components.close_menu(page, control_id)
                            except Exception:  # noqa: BLE001
                                pass
                            if not captured_failure:
                                ui.capture_failure(page, failure_path)
                                captured_failure = True
        finally:
            context.close()

    if total_exercised != total_discovered:
        failures.append(
            "component coverage mismatch: "
            f"discovered={total_discovered}, passed={total_exercised}; every visible "
            "interactive component must satisfy a maintained family contract."
        )
    if aggregate_families.get("checkbox-dropdown", 0) == 0:
        failures.append(
            "coverage: no checkbox-dropdown instances were exercised; the shared "
            "Language/feed dropdown family must remain in the matrix."
        )

    ui.write_metrics(
        runtime.run_dir / "ui-05-metrics.json",
        {
            "check": "UI-05",
            "contract": (
                "every visible interactive control is classified into a maintained component "
                "family and passes deterministic readability, contrast, focusability, clipping, "
                "viewport, and menu-panel occlusion checks across light/dark responsive states"
            ),
            "matrix": {
                "themes": list(COMPONENT_THEMES),
                "viewports": [
                    {"width": width, "height": height}
                    for width, height in COMPONENT_VIEWPORTS
                ],
                "pages": [
                    {"name": name, "path": path}
                    for name, path in page_matrix
                ],
                "menu_families": sorted(components.MENU_FAMILIES),
            },
            "family_counts": dict(sorted(aggregate_families.items())),
            "discovered_components": total_discovered,
            "passed_components": total_exercised,
            "opened_menu_instances": total_menus_opened,
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
        title="All generic disclosures/menus preserve interaction and layout invariants",
        dependencies=(),
        handler=check_ui_04,
    ),
    "UI-05": core.CheckSpec(
        check_id="UI-05",
        phase="UI",
        title="All interactive component families satisfy responsive readability contracts",
        dependencies=(),
        handler=check_ui_05,
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

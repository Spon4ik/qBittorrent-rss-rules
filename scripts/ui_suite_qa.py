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
MIN_DISCOVERED_INTERACTIONS = 3


def check_ui_04(runtime: core.FocusedRuntime) -> None:
    """Audit generic interactive details/menu state transitions deterministically."""

    rule_id = base._seed_rule_id(runtime)
    page_matrix = (*base.CORE_PAGE_MATRIX, ("edit-rule", f"/rules/{rule_id}"))
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    total_discovered = 0
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
                        before = interactions.capture_surface_state(page, surface_id)
                        surface_record["before"] = before

                        interactions.open_surface(
                            page,
                            surface_id,
                            timeout_ms=runtime.timeout_ms,
                        )
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

    if total_discovered < MIN_DISCOVERED_INTERACTIONS:
        failures.append(
            "coverage: discovered only "
            f"{total_discovered} generic interactive surface(s); "
            f"expected at least {MIN_DISCOVERED_INTERACTIONS}."
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
                "dedicated_scenarios_excluded": list(
                    interactions.DEDICATED_SURFACE_SELECTORS
                ),
            },
            "discovered_interactions": total_discovered,
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

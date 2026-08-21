#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import browser_qa as core
import ui_invariants as ui


CORE_PAGE_MATRIX: tuple[tuple[str, str], ...] = (
    ("rules", "/"),
    ("new-rule", "/rules/new"),
    ("search", "/search"),
    ("settings", "/settings"),
    ("acceleration", "/acceleration"),
)

RESPONSIVE_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1180, 900),
    (1720, 1040),
)

DIAGNOSTIC_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1180, 900),
    (1720, 1040),
    (2048, 1150),
)


def _record_failure(
    failures: list[str],
    *,
    label: str,
    exc: Exception,
) -> None:
    failures.append(f"{label}: {exc.__class__.__name__}: {exc}")


def _seed_rule_id(runtime: core.FocusedRuntime, *, diagnostics: bool = False) -> str:
    from app.models import Rule

    engine = create_engine(
        f"sqlite:///{runtime.db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    try:
        with Session(engine) as session:
            rule = session.scalar(
                select(Rule).where(Rule.rule_name == "QA P19 Inline Search Profile")
            )
            if rule is None:
                raise ui.UIInvariantError("Expected the pre-seeded UI QA rule to exist.")
            if diagnostics:
                rule.last_synced_rule_payload = {
                    "mustContain": "(?i)qa-ui-invariants",
                    "affectedFeeds": ["Jackett/alpha"],
                }
                rule.last_remote_rule_payload = {
                    "mustContain": "(?i)qa-ui-invariants-remote",
                    "affectedFeeds": ["Jackett/alpha"],
                }
                session.commit()
            return str(rule.id)
    finally:
        engine.dispose()


def check_ui_01(runtime: core.FocusedRuntime) -> None:
    """Representative core pages must not create document-level horizontal overflow."""

    records: list[dict[str, Any]] = []
    failures: list[str] = []
    failure_path = runtime.run_dir / "ui-01-failure.png"
    captured_failure = False

    for width, height in RESPONSIVE_VIEWPORTS:
        context = runtime.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            for page_name, relative_url in CORE_PAGE_MATRIX:
                label = f"{page_name}@{width}x{height}"
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
                    snapshot = ui.capture_layout(page)
                    records.append(
                        {
                            "page": page_name,
                            "path": relative_url,
                            "viewport": {"width": width, "height": height},
                            "snapshot": snapshot,
                        }
                    )
                    ui.assert_no_page_horizontal_overflow(snapshot)
                except Exception as exc:  # noqa: BLE001
                    _record_failure(failures, label=label, exc=exc)
                    if not captured_failure:
                        ui.capture_failure(page, failure_path)
                        captured_failure = True
        finally:
            context.close()

    ui.write_metrics(
        runtime.run_dir / "ui-01-metrics.json",
        {
            "check": "UI-01",
            "contract": "core pages have no document-level horizontal overflow",
            "records": records,
            "failures": failures,
        },
    )
    if failures:
        suffix = "" if len(failures) <= 6 else f"; +{len(failures) - 6} more"
        raise ui.UIInvariantError("; ".join(failures[:6]) + suffix)


def check_ui_02(runtime: core.FocusedRuntime) -> None:
    """Opening qB diagnostics must not move unrelated rule-header actions."""

    rule_id = _seed_rule_id(runtime, diagnostics=True)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    failure_path = runtime.run_dir / "ui-02-failure.png"
    captured_failure = False

    elements = {
        "panel_head": ".panel-head",
        "command_bar": "[data-rule-edit-command-bar]",
        "diagnostics": ".rule-diagnostics-disclosure",
    }
    groups = {
        "command_actions": "[data-rule-edit-command-bar] > *",
    }

    for width, height in DIAGNOSTIC_VIEWPORTS:
        context = runtime.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        label = f"rule-header-diagnostics@{width}x{height}"
        try:
            try:
                response = page.goto(
                    f"{runtime.app_base_url}/rules/{rule_id}",
                    wait_until="load",
                    timeout=runtime.timeout_ms,
                )
                if response is not None and response.status >= 400:
                    raise ui.UIInvariantError(f"HTTP {response.status} for rule edit page.")
                page.wait_for_selector(
                    ".rule-diagnostics-disclosure > summary",
                    state="visible",
                    timeout=runtime.timeout_ms,
                )

                before = ui.capture_layout(page, elements=elements, groups=groups)
                record: dict[str, Any] = {
                    "viewport": {"width": width, "height": height},
                    "before": before,
                }
                records.append(record)
                ui.assert_no_page_horizontal_overflow(before)
                ui.assert_elements_visible(before, ("command_bar", "diagnostics"))
                ui.assert_elements_within_viewport_horizontally(
                    before, ("command_bar", "diagnostics")
                )
                ui.assert_group_no_overlap(before, "command_actions")
                ui.assert_group_within_viewport_horizontally(before, "command_actions")

                page.locator(".rule-diagnostics-disclosure > summary").click()
                page.wait_for_function(
                    "() => document.querySelector('.rule-diagnostics-disclosure')?.open === true",
                    timeout=runtime.timeout_ms,
                )
                after = ui.capture_layout(page, elements=elements, groups=groups)
                record["after"] = after
                ui.assert_no_page_horizontal_overflow(after)
                ui.assert_elements_visible(after, ("command_bar", "diagnostics"))
                ui.assert_elements_within_viewport_horizontally(
                    after, ("command_bar", "diagnostics")
                )
                ui.assert_group_no_overlap(after, "command_actions")
                ui.assert_group_within_viewport_horizontally(after, "command_actions")

                # Desktop command bars should keep their horizontal anchor while a
                # sibling diagnostic disclosure changes state. Narrow/wrapped layouts
                # are checked for containment/overlap but may legitimately wrap.
                if width >= 1720:
                    ui.assert_element_stable(
                        before,
                        after,
                        "command_bar",
                        axes=("x",),
                        tolerance=1.0,
                    )
                    ui.assert_group_stable(
                        before,
                        after,
                        "command_actions",
                        axes=("x",),
                        tolerance=1.0,
                    )
            except Exception as exc:  # noqa: BLE001
                _record_failure(failures, label=label, exc=exc)
                if not captured_failure:
                    ui.capture_failure(page, failure_path)
                    captured_failure = True
        finally:
            context.close()

    ui.write_metrics(
        runtime.run_dir / "ui-02-metrics.json",
        {
            "check": "UI-02",
            "contract": (
                "qB diagnostics may expand its own content but must not shift "
                "unrelated desktop rule-header actions horizontally"
            ),
            "records": records,
            "failures": failures,
        },
    )
    if failures:
        suffix = "" if len(failures) <= 6 else f"; +{len(failures) - 6} more"
        raise ui.UIInvariantError("; ".join(failures[:6]) + suffix)


def check_ui_03(runtime: core.FocusedRuntime) -> None:
    """Reuse the maintained P44 result-toolbar state/geometry regression."""

    try:
        core.check_p44_03(runtime)
    except Exception:
        source = runtime.run_dir / "p44-03-failure.png"
        target = runtime.run_dir / "ui-03-failure.png"
        if source.exists() and not target.exists():
            shutil.copyfile(source, target)
        raise


UI_CHECK_SPECS: dict[str, core.CheckSpec] = {
    "UI-01": core.CheckSpec(
        check_id="UI-01",
        phase="UI",
        title="Core responsive pages avoid document-level horizontal overflow",
        dependencies=(),
        handler=check_ui_01,
    ),
    "UI-02": core.CheckSpec(
        check_id="UI-02",
        phase="UI",
        title="Rule-header actions stay horizontally stable when qB diagnostics opens",
        dependencies=(),
        handler=check_ui_02,
    ),
    "UI-03": core.CheckSpec(
        check_id="UI-03",
        phase="UI",
        title="Result-toolbar menus preserve interaction, geometry, and queue-option visibility",
        dependencies=(),
        handler=check_ui_03,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reusable deterministic UI-invariants suite through the shared "
            "focused browser-QA runtime."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--suite",
        choices=("ui",),
        help="Run the maintained deterministic UI-invariants suite.",
    )
    mode.add_argument(
        "--check",
        action="append",
        help="Run one UI invariant check ID; repeat for multiple checks.",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/qa",
        help="Directory for timestamped browser QA artifacts.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=25000,
        help="Playwright step timeout in milliseconds.",
    )
    parser.add_argument("--headful", action="store_true", help="Run Chromium visibly.")
    parser.add_argument(
        "--app-host", default="127.0.0.1", help="Host bound for the isolated app process."
    )
    args = parser.parse_args()
    args.phase = ["UI"] if args.suite else None
    args.full = False
    return args


def main() -> int:
    args = parse_args()
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

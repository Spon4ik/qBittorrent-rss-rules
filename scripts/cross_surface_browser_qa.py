#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

import browser_qa as core
import cross_surface_contracts as actions
import ui_component_behavior as component_behavior
import ui_component_contracts as components
import ui_design_contracts as design
import ui_invariant_qa as base
import ui_invariants as ui

VIEWPORTS: tuple[tuple[int, int], ...] = (
    (390, 844),
    (1180, 900),
    (1720, 1040),
)
THEMES: tuple[str, ...] = ("light", "dark")
ACTION_TIMEOUT_MS = 3000


def _same_origin_path(base_url: str, href: str) -> str | None:
    candidate = str(href or "").strip()
    if not candidate or candidate.startswith(("#", "mailto:", "javascript:")):
        return None
    base = urlsplit(base_url)
    resolved = urlsplit(candidate)
    if resolved.scheme and (resolved.scheme, resolved.netloc) != (base.scheme, base.netloc):
        return None
    path = resolved.path or "/"
    if path.startswith(("/api/", "/static/")):
        return None
    return path


def discover_page_paths(runtime: core.FocusedRuntime) -> list[str]:
    """Discover stable user pages from app navigation plus seeded dynamic pages."""

    rule_id = base._seed_rule_id(runtime)
    paths: set[str] = {
        "/",
        "/rules/new",
        f"/rules/{rule_id}",
        "/search",
        "/import",
        "/acceleration",
        "/settings",
        "/taxonomy",
    }
    context = runtime.browser.new_context(viewport={"width": 1180, "height": 900})
    page = context.new_page()
    try:
        pending = ["/", "/settings"]
        visited: set[str] = set()
        while pending:
            path = pending.pop(0)
            if path in visited:
                continue
            visited.add(path)
            response = page.goto(
                f"{runtime.app_base_url}{path}",
                wait_until="load",
                timeout=runtime.timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise ui.UIInvariantError(f"HTTP {response.status} while discovering {path}.")
            hrefs = page.locator("a[href]").evaluate_all(
                "elements => elements.map((element) => element.href || element.getAttribute('href') || '')"
            )
            for href in hrefs:
                discovered = _same_origin_path(runtime.app_base_url, str(href))
                if discovered is None:
                    continue
                if discovered.startswith("/rules/") and discovered not in {
                    "/rules/new",
                    f"/rules/{rule_id}",
                }:
                    continue
                if discovered.startswith("/settings/") or discovered in {
                    "/",
                    "/rules/new",
                    "/search",
                    "/import",
                    "/acceleration",
                    "/settings",
                    "/taxonomy",
                }:
                    if discovered not in paths:
                        paths.add(discovered)
                        if discovered.startswith("/settings/"):
                            pending.append(discovered)
    finally:
        context.close()
    return sorted(paths)


def _command_surfaces(page: Any) -> list[dict[str, Any]]:
    result = page.evaluate(
        """
        () => {
          const visible = (element) => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return element.getClientRects().length > 0
              && rect.width > 0
              && rect.height > 0
              && style.display !== 'none'
              && style.visibility !== 'hidden';
          };
          const text = (element) => String(
            element?.getAttribute?.('aria-label')
            || element?.innerText
            || element?.value
            || element?.getAttribute?.('title')
            || element?.textContent
            || ''
          ).trim().replace(/\\s+/g, ' ').slice(0, 160);
          const hasDangerTone = (element) => (
            Array.from(element.classList || []).some((token) => token.toLocaleLowerCase().includes('danger'))
            || element.dataset.uiCommandTone === 'danger'
          );
          const hasConcreteConfirmation = (element, form) => String(
            element.getAttribute('onclick')
            || form?.getAttribute?.('onsubmit')
            || ''
          ).includes('confirm(');
          const familyForControl = (element) => {
            if (element.matches('[data-rules-run-selected], [data-rules-run-all], [data-rules-schedule-run-now], [data-run-search-here]')) return 'fetch-snapshot';
            if (element.matches('a[data-operation-start-label]') && String(element.getAttribute('href') || '').includes('/search')) return 'fetch-snapshot';
            if (element.matches('[data-rules-schedule-save]')) return 'save-schedule';
            if (element.matches('[data-rules-save-defaults], [data-search-save-defaults]')) return 'save-preferences';
            if (element.matches('[data-rules-apply-quality]')) return 'apply-quality';
            if (element.matches('[data-feed-refresh]')) return 'refresh-feeds';
            if (element.matches('[data-result-queue-button]')) return 'queue';
            if (element.matches('[data-acceleration-refresh]')) return 'refresh-view';
            const actionArea = element.closest('.acceleration-actions, .operation-progress-actions');
            if (actionArea) {
              const label = text(element).toLocaleLowerCase();
              if (label.startsWith('retry')) return 'retry-acceleration';
              if (label.startsWith('ask codex')) return 'ask-codex';
              if (label.startsWith('dismiss')) return 'dismiss-acceleration';
              if (label.startsWith('remove')) return 'remove-acceleration';
            }
            return element.dataset.uiCommandFamily || null;
          };

          const commands = [];
          const seen = new Set();
          for (const trigger of document.querySelectorAll(
            'button[type="submit"], input[type="submit"], button:not([type])'
          )) {
            if (!visible(trigger)) continue;
            const form = trigger.form;
            if (!form || String(form.method || 'get').toLocaleLowerCase() !== 'post') continue;
            seen.add(trigger);
            const endpoint = String(
              trigger.getAttribute('formaction')
              || form.getAttribute('action')
              || form.action
              || ''
            );
            commands.push({
              transport: 'form-post',
              endpoint,
              family: form.dataset.uiCommandFamily || trigger.dataset.uiCommandFamily || null,
              label: text(trigger),
              disabled: Boolean(trigger.disabled),
              danger: hasDangerTone(trigger),
              confirmation: hasConcreteConfirmation(trigger, form),
              feedback: 'navigation',
            });
          }

          for (const element of document.querySelectorAll('button, a[href]')) {
            if (seen.has(element) || !visible(element)) continue;
            const family = familyForControl(element);
            if (!family) continue;
            const commandRoot = element.closest(
              '[data-rules-page], [data-search-page], [data-acceleration-console], [data-operation-progress-shell]'
            );
            const hasStatusSurface = Boolean(
              commandRoot?.querySelector?.(
                '[aria-live], [data-rules-run-status], [data-rules-schedule-status], [data-acceleration-summary], [data-operation-progress-summary]'
              )
            );
            commands.push({
              transport: element.tagName === 'A' ? 'link' : 'async-control',
              endpoint: String(element.getAttribute('href') || ''),
              family,
              label: text(element),
              disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
              danger: hasDangerTone(element),
              confirmation: hasConcreteConfirmation(element, null),
              feedback: element.hasAttribute('data-operation-start-label')
                ? 'global-progress'
                : (hasStatusSurface ? 'status-surface' : 'none'),
            });
          }
          return commands;
        }
        """
    )
    if not isinstance(result, list):
        raise ui.UIInvariantError("Command-surface discovery did not return a list.")
    return [item for item in result if isinstance(item, dict)]


def _validate_commands(records: list[dict[str, Any]], *, page_label: str) -> list[str]:
    failures: list[str] = []
    for index, record in enumerate(records):
        family = str(record.get("family") or "").strip()
        endpoint = str(record.get("endpoint") or "").strip()
        label = str(record.get("label") or "").strip()
        if not family and endpoint:
            family = actions.classify_endpoint(endpoint) or ""
        family = actions.refine_family(family or None, label) or ""
        record["family"] = family or None
        if not family:
            failures.append(f"{page_label}: command #{index} is unclassified: {record}")
            continue
        try:
            contract = actions.contract_for_family(family)
        except ValueError as exc:
            failures.append(f"{page_label}: {exc}")
            continue
        if (
            family not in {"provider-command"}
            and label
            and not actions.canonical_label_matches(family, label)
        ):
            failures.append(
                f"{page_label}: {family} label {label!r} does not use canonical verb "
                f"{contract.canonical_verb!r}"
            )
        if contract.destructive:
            if not bool(record.get("danger")):
                failures.append(f"{page_label}: destructive {family} command is not danger-styled")
            if record.get("transport") == "form-post" and not bool(record.get("confirmation")):
                failures.append(
                    f"{page_label}: destructive {family} POST form has no confirmation contract"
                )
        if (
            contract.long_running
            and record.get("transport") in {"async-control", "link"}
            and str(record.get("feedback") or "") == "none"
        ):
            failures.append(
                f"{page_label}: long-running {family} command exposes no progress/status feedback"
            )
    return failures


def _audit(runtime: core.FocusedRuntime) -> tuple[list[dict[str, Any]], list[str]]:
    paths = discover_page_paths(runtime)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    component_family_counts: Counter[str] = Counter()
    action_family_counts: Counter[str] = Counter()
    palette_observations: list[design.PaletteObservation] = []

    for width, height in VIEWPORTS:
        context = runtime.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            for theme in THEMES:
                for path in paths:
                    label = f"{path}@{width}x{height}:{theme}"
                    record: dict[str, Any] = {
                        "path": path,
                        "viewport": {"width": width, "height": height},
                        "theme": theme,
                        "controls": [],
                        "commands": [],
                    }
                    records.append(record)
                    try:
                        response = page.goto(
                            f"{runtime.app_base_url}{path}",
                            wait_until="load",
                            timeout=runtime.timeout_ms,
                        )
                        if response is not None and response.status >= 400:
                            raise ui.UIInvariantError(f"HTTP {response.status} for {path}.")
                        page.wait_for_selector("body", timeout=runtime.timeout_ms)
                        components.set_theme(page, theme)
                        controls = components.discover_interactive_components(page)
                        components.assert_component_coverage(controls)
                        record["component_family_counts"] = components.family_counts(controls)

                        for control in controls:
                            control_id = str(control.get("id") or "")
                            family = str(control.get("family") or "unclassified")
                            control_label = f"{label}:{family}:{str(control.get('text') or control_id)[:60]}"
                            control_record: dict[str, Any] = {"control": control}
                            record["controls"].append(control_record)
                            component_family_counts[family] += 1

                            normal = components.capture_control_readability(page, control_id)
                            control_record["normal"] = normal
                            components.assert_control_readability(normal, label=control_label)
                            design.add_palette_observation(
                                palette_observations,
                                control=control,
                                metric=normal,
                                theme=theme,
                                state="normal",
                                label=control_label,
                            )

                            if not bool(control.get("disabled")):
                                locator = page.locator(
                                    f'[data-ui-qa-control-id="{control_id}"]'
                                )
                                locator.hover(timeout=min(runtime.timeout_ms, ACTION_TIMEOUT_MS))
                                hover = components.capture_control_readability(page, control_id)
                                control_record["hover"] = hover
                                components.assert_control_readability(
                                    hover,
                                    label=f"{control_label}:hover",
                                )
                                design.add_palette_observation(
                                    palette_observations,
                                    control=control,
                                    metric=hover,
                                    theme=theme,
                                    state="hover",
                                    label=control_label,
                                )

                                page.mouse.move(1, 1)
                                components.focus_control(
                                    page,
                                    control_id,
                                    timeout_ms=runtime.timeout_ms,
                                )
                                focus = components.capture_control_readability(page, control_id)
                                control_record["focus"] = focus
                                components.assert_control_readability(
                                    focus,
                                    label=f"{control_label}:focus",
                                )
                                design.add_palette_observation(
                                    palette_observations,
                                    control=control,
                                    metric=focus,
                                    theme=theme,
                                    state="focus",
                                    label=control_label,
                                )

                            if family in components.MENU_FAMILIES:
                                components.open_menu(
                                    page,
                                    control_id,
                                    timeout_ms=runtime.timeout_ms,
                                )
                                opened = components.capture_open_menu_readability(page, control_id)
                                control_record["open"] = opened
                                components.assert_open_menu_readability(
                                    opened,
                                    label=f"{control_label}:open",
                                )
                                design.add_palette_observation(
                                    palette_observations,
                                    control=control,
                                    metric=opened,
                                    theme=theme,
                                    state="open",
                                    label=control_label,
                                )
                                choice = component_behavior.exercise_first_menu_choice(
                                    page,
                                    control_id,
                                    timeout_ms=runtime.timeout_ms,
                                )
                                control_record["choice_behavior"] = choice
                                components.close_menu(page, control_id)

                        command_records = _command_surfaces(page)
                        command_failures = _validate_commands(command_records, page_label=label)
                        for command in command_records:
                            action_family_counts[str(command.get("family") or "unclassified")] += 1
                        record["commands"] = command_records
                        failures.extend(command_failures)
                    except Exception as exc:  # noqa: BLE001
                        failures.append(f"{label}: {exc.__class__.__name__}: {exc}")
        finally:
            context.close()

    try:
        design.assert_palette_consistency(palette_observations)
    except ui.UIInvariantError as exc:
        failures.append(f"design-consistency: {exc}")

    records.append(
        {
            "summary": {
                "paths": paths,
                "themes": list(THEMES),
                "viewports": [{"width": w, "height": h} for w, h in VIEWPORTS],
                "component_family_counts": dict(sorted(component_family_counts.items())),
                "action_family_counts": dict(sorted(action_family_counts.items())),
                "palette_observations": len(palette_observations),
            }
        }
    )
    return records, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit cross-page component and action-family consistency."
    )
    parser.add_argument("--suite", choices=("ui", "consistency"), default="consistency")
    parser.add_argument("--output-dir", default="logs/qa")
    parser.add_argument("--timeout-ms", type=int, default=25000)
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--app-host", default="127.0.0.1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with core.focused_runtime(args) as runtime:
        records, failures = _audit(runtime)
        report_path = runtime.run_dir / "cross-surface-report.json"
        report_path.write_text(
            json.dumps(
                {
                    "status": "pass" if not failures else "fail",
                    "records": records,
                    "failures": failures,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Saved cross-surface QA report: {report_path}")
        if failures:
            print(f"CROSS-SURFACE FAIL: {len(failures)} finding(s).", file=sys.stderr)
            for failure in failures[:12]:
                print(f"- {failure}", file=sys.stderr)
            if len(failures) > 12:
                print(f"- +{len(failures) - 12} more", file=sys.stderr)
            return 1
        print("CROSS-SURFACE PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from typing import Any, Mapping, Sequence

import ui_invariants as ui


DEDICATED_SURFACE_SELECTORS: tuple[str, ...] = (
    ".rule-diagnostics-disclosure",
    "[data-result-toolbar-menu]",
)

_ACTION_GROUP_SELECTORS: tuple[str, ...] = (
    '[class*="actions"]',
    '[role="group"]',
    '[data-rule-edit-command-bar]',
    '.rules-utility-strip',
    '.rules-schedule-strip',
)


def discover_interactive_surfaces(
    page: Any,
    *,
    max_surfaces: int = 8,
    excluded_selectors: Sequence[str] = DEDICATED_SURFACE_SELECTORS,
) -> list[dict[str, Any]]:
    """Discover a bounded set of visible top-level <details> interactions.

    Dedicated scenarios are excluded by default so a broad suite does not pay
    twice for the same regression. Overlay-like controls are prioritized ahead
    of ordinary in-flow disclosures.
    """

    result = page.evaluate(
        """
        ({maxSurfaces, excludedSelectors}) => {
          const isVisible = (element) => {
            if (!element) return false;
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const opacity = Number.parseFloat(style.opacity || "1");
            return (
              element.getClientRects().length > 0
              && rect.width > 0
              && rect.height > 0
              && style.display !== "none"
              && style.visibility !== "hidden"
              && !Number.isNaN(opacity)
              && opacity > 0
            );
          };

          const hasHorizontalScroller = (element) => {
            let current = element.parentElement;
            while (current && current !== document.body) {
              const style = window.getComputedStyle(current);
              if (
                ["auto", "scroll"].includes(style.overflowX)
                && current.scrollWidth > current.clientWidth + 1
              ) return true;
              current = current.parentElement;
            }
            return false;
          };

          const candidates = [];
          let sequence = 0;
          for (const details of document.querySelectorAll("details")) {
            if (details.parentElement?.closest("details")) continue;
            if (excludedSelectors.some((selector) => details.matches(selector))) continue;

            const summary = details.querySelector(":scope > summary");
            if (!summary || !isVisible(summary)) continue;

            if (!details.dataset.uiQaSurfaceId) {
              details.dataset.uiQaSurfaceId = `ui-surface-${sequence}`;
            }
            sequence += 1;

            const panel = Array.from(details.children)
              .find((child) => child.tagName !== "SUMMARY");
            if (!panel) continue;
            const panelStyle = window.getComputedStyle(panel);
            const overlay = Boolean(
              details.matches(".search-multiselect, .search-queue-advanced")
              || details.querySelector('[role="menu"], [role="listbox"]')
              || ["absolute", "fixed"].includes(panelStyle.position)
            );

            candidates.push({
              id: details.dataset.uiQaSurfaceId,
              summaryText: String(summary.innerText || summary.textContent || "")
                .trim()
                .slice(0, 120),
              classes: String(details.className || ""),
              originallyOpen: Boolean(details.open),
              overlay,
              semanticClose: details.matches("[data-result-toolbar-menu]")
                ? "result-toolbar"
                : "native-details",
              insideHorizontalScroller: hasHorizontalScroller(details),
              priority: overlay ? 0 : 1,
            });
          }

          candidates.sort((left, right) => (
            left.priority - right.priority
            || left.id.localeCompare(right.id)
          ));
          return candidates.slice(0, Math.max(0, maxSurfaces));
        }
        """,
        {
            "maxSurfaces": max_surfaces,
            "excludedSelectors": list(excluded_selectors),
        },
    )
    if not isinstance(result, list):
        raise ui.UIInvariantError("Interactive-surface discovery did not return a list.")
    return [item for item in result if isinstance(item, dict)]


def set_surface_open(page: Any, surface_id: str, open_state: bool) -> None:
    changed = page.evaluate(
        """
        ({surfaceId, openState}) => {
          const details = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          if (!(details instanceof HTMLDetailsElement)) return false;
          details.open = Boolean(openState);
          return true;
        }
        """,
        {"surfaceId": surface_id, "openState": open_state},
    )
    if not changed:
        raise ui.UIInvariantError(f"Interactive surface {surface_id!r} is unavailable.")
    _settle_layout(page)


def open_surface(page: Any, surface_id: str, *, timeout_ms: int) -> None:
    selector = _surface_selector(surface_id)
    summary = page.locator(f"{selector} > summary")
    summary.click(timeout=timeout_ms)
    page.wait_for_function(
        """
        (surfaceId) => {
          const details = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          return details instanceof HTMLDetailsElement && details.open === true;
        }
        """,
        surface_id,
        timeout=timeout_ms,
    )
    _settle_layout(page)


def capture_surface_state(page: Any, surface_id: str) -> dict[str, Any]:
    selector = _surface_selector(surface_id)
    layout = ui.capture_layout(
        page,
        elements={
            "surface": selector,
            "summary": f"{selector} > summary",
            "panel": f"{selector} > :not(summary)",
        },
    )
    return {
        "layout": layout,
        "action_groups": ui.capture_action_groups(page),
        "unrelated_action_groups": capture_unrelated_action_groups(page, surface_id),
        "context": capture_surface_context(page, surface_id),
    }


def capture_unrelated_action_groups(page: Any, surface_id: str) -> list[dict[str, Any]]:
    """Capture stable geometry for action groups unrelated to one surface."""

    result = page.evaluate(
        """
        ({surfaceId, selectors}) => {
          const surface = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          if (!surface) return [];

          const metric = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const opacity = Number.parseFloat(style.opacity || "1");
            return {
              left: rect.left,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height,
              text: String(element.innerText || element.textContent || "")
                .trim()
                .slice(0, 120),
              visible: (
                element.getClientRects().length > 0
                && rect.width > 0
                && rect.height > 0
                && style.display !== "none"
                && style.visibility !== "hidden"
                && !Number.isNaN(opacity)
                && opacity > 0
              ),
            };
          };

          const domKey = (element) => {
            const parts = [];
            let current = element;
            while (current && current !== document.body) {
              const parent = current.parentElement;
              if (!parent) break;
              const siblings = Array.from(parent.children)
                .filter((item) => item.tagName === current.tagName);
              const index = siblings.indexOf(current) + 1;
              parts.push(`${current.tagName.toLowerCase()}:nth-of-type(${index})`);
              current = parent;
            }
            return parts.reverse().join(">");
          };

          const seen = new Set();
          const containers = [];
          for (const selector of selectors) {
            for (const element of document.querySelectorAll(selector)) {
              if (seen.has(element)) continue;
              seen.add(element);
              if (surface.contains(element) || element.contains(surface)) continue;
              containers.push(element);
            }
          }

          return containers
            .map((container) => ({
              key: domKey(container),
              container: metric(container),
            }))
            .filter((item) => item.container.visible);
        }
        """,
        {"surfaceId": surface_id, "selectors": list(_ACTION_GROUP_SELECTORS)},
    )
    if not isinstance(result, list):
        raise ui.UIInvariantError("Unrelated action-group probe did not return a list.")
    return [item for item in result if isinstance(item, dict)]


def capture_surface_context(page: Any, surface_id: str) -> dict[str, Any]:
    """Capture immediate surrounding layout used to detect overlay reflow."""

    result = page.evaluate(
        """
        (surfaceId) => {
          const surface = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          if (!surface) return null;

          const metric = (element) => {
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            return {
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height,
            };
          };

          return {
            parent: metric(surface.parentElement),
            previous: metric(surface.previousElementSibling),
            next: metric(surface.nextElementSibling),
          };
        }
        """,
        surface_id,
    )
    if not isinstance(result, dict):
        raise ui.UIInvariantError("Interactive-surface context probe failed.")
    return result


def assert_interactive_transition(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    surface: Mapping[str, Any],
    *,
    viewport_width: float,
    desktop_stability_width: float = 1720.0,
    tolerance: float = 1.0,
) -> None:
    """Validate one closed->open transition with semantic layout rules."""

    after_layout = _mapping(after, "layout")
    ui.assert_no_page_horizontal_overflow(after_layout)
    ui.assert_elements_visible(after_layout, ("surface", "summary", "panel"))

    if not bool(surface.get("insideHorizontalScroller")):
        ui.assert_elements_within_viewport_horizontally(
            after_layout,
            ("summary", "panel"),
            tolerance=tolerance,
        )

    after_groups = _sequence_of_mappings(after, "action_groups")
    ui.assert_action_groups_safe(after_groups, viewport_width=viewport_width)

    before_groups = _sequence_of_mappings(before, "unrelated_action_groups")
    after_unrelated_groups = _sequence_of_mappings(after, "unrelated_action_groups")
    if bool(surface.get("overlay")):
        assert_action_group_positions_stable(
            before_groups,
            after_unrelated_groups,
            axes=("left", "top"),
            tolerance=tolerance,
        )
        assert_surface_context_stable(
            _mapping(before, "context"),
            _mapping(after, "context"),
            tolerance=tolerance,
        )
    elif viewport_width >= desktop_stability_width:
        assert_action_group_positions_stable(
            before_groups,
            after_unrelated_groups,
            axes=("left",),
            tolerance=tolerance,
        )


def assert_action_group_positions_stable(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    axes: Sequence[str],
    tolerance: float = 1.0,
) -> None:
    """Compare visible unrelated action-group containers by stable DOM key."""

    before_by_key = {
        str(item.get("key")): item
        for item in before
        if item.get("key") and isinstance(item.get("container"), Mapping)
    }
    after_by_key = {
        str(item.get("key")): item
        for item in after
        if item.get("key") and isinstance(item.get("container"), Mapping)
    }
    failures: list[str] = []
    for key in sorted(set(before_by_key) & set(after_by_key)):
        old = before_by_key[key].get("container")
        new = after_by_key[key].get("container")
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            continue
        if not bool(old.get("visible")) or not bool(new.get("visible")):
            continue
        for axis in axes:
            old_value = float(old.get(axis) or 0)
            new_value = float(new.get(axis) or 0)
            delta = new_value - old_value
            if abs(delta) > tolerance:
                label = str(old.get("text") or key).strip().replace("\n", " ")[:80]
                failures.append(
                    f"{label or key} {axis}: "
                    f"{old_value:.1f}->{new_value:.1f} ({delta:+.1f}px)"
                )
    if failures:
        suffix = "" if len(failures) <= 6 else f"; +{len(failures) - 6} more"
        raise ui.UIInvariantError(
            "Unrelated action groups moved unexpectedly: "
            + "; ".join(failures[:6])
            + suffix
        )


def assert_surface_context_stable(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    tolerance: float = 1.0,
) -> None:
    """Overlay-like surfaces must not resize/reposition their surrounding flow."""

    failures: list[str] = []
    for name in ("parent", "previous", "next"):
        old = before.get(name)
        new = after.get(name)
        if old is None and new is None:
            continue
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            failures.append(f"{name}: surrounding element appeared/disappeared")
            continue
        for axis in ("left", "top", "width", "height"):
            old_value = float(old.get(axis) or 0)
            new_value = float(new.get(axis) or 0)
            delta = new_value - old_value
            if abs(delta) > tolerance:
                failures.append(
                    f"{name}.{axis}: "
                    f"{old_value:.1f}->{new_value:.1f} ({delta:+.1f}px)"
                )
    if failures:
        suffix = "" if len(failures) <= 6 else f"; +{len(failures) - 6} more"
        raise ui.UIInvariantError(
            "Overlay reflowed surrounding layout: "
            + "; ".join(failures[:6])
            + suffix
        )


def assert_semantic_close_behavior(
    page: Any,
    surface: Mapping[str, Any],
    *,
    timeout_ms: int,
) -> None:
    """Assert close behavior only when the component explicitly owns that contract."""

    if surface.get("semanticClose") != "result-toolbar":
        return
    surface_id = str(surface.get("id") or "")
    if not surface_id:
        raise ui.UIInvariantError("Semantic-close surface has no QA id.")

    page.keyboard.press("Escape")
    _wait_for_open_state(page, surface_id, False, timeout_ms=timeout_ms)

    open_surface(page, surface_id, timeout_ms=timeout_ms)
    page.evaluate("() => document.body.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    _wait_for_open_state(page, surface_id, False, timeout_ms=timeout_ms)


def _wait_for_open_state(
    page: Any,
    surface_id: str,
    expected: bool,
    *,
    timeout_ms: int,
) -> None:
    page.wait_for_function(
        """
        ({surfaceId, expected}) => {
          const details = document.querySelector(
            `[data-ui-qa-surface-id="${CSS.escape(surfaceId)}"]`
          );
          return (
            details instanceof HTMLDetailsElement
            && details.open === Boolean(expected)
          );
        }
        """,
        {"surfaceId": surface_id, "expected": expected},
        timeout=timeout_ms,
    )
    _settle_layout(page)


def _settle_layout(page: Any) -> None:
    page.evaluate(
        """
        () => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        })
        """
    )


def _surface_selector(surface_id: str) -> str:
    escaped = surface_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'[data-ui-qa-surface-id="{escaped}"]'


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ui.UIInvariantError(f"Missing structured interaction field {key!r}.")
    return item


def _sequence_of_mappings(
    value: Mapping[str, Any],
    key: str,
) -> list[Mapping[str, Any]]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ui.UIInvariantError(f"Missing structured interaction list {key!r}.")
    return [item for item in raw if isinstance(item, Mapping)]

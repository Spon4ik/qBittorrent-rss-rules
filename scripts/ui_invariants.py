from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


class UIInvariantError(AssertionError):
    """Raised when deterministic browser geometry violates a maintained UI contract."""


def _rect_label(item: Mapping[str, Any]) -> str:
    text = str(item.get("text") or "").strip()
    if text:
        return text[:80]
    tag = str(item.get("tag") or "element")
    element_id = str(item.get("id") or "")
    return f"{tag}#{element_id}" if element_id else tag


def capture_layout(
    page: Any,
    *,
    elements: Mapping[str, str] | None = None,
    groups: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Capture DOM geometry/state without screenshots or image interpretation."""

    payload = {
        "elements": dict(elements or {}),
        "groups": dict(groups or {}),
    }
    result = page.evaluate(
        """
        ({elements, groups}) => {
          const metric = (element) => {
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const opacity = Number.parseFloat(style.opacity || "1");
            const visible = (
              element.getClientRects().length > 0
              && rect.width > 0
              && rect.height > 0
              && style.display !== "none"
              && style.visibility !== "hidden"
              && !Number.isNaN(opacity)
              && opacity > 0
            );
            return {
              tag: element.tagName.toLowerCase(),
              id: element.id || "",
              classes: String(element.className || ""),
              text: String(element.innerText || element.textContent || "").trim().slice(0, 160),
              x: rect.x,
              y: rect.y,
              left: rect.left,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height,
              documentX: rect.left + window.scrollX,
              documentY: rect.top + window.scrollY,
              visible,
              display: style.display,
              visibility: style.visibility,
              position: style.position,
              overflowX: style.overflowX,
              overflowY: style.overflowY,
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
              scrollHeight: element.scrollHeight,
              clientHeight: element.clientHeight,
            };
          };

          const elementMetrics = {};
          for (const [name, selector] of Object.entries(elements)) {
            elementMetrics[name] = metric(document.querySelector(selector));
          }

          const groupMetrics = {};
          for (const [name, selector] of Object.entries(groups)) {
            groupMetrics[name] = Array.from(document.querySelectorAll(selector)).map(metric);
          }

          const root = document.documentElement;
          return {
            url: window.location.href,
            viewport: {
              width: window.innerWidth,
              height: window.innerHeight,
              scrollX: window.scrollX,
              scrollY: window.scrollY,
            },
            document: {
              scrollWidth: root.scrollWidth,
              clientWidth: root.clientWidth,
              scrollHeight: root.scrollHeight,
              clientHeight: root.clientHeight,
            },
            elements: elementMetrics,
            groups: groupMetrics,
          };
        }
        """,
        payload,
    )
    if not isinstance(result, dict):
        raise UIInvariantError("Browser layout probe did not return structured metrics.")
    return result


def capture_action_groups(page: Any) -> list[dict[str, Any]]:
    """Discover common action/tool groups and record direct-child geometry.

    Viewport containment is intentionally waived for groups inside a genuine
    horizontal scroller (for example a wide result table); sibling overlap is
    still actionable there.
    """

    result = page.evaluate(
        """
        () => {
          const metric = (element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            const opacity = Number.parseFloat(style.opacity || "1");
            return {
              tag: element.tagName.toLowerCase(),
              id: element.id || "",
              classes: String(element.className || ""),
              text: String(element.innerText || element.textContent || "").trim().slice(0, 160),
              left: rect.left,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height,
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

          const selectors = [
            '[class*="actions"]',
            '[role="group"]',
            '[data-rule-edit-command-bar]',
            '.rules-utility-strip',
            '.rules-schedule-strip',
          ];
          const seen = new Set();
          const containers = [];
          for (const selector of selectors) {
            for (const element of document.querySelectorAll(selector)) {
              if (!seen.has(element)) {
                seen.add(element);
                containers.push(element);
              }
            }
          }

          const hasHorizontalScroller = (element) => {
            let current = element.parentElement;
            while (current && current !== document.body) {
              const style = window.getComputedStyle(current);
              if (
                ['auto', 'scroll'].includes(style.overflowX)
                && current.scrollWidth > current.clientWidth + 1
              ) return true;
              current = current.parentElement;
            }
            return false;
          };

          return containers
            .map((container) => ({
              container: metric(container),
              insideHorizontalScroller: hasHorizontalScroller(container),
              children: Array.from(container.children).map(metric),
            }))
            .filter((group) => group.container.visible && group.children.some((item) => item.visible));
        }
        """
    )
    if not isinstance(result, list):
        raise UIInvariantError("Action-group probe did not return a list.")
    return [item for item in result if isinstance(item, dict)]


def write_metrics(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def capture_failure(page: Any, path: Path) -> None:
    """Best-effort human evidence; never the pass/fail oracle."""

    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def assert_no_page_horizontal_overflow(
    snapshot: Mapping[str, Any], *, tolerance: float = 1.0
) -> None:
    document = snapshot.get("document")
    if not isinstance(document, Mapping):
        raise UIInvariantError("Missing document geometry.")
    scroll_width = float(document.get("scrollWidth") or 0)
    client_width = float(document.get("clientWidth") or 0)
    overflow = scroll_width - client_width
    if overflow > tolerance:
        raise UIInvariantError(
            f"Page horizontal overflow={overflow:.1f}px "
            f"(scrollWidth={scroll_width:.1f}, clientWidth={client_width:.1f})."
        )


def _element(snapshot: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    elements = snapshot.get("elements")
    if not isinstance(elements, Mapping):
        raise UIInvariantError("Missing element metrics.")
    item = elements.get(name)
    if not isinstance(item, Mapping):
        raise UIInvariantError(f"Expected element {name!r} was not found.")
    return item


def _group(snapshot: Mapping[str, Any], name: str) -> Sequence[Mapping[str, Any]]:
    groups = snapshot.get("groups")
    if not isinstance(groups, Mapping):
        raise UIInvariantError("Missing group metrics.")
    raw_items = groups.get(name)
    if not isinstance(raw_items, list):
        raise UIInvariantError(f"Expected element group {name!r} was not found.")
    items = [item for item in raw_items if isinstance(item, Mapping)]
    if len(items) != len(raw_items):
        raise UIInvariantError(f"Element group {name!r} returned malformed metrics.")
    return items


def assert_elements_visible(snapshot: Mapping[str, Any], names: Sequence[str]) -> None:
    failures = []
    for name in names:
        item = _element(snapshot, name)
        if not bool(item.get("visible")):
            failures.append(name)
    if failures:
        raise UIInvariantError("Expected visible element(s): " + ", ".join(failures) + ".")


def assert_elements_within_viewport_horizontally(
    snapshot: Mapping[str, Any],
    names: Sequence[str],
    *,
    tolerance: float = 1.0,
) -> None:
    viewport = snapshot.get("viewport")
    if not isinstance(viewport, Mapping):
        raise UIInvariantError("Missing viewport geometry.")
    width = float(viewport.get("width") or 0)
    failures = []
    for name in names:
        item = _element(snapshot, name)
        left = float(item.get("left") or 0)
        right = float(item.get("right") or 0)
        if left < -tolerance or right > width + tolerance:
            failures.append(f"{name}(left={left:.1f}, right={right:.1f}, viewport={width:.1f})")
    if failures:
        raise UIInvariantError("Element(s) escape viewport horizontally: " + "; ".join(failures))


def assert_element_stable(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    name: str,
    *,
    axes: Sequence[str] = ("x", "y"),
    tolerance: float = 1.0,
) -> None:
    before_item = _element(before, name)
    after_item = _element(after, name)
    failures = []
    for axis in axes:
        if axis not in {"x", "y", "width", "height"}:
            raise ValueError(f"Unsupported geometry axis {axis!r}.")
        old = float(before_item.get(axis) or 0)
        new = float(after_item.get(axis) or 0)
        delta = new - old
        if abs(delta) > tolerance:
            failures.append(f"{axis}: {old:.1f}->{new:.1f} ({delta:+.1f}px)")
    if failures:
        raise UIInvariantError(f"{name} moved unexpectedly: " + ", ".join(failures))


def assert_group_stable(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    name: str,
    *,
    axes: Sequence[str] = ("x", "y"),
    tolerance: float = 1.0,
) -> None:
    before_items = _group(before, name)
    after_items = _group(after, name)
    if len(before_items) != len(after_items):
        raise UIInvariantError(
            f"{name} item count changed: {len(before_items)} -> {len(after_items)}."
        )
    failures = []
    for index, (old_item, new_item) in enumerate(zip(before_items, after_items, strict=True)):
        item_failures = []
        for axis in axes:
            if axis not in {"x", "y", "width", "height"}:
                raise ValueError(f"Unsupported geometry axis {axis!r}.")
            old = float(old_item.get(axis) or 0)
            new = float(new_item.get(axis) or 0)
            delta = new - old
            if abs(delta) > tolerance:
                item_failures.append(f"{axis} {old:.1f}->{new:.1f} ({delta:+.1f}px)")
        if item_failures:
            failures.append(
                f"#{index} {_rect_label(old_item)}: " + ", ".join(item_failures)
            )
    if failures:
        raise UIInvariantError(f"{name} moved unexpectedly: " + "; ".join(failures[:6]))


def assert_group_no_overlap(
    snapshot: Mapping[str, Any],
    name: str,
    *,
    tolerance: float = 0.5,
) -> None:
    items = [item for item in _group(snapshot, name) if bool(item.get("visible"))]
    failures = _overlap_failures(items, tolerance=tolerance)
    if failures:
        raise UIInvariantError(f"{name} contains overlapping controls: " + "; ".join(failures[:6]))


def _overlap_failures(
    items: Sequence[Mapping[str, Any]], *, tolerance: float
) -> list[str]:
    failures = []
    for left_index, left_item in enumerate(items):
        for right_index in range(left_index + 1, len(items)):
            right_item = items[right_index]
            overlap_x = min(
                float(left_item.get("right") or 0),
                float(right_item.get("right") or 0),
            ) - max(
                float(left_item.get("left") or 0),
                float(right_item.get("left") or 0),
            )
            overlap_y = min(
                float(left_item.get("bottom") or 0),
                float(right_item.get("bottom") or 0),
            ) - max(
                float(left_item.get("top") or 0),
                float(right_item.get("top") or 0),
            )
            if overlap_x > tolerance and overlap_y > tolerance:
                failures.append(
                    f"#{left_index} {_rect_label(left_item)} overlaps "
                    f"#{right_index} {_rect_label(right_item)} "
                    f"({overlap_x:.1f}x{overlap_y:.1f}px)"
                )
    return failures


def assert_group_within_viewport_horizontally(
    snapshot: Mapping[str, Any],
    name: str,
    *,
    tolerance: float = 1.0,
) -> None:
    viewport = snapshot.get("viewport")
    if not isinstance(viewport, Mapping):
        raise UIInvariantError("Missing viewport geometry.")
    width = float(viewport.get("width") or 0)
    failures = []
    for index, item in enumerate(_group(snapshot, name)):
        if not bool(item.get("visible")):
            continue
        left = float(item.get("left") or 0)
        right = float(item.get("right") or 0)
        if left < -tolerance or right > width + tolerance:
            failures.append(
                f"#{index} {_rect_label(item)} left={left:.1f}, right={right:.1f}, viewport={width:.1f}"
            )
    if failures:
        raise UIInvariantError(
            f"{name} contains controls outside the viewport: " + "; ".join(failures[:6])
        )


def assert_action_groups_safe(
    groups: Sequence[Mapping[str, Any]],
    *,
    viewport_width: float,
    overlap_tolerance: float = 0.5,
    viewport_tolerance: float = 1.0,
) -> None:
    """Reject overlap/off-screen action groups while respecting table scrollers."""

    failures: list[str] = []
    for group_index, group in enumerate(groups):
        container = group.get("container")
        raw_children = group.get("children")
        if not isinstance(container, Mapping) or not isinstance(raw_children, list):
            failures.append(f"group #{group_index}: malformed geometry")
            continue
        children = [
            item
            for item in raw_children
            if isinstance(item, Mapping) and bool(item.get("visible"))
        ]
        container_label = _rect_label(container)
        for overlap in _overlap_failures(children, tolerance=overlap_tolerance):
            failures.append(f"{container_label}: {overlap}")

        if bool(group.get("insideHorizontalScroller")):
            continue
        for child_index, item in enumerate(children):
            left = float(item.get("left") or 0)
            right = float(item.get("right") or 0)
            if left < -viewport_tolerance or right > viewport_width + viewport_tolerance:
                failures.append(
                    f"{container_label}: child #{child_index} {_rect_label(item)} escapes viewport "
                    f"(left={left:.1f}, right={right:.1f}, viewport={viewport_width:.1f})"
                )
    if failures:
        suffix = "" if len(failures) <= 8 else f"; +{len(failures) - 8} more"
        raise UIInvariantError("Unsafe action groups: " + "; ".join(failures[:8]) + suffix)

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import ui_invariants as ui

MENU_FAMILIES = frozenset({"checkbox-dropdown", "search-multiselect", "toolbar-menu"})
MIN_TEXT_CONTRAST = 4.5
MIN_DISABLED_TEXT_CONTRAST = 3.0

_INTERACTIVE_SELECTOR = ", ".join(
    (
        "summary",
        "select",
        "textarea",
        "button",
        "a[href]",
        'input:not([type="hidden"])',
        '[role="button"]',
        '[tabindex]:not([tabindex="-1"])',
    )
)


def discover_interactive_components(page: Any) -> list[dict[str, Any]]:
    """Enumerate every visible interactive control and classify its component family."""

    result = page.evaluate(
        """
        (selector) => {
          const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
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

          const diagnosticLabel = (element) => {
            const tag = element.tagName.toLowerCase();
            if (tag === "select") {
              return String(
                element.getAttribute("aria-label")
                || element.getAttribute("name")
                || element.selectedOptions?.[0]?.textContent
                || "select"
              ).trim();
            }
            if (["input", "textarea"].includes(tag)) {
              return String(
                element.getAttribute("aria-label")
                || element.getAttribute("name")
                || element.getAttribute("placeholder")
                || element.getAttribute("type")
                || tag
              ).trim();
            }
            return String(
              element.innerText
              || element.getAttribute("aria-label")
              || element.textContent
              || tag
            ).trim();
          };

          const familyFor = (element) => {
            const tag = element.tagName.toLowerCase();
            if (tag === "summary") {
              const details = element.closest("details");
              if (!details) return null;
              if (details.matches(".checkbox-dropdown")) return "checkbox-dropdown";
              if (details.matches(".search-multiselect")) return "search-multiselect";
              if (details.matches(".search-queue-advanced, [data-result-toolbar-menu]")) {
                return "toolbar-menu";
              }
              if (details.matches(".rule-diagnostics-disclosure")) {
                return "diagnostic-disclosure";
              }
              return "details-disclosure";
            }
            if (tag === "select") return "native-select";
            if (tag === "textarea") return "textarea";
            if (tag === "button") return "button";
            if (tag === "a" && element.hasAttribute("href")) return "link";
            if (tag === "input") {
              const type = String(element.getAttribute("type") || "text").toLowerCase();
              if (type === "checkbox") return "checkbox";
              if (type === "radio") return "radio";
              if (type === "file") return "file-input";
              if (["button", "submit", "reset"].includes(type)) return "button";
              return "input";
            }
            if (element.matches(".field-help[tabindex]")) return "help-control";
            if (element.getAttribute("role") === "button") return "button-role";
            return null;
          };

          const seen = new Set();
          const controls = [];
          let sequence = 0;
          for (const element of document.querySelectorAll(selector)) {
            if (seen.has(element) || !visible(element)) continue;
            seen.add(element);
            if (!element.dataset.uiQaControlId) {
              element.dataset.uiQaControlId = `ui-control-${sequence}`;
            }
            sequence += 1;
            const details = element.tagName === "SUMMARY" ? element.closest("details") : null;
            controls.push({
              id: element.dataset.uiQaControlId,
              family: familyFor(element),
              tag: element.tagName.toLowerCase(),
              type: String(element.getAttribute("type") || ""),
              text: diagnosticLabel(element).slice(0, 140),
              disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
              detailsClasses: details ? String(details.className || "") : "",
              detailsOpen: details ? Boolean(details.open) : null,
            });
          }
          return controls;
        }
        """,
        _INTERACTIVE_SELECTOR,
    )
    if not isinstance(result, list):
        raise ui.UIInvariantError("Interactive component discovery did not return a list.")
    return [item for item in result if isinstance(item, dict)]


def family_counts(controls: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("family") or "unclassified") for item in controls)
    return dict(sorted(counts.items()))


def assert_component_coverage(controls: Sequence[Mapping[str, Any]]) -> None:
    unclassified = [item for item in controls if not str(item.get("family") or "").strip()]
    if not unclassified:
        return
    labels = [
        f"{item.get('tag')}:{str(item.get('text') or item.get('id') or '')[:60]}"
        for item in unclassified[:8]
    ]
    suffix = "" if len(unclassified) <= 8 else f"; +{len(unclassified) - 8} more"
    raise ui.UIInvariantError(
        "Visible interactive controls are not assigned to a maintained component family: "
        + "; ".join(labels)
        + suffix
    )


def capture_control_readability(page: Any, control_id: str) -> dict[str, Any]:
    result = page.evaluate(
        _READABILITY_SCRIPT,
        {"controlId": control_id, "subtree": False},
    )
    if not isinstance(result, dict):
        raise ui.UIInvariantError(f"Readability probe failed for {control_id!r}.")
    return result


def capture_open_menu_readability(page: Any, control_id: str) -> dict[str, Any]:
    result = page.evaluate(
        _READABILITY_SCRIPT,
        {"controlId": control_id, "subtree": True},
    )
    if not isinstance(result, dict):
        raise ui.UIInvariantError(f"Open-menu readability probe failed for {control_id!r}.")
    return result


def assert_control_readability(
    metric: Mapping[str, Any],
    *,
    label: str,
    min_contrast: float = MIN_TEXT_CONTRAST,
    disabled_min_contrast: float = MIN_DISABLED_TEXT_CONTRAST,
) -> None:
    if not bool(metric.get("visible")):
        raise ui.UIInvariantError(f"{label} is not visible.")

    failures: list[str] = []
    text = str(metric.get("text") or "").strip()
    disabled = bool(metric.get("disabled"))
    contrast = metric.get("contrast")
    if text and isinstance(contrast, (int, float)):
        required = disabled_min_contrast if disabled else min_contrast
        if float(contrast) + 1e-9 < required:
            failures.append(f"text contrast {float(contrast):.2f}:1 < {required:.2f}:1")

    placeholder_contrast = metric.get("placeholderContrast")
    if isinstance(placeholder_contrast, (int, float)) and not disabled:
        if float(placeholder_contrast) + 1e-9 < min_contrast:
            failures.append(
                f"placeholder contrast {float(placeholder_contrast):.2f}:1 < {min_contrast:.2f}:1"
            )

    if bool(metric.get("clipsTextHorizontally")):
        failures.append("text is horizontally clipped")
    if bool(metric.get("clipsTextVertically")):
        failures.append("text is vertically clipped")
    if not bool(metric.get("insideHorizontalScroller")) and bool(metric.get("escapesViewport")):
        failures.append("control escapes the viewport")

    interactive = bool(metric.get("interactive", True))
    if interactive and not disabled and not bool(metric.get("keyboardFocusable")):
        failures.append("interactive control is not keyboard-focusable")

    if failures:
        raise ui.UIInvariantError(f"{label}: " + "; ".join(failures))


def assert_open_menu_readability(metric: Mapping[str, Any], *, label: str) -> None:
    failures: list[str] = []
    if not bool(metric.get("open")):
        failures.append("menu did not open")
    if not bool(metric.get("panelVisible")):
        failures.append("open panel is not visible")
    if bool(metric.get("panelEscapesViewport")):
        failures.append("open panel escapes the viewport horizontally")
    if not bool(metric.get("panelTopmost")):
        failures.append("open panel is occluded by another element")

    descendants = metric.get("descendants")
    if not isinstance(descendants, list):
        failures.append("open panel readability descendants are missing")
    else:
        for index, descendant in enumerate(descendants):
            if not isinstance(descendant, Mapping):
                failures.append(f"descendant #{index} returned malformed metrics")
                continue
            try:
                assert_control_readability(
                    descendant,
                    label=f"{label} descendant #{index} {str(descendant.get('text') or '')[:50]}",
                )
            except ui.UIInvariantError as exc:
                failures.append(str(exc))

    if failures:
        suffix = "" if len(failures) <= 8 else f"; +{len(failures) - 8} more"
        raise ui.UIInvariantError(f"{label}: " + "; ".join(failures[:8]) + suffix)


def focus_control(page: Any, control_id: str, *, timeout_ms: int) -> None:
    selector = f'[data-ui-qa-control-id="{_escape_attribute(control_id)}"]'
    locator = page.locator(selector)
    locator.focus(timeout=min(max(1, timeout_ms), 3000))
    focused = locator.evaluate(
        "(element) => document.activeElement === element || element.contains(document.activeElement)"
    )
    if not focused:
        raise ui.UIInvariantError(f"Control {control_id!r} did not accept keyboard focus.")


def open_menu(page: Any, control_id: str, *, timeout_ms: int) -> None:
    selector = f'[data-ui-qa-control-id="{_escape_attribute(control_id)}"]'
    summary = page.locator(selector)
    summary.click(timeout=min(max(1, timeout_ms), 3000))
    page.wait_for_function(
        """
        (controlId) => {
          const summary = document.querySelector(
            `[data-ui-qa-control-id="${CSS.escape(controlId)}"]`
          );
          const details = summary?.closest("details");
          return details instanceof HTMLDetailsElement && details.open === true;
        }
        """,
        arg=control_id,
        timeout=min(max(1, timeout_ms), 3000),
    )
    _settle(page)


def close_menu(page: Any, control_id: str) -> None:
    page.evaluate(
        """
        (controlId) => {
          const summary = document.querySelector(
            `[data-ui-qa-control-id="${CSS.escape(controlId)}"]`
          );
          const details = summary?.closest("details");
          if (details instanceof HTMLDetailsElement) details.open = false;
        }
        """,
        control_id,
    )
    _settle(page)


def set_theme(page: Any, theme: str) -> None:
    if theme not in {"light", "dark"}:
        raise ValueError(f"Unsupported deterministic UI theme {theme!r}.")
    page.evaluate(
        """
        (theme) => {
          document.documentElement.dataset.themePreference = theme;
          document.documentElement.dataset.theme = theme;
        }
        """,
        theme,
    )
    _settle(page)


def _settle(page: Any) -> None:
    page.evaluate(
        """
        () => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        })
        """
    )


def _escape_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_READABILITY_SCRIPT = r"""
({controlId, subtree}) => {
  const summary = document.querySelector(
    `[data-ui-qa-control-id="${CSS.escape(controlId)}"]`
  );
  if (!summary) return null;
  const details = summary.closest("details");

  const rgba = (value) => {
    const match = String(value || "").match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const parts = match[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    if (parts.length < 3 || parts.slice(0, 3).some(Number.isNaN)) return null;
    return {
      r: Math.max(0, Math.min(255, parts[0])),
      g: Math.max(0, Math.min(255, parts[1])),
      b: Math.max(0, Math.min(255, parts[2])),
      a: parts.length >= 4 && !Number.isNaN(parts[3]) ? Math.max(0, Math.min(1, parts[3])) : 1,
    };
  };
  const composite = (front, back) => {
    const a = front.a + back.a * (1 - front.a);
    if (a <= 0) return {r: 0, g: 0, b: 0, a: 0};
    return {
      r: (front.r * front.a + back.r * back.a * (1 - front.a)) / a,
      g: (front.g * front.a + back.g * back.a * (1 - front.a)) / a,
      b: (front.b * front.a + back.b * back.a * (1 - front.a)) / a,
      a,
    };
  };
  const effectiveBackground = (element) => {
    const theme = document.documentElement.dataset.theme;
    let result = theme === "dark"
      ? {r: 14, g: 23, b: 25, a: 1}
      : {r: 238, g: 241, b: 237, a: 1};
    const chain = [];
    for (let current = element; current; current = current.parentElement) chain.push(current);
    chain.reverse();
    for (const current of chain) {
      const layer = rgba(getComputedStyle(current).backgroundColor);
      if (layer && layer.a > 0) result = composite(layer, result);
    }
    return result;
  };
  const luminance = (color) => {
    const linear = (channel) => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * linear(color.r) + 0.7152 * linear(color.g) + 0.0722 * linear(color.b);
  };
  const contrast = (front, back) => {
    const frontOpaque = composite(front, back);
    const high = Math.max(luminance(frontOpaque), luminance(back));
    const low = Math.min(luminance(frontOpaque), luminance(back));
    return (high + 0.05) / (low + 0.05);
  };
  const hasHorizontalScroller = (element) => {
    for (let current = element.parentElement; current && current !== document.body; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (["auto", "scroll"].includes(style.overflowX) && current.scrollWidth > current.clientWidth + 1) {
        return true;
      }
    }
    return false;
  };
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
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
  const isInteractive = (element) => element.matches([
    "summary",
    "select",
    "textarea",
    "button",
    "a[href]",
    'input:not([type="hidden"])',
    '[role="button"]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(","));
  const visibleTextMarker = (element) => {
    const tag = element.tagName.toLowerCase();
    if (tag === "select") {
      return String(element.selectedOptions?.[0]?.textContent || "").trim().slice(0, 180);
    }
    if (["input", "textarea"].includes(tag)) {
      return element.value ? "[value]" : "";
    }
    return String(element.innerText || element.textContent || "").trim().slice(0, 180);
  };
  const metric = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const background = effectiveBackground(element);
    const foreground = rgba(style.color);
    const placeholderStyle = element.matches("input, textarea")
      ? getComputedStyle(element, "::placeholder")
      : null;
    const placeholderColor = placeholderStyle ? rgba(placeholderStyle.color) : null;
    const text = visibleTextMarker(element);
    const overflowX = style.overflowX;
    const overflowY = style.overflowY;
    return {
      tag: element.tagName.toLowerCase(),
      text,
      visible: visible(element),
      interactive: isInteractive(element),
      disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
      keyboardFocusable: element.tabIndex >= 0,
      contrast: foreground ? contrast(foreground, background) : null,
      placeholderContrast: (
        element.getAttribute("placeholder") && placeholderColor
          ? contrast(placeholderColor, background)
          : null
      ),
      color: style.color,
      background: `rgba(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)}, ${background.a.toFixed(3)})`,
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowX,
      overflowY,
      clipsTextHorizontally: (
        ["hidden", "clip"].includes(overflowX)
        && element.scrollWidth > element.clientWidth + 1
      ),
      clipsTextVertically: (
        ["hidden", "clip"].includes(overflowY)
        && element.scrollHeight > element.clientHeight + 1
      ),
      insideHorizontalScroller: hasHorizontalScroller(element),
      escapesViewport: rect.left < -1 || rect.right > window.innerWidth + 1,
    };
  };

  const base = metric(summary);
  if (!subtree) return base;
  if (!(details instanceof HTMLDetailsElement)) return {...base, open: false};
  const panel = Array.from(details.children).find((child) => child.tagName !== "SUMMARY");
  if (!panel) return {...base, open: details.open, panelVisible: false};
  const panelRect = panel.getBoundingClientRect();
  const sampleX = Math.min(
    window.innerWidth - 2,
    Math.max(1, panelRect.left + Math.min(panelRect.width / 2, 24))
  );
  const sampleY = Math.min(
    window.innerHeight - 2,
    Math.max(1, panelRect.top + Math.min(panelRect.height / 2, 24))
  );
  const topmost = document.elementFromPoint(sampleX, sampleY);
  const descendantSelector = [
    "summary",
    "button",
    "a[href]",
    "select",
    "textarea",
    'input:not([type="hidden"])',
    "label",
    "span",
  ].join(",");
  const descendants = Array.from(panel.querySelectorAll(descendantSelector))
    .filter((element) => visible(element))
    .filter((element) => Boolean(
      visibleTextMarker(element) || element.getAttribute("placeholder")
    ))
    .filter((element) => !Array.from(element.children).some(
      (child) => visible(child) && Boolean(
        visibleTextMarker(child) || child.getAttribute("placeholder")
      )
    ))
    .map(metric);
  return {
    ...base,
    open: details.open,
    panelVisible: visible(panel),
    panelEscapesViewport: panelRect.left < -1 || panelRect.right > window.innerWidth + 1,
    panelTopmost: Boolean(topmost && (panel === topmost || panel.contains(topmost))),
    descendants,
  };
}
"""

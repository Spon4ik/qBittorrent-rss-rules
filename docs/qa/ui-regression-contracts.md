# UI regression contracts

The browser QA model is property-first rather than screenshot-first. A reported UI
symptom must be translated into a reusable invariant and applied to every sibling
component that shares the same behavioral or visual contract.

## Maintained contracts

| Check | Scope | Defect classes prevented |
| --- | --- | --- |
| `UI-01` | Core responsive pages | document overflow, action overlap, viewport escape |
| `UI-02` | Rule-header diagnostics | unrelated action movement when a disclosure changes state |
| `UI-03` | Result toolbar menus | sibling-menu interaction, Escape/outside close, overlay reflow, hidden queue options |
| `UI-04` | Every visible generic top-level `details`/menu surface | unsampled disclosure/menu interaction and layout regressions |
| `UI-05` | Every visible interactive component across core pages, light/dark themes, and responsive widths | unclassified components, unreadable contrast, clipped text, viewport escape, keyboard-focus loss, hover/focus readability, menu occlusion, and non-functioning checkbox-menu choices |

`UI-04` and `UI-05` are exhaustive coverage gates. They do not intentionally sample
only the first N controls. A high fail-safe ceiling exists only to detect runaway
or malformed discovery; reaching it is itself a failure.

Dedicated exclusions from a generic check are allowed only when they are mapped to
another maintained `UI-*` contract. The suite fails if an exclusion exists without
an explicit replacement contract.

## Issue-to-invariant workflow

For every reported UI defect:

1. Reproduce the reported symptom with deterministic DOM/browser evidence when
   possible.
2. Identify the violated property: readability, containment, alignment, overlay
   behavior, state transition, selection behavior, etc.
3. Identify the component family or common interaction class rather than only the
   concrete control named in the report.
4. Extend the lowest-cost existing invariant that can cover the whole family. Add
   a dedicated check only when the behavior is genuinely unique.
5. Ensure the originally reported instance is discovered by the generalized
   matrix and that all visible siblings are exercised by the same contract.
6. Fix the shared component implementation where possible instead of adding a
   one-instance CSS/JS override.
7. Run the focused invariant first, then `scripts\\browser_qa.bat --suite ui`, and
   finally the normal broader completion gate when deployable code changed.
8. Keep screenshots only as failure evidence when DOM/state/computed-style checks
   cannot prove the visual property.

## Component-family inventory

`UI-05` currently classifies visible controls into maintained families including:

- checkbox dropdowns (the shared Language/feed family);
- search multiselects;
- toolbar menus;
- generic/diagnostic disclosures;
- native selects;
- text inputs and textareas;
- checkboxes/radios;
- file inputs;
- buttons, button-role controls, and links;
- keyboard-focusable help controls.

A visible interactive element that cannot be classified fails the suite rather
than silently falling outside coverage. Menu-family instances are opened and
checked for panel visibility, horizontal containment, topmost/occlusion state,
and descendant readability. When an enabled checkbox choice exists, the suite
activates it and restores its original state in the isolated QA runtime.

## Readability evidence

The component contract uses browser-computed styles and DOM geometry, including:

- effective foreground/background contrast;
- placeholder contrast;
- normal, hover, and keyboard-focus states;
- text clipping and viewport containment;
- open-panel containment and occlusion;
- keyboard focusability for interactive controls.

Normal text uses a minimum `4.5:1` contrast contract; disabled text uses `3:1`.
This is deterministic browser evidence, not image interpretation.

# Cross-surface consistency contracts

The project treats repeated concepts as shared contracts, not as unrelated controls
that happen to look similar. A defect reported on one surface must be expanded to
all siblings that implement the same concept before the task can close.

## Contract axes

Every user-facing interaction is evaluated on two independent axes.

### Component family

This owns presentation and interaction mechanics: dropdowns, selects, buttons,
inputs, disclosures, toolbar menus, status chips, tables, action groups, and other
reusable UI primitives.

A component-family contract covers properties such as:

- light/dark readability and contrast;
- normal, hover, focus, selected, checked, disabled, and open states where relevant;
- clipping, overlap, viewport containment, scrolling, and overlay/reflow behavior;
- keyboard focus and component-specific close/open behavior;
- responsive behavior across the maintained viewport matrix.

`UI-04`/`UI-05` own the existing exhaustive component-family layer.

### Action family

This owns what a command means regardless of which page presents it. Examples are
`sync`, `fetch-snapshot`, `queue`, `refresh-feeds`, `retry-acceleration`, and
`delete-rule`.

An action-family contract covers:

- one canonical leading verb and terminology;
- the same destructive/non-destructive meaning everywhere;
- the same confirmation requirement for destructive actions;
- a consistent busy/progress/error/success lifecycle for long-running actions;
- consistent scope language (`rule`, `selected`, `all`, `scheduled scope`, etc.);
- the same backend/service semantic boundary even when presentation differs
  between a compact row icon and a full text button.

`scripts/cross_surface_contracts.py` is the registry. The cheap
`scripts/cross_surface_guard.py` scans POST forms and frontend POST requests and
fails the normal gate when a user command cannot be assigned to a maintained
action family. It writes `logs/qa/cross-surface-guard.json`.

## Cross-page browser audit

`scripts/cross_surface_browser_qa.py` uses the isolated focused browser runtime.
It discovers user pages from the application's own primary/settings navigation,
adds deterministic dynamic pages such as a seeded rule-edit page, and audits the
discovered page set across the maintained light/dark and responsive matrix.

For each page it:

1. expands ordinary initially closed disclosures so their controls cannot escape
   inventory;
2. classifies and checks all resulting interactive component instances;
3. discovers command surfaces from POST forms and maintained JS action markers;
4. maps those commands to the action registry;
5. rejects unknown action families and inconsistent canonical verbs;
6. requires destructive form commands to expose danger + confirmation semantics;
7. records compact machine-readable evidence.

The canonical `scripts\\browser_qa.bat --suite ui` and Linux equivalent run this
cross-surface audit after the focused `UI-*` suite. A local UI closeout therefore
cannot pass merely because one representative page or one instance was correct.

## Issue expansion workflow

For any past or future defect, use this order:

1. Reproduce the exact reported failure.
2. Identify the violated property or business action, not only the DOM selector or
   endpoint named in the report.
3. Identify the component family, action family, service/API boundary, or data
   invariant that owns that property.
4. Enumerate siblings from code/DOM/routes rather than from memory.
5. Strengthen the shared invariant so the reported instance and all siblings are
   covered.
6. Fix the shared implementation where possible; avoid per-page/per-ID patches.
7. Validate narrowly, then run the family/cross-surface gate, then the normal
   completion gate and deployed-runtime validation when applicable.

The same rule applies beyond UI. A malformed database value should become a table
or schema invariant; an API error should become an endpoint-family/error-boundary
contract; a scheduler failure should become a scheduler-state invariant; a runtime
command problem should become a maintained operational tool rather than another
one-off shell command.

## Presentation variants are not semantic exceptions

The same action may be rendered differently when context requires it (for example,
an icon-only table action versus a text button in a card). That is a presentation
variant, not permission to change the action's name, destructive scope, progress
semantics, or backend meaning.

When a genuine semantic difference exists, model it as a different action family
or explicit scope instead of silently overloading one label with different
behavior.

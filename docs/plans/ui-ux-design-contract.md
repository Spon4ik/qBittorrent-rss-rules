# UI/UX Design Contract

Last updated: 2026-05-05

## 1) Layout principles

- Information-dense where users operate repeatedly (Rules, Search, Rule Form).
- Strong hierarchy: status and next action first; advanced controls second.
- Stable placement for destructive and primary actions.

## 2) Viewport usage principles

- Use full available width on medium/wide screens for tabular workflows.
- Avoid narrow centered columns for dense data unless reading-focused page.
- Vertical space should favor visible rows over decorative spacing.

## 3) Responsive behavior

- **Narrow (<900px)**: single-column, collapsible advanced sections, sticky key actions.
- **Medium (900–1400px)**: two-column form/workspace splits, compact controls.
- **Wide (>1400px)**: expanded tables, side-by-side comparison controls, reduced wrapping.

## 4) Density and component rules

- Tables for rule/search operations and sortable comparisons.
- Cards for optional alternate browsing only.
- Badges for state chips (sync, release confidence, mode).
- Tooltips for compact icon actions only when labels are otherwise ambiguous.

## 5) Icons vs text buttons

Use icon buttons for row-local repeated actions (move/delete/retry) with:
- clear shape,
- tooltip/title,
- accessible label.
Use text buttons for primary cross-row actions.

## 6) Inline editing / modal / drawer

- Inline edit for simple scalar fields and per-row toggles.
- Modal only for confirmations/destructive operations.
- Drawer for deep diagnostics that should not navigate away.

## 7) Empty/error/loading patterns

- Empty: one-line cause + one primary CTA.
- Error: clear cause + remediation step + retry action.
- Loading/background: non-blocking progress indicators with latest status text.

## 8) Accessibility + keyboard/mouse

- Full keyboard access for form fields, multiselects, and row actions.
- Visible focus ring and consistent tab order.
- Color state chips must have text labels (not color-only meaning).

## 9) Page-by-page desired layout

- Rules: sticky filter row + sticky table header + compact batch/schedule strip.
- Rule Form: sticky action footer, compact criteria sections, explicit mode indicator (Managed/Manual).
- Search: table-first with persistent sort/filter controls and hidden-row explanation toggles.
- Settings: segmented sections; quality preset management in compact comparative control.
- Taxonomy: structured editor first, raw JSON advanced section collapsed by default.

## 10) Manage preset quality filters redesign direction

Current repeated include/exclude checklists are hard to scan and compare.
Preferred direction: **matrix editor** with progressive complexity:
- Rows: taxonomy tokens (grouped + collapsible by taxonomy group).
- Columns: preset profiles.
- Cell state: Include / Exclude / Neutral (tri-state).
- Optional per-column summary counts + quick filter (show only non-neutral rows).

Why this over duplicated lists:
- Faster cross-profile comparison.
- Lower scroll burden.
- More obvious conflict detection.

Fallback if matrix complexity is too high for first pass:
- Two-column diff view (selected preset vs baseline) with compact token rows.

## 11) Existing patterns to keep

- Rules page table/card dual-mode toggle.
- Inline sync error surfacing in rules list.
- Taxonomy structured add/move/remove controls with audit and preview.
- Search hidden-row reasoning and active-filter chips.

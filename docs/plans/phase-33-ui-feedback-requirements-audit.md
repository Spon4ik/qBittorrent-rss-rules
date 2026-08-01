# Phase 33 UI Feedback Requirements Audit

Date: 2026-06-02

## User Requirements

1. Result scrolling must happen only inside the result table area, not on the whole page.
2. The `Rule settings` section should not be collapsed if collapsing it does not create useful space for the workflow.
3. Expanding or showing `Rule settings` must not create an overlapped menu or controls.
4. `Start season` and `Start episode` should be combined into one row.
5. Explanatory text below buttons or fields should be removed from the visible layout.
6. The metadata lookup explanation, `Search by title or provider-specific ID using services relevant to the selected media type.`, should be available as hover/focus help on the relevant field or control instead of visible text below it.
7. The quality authority explanation, for example `This rule keeps its current include/exclude tokens until you choose a managed profile.`, should be available as hover/focus help on the relevant button or text/control instead of visible text below `Quality authority` / `Manual snapshot`.

## Current Implementation Comparison

| Requirement | Current evidence | Status | Notes |
| --- | --- | --- | --- |
| 1. Result scrolling only inside the result table area | Rendered Docker metrics at 1600x900 for `/rules/eb4c40e3-d012-4835-bdf2-39c34c064eba` show `documentNeedsVerticalScroll=false`, `.search-table-wrap` `overflowY=auto`, `scrollHeight=20042`, `clientHeight=205`, and `tableWrapCanScroll=true`. | Achieved | The long result set scrolls in the table wrapper, not the page. |
| 2. `Rule settings` should not collapse when collapse is not useful | `app/templates/rule_form.html` now renders `<section class="rule-settings-panel" data-rule-settings-panel>` and no longer renders `data-rule-settings-drawer`; rendered Docker metrics show `oldDrawerExists=false`. | Achieved | The outer Rule settings rail is no longer collapsible. |
| 3. Showing `Rule settings` must not overlap menu/controls | Rendered Docker metrics for both audited edit pages show `settingsOverlapsInline=false`. | Achieved | The settings rail is viewport-contained and independently scrollable. |
| 4. Combine `Start season` and `Start episode` into one row | `app/templates/rule_form.html` renders one `.episode-floor-field` with label `Start season / episode` and a `.paired-input-row` containing both inputs; rendered metrics confirm `combinedFloor=true`. | Achieved | The separate rows are gone. |
| 5. Remove visible explanatory text below buttons/fields | Rendered Docker metrics show `visibleMetadataSentence=false` and `visibleQualitySentence=false` for the two quoted texts. | Achieved for reported copy | The specific visible helper paragraphs called out in feedback are no longer visible in the edit layout. |
| 6. Metadata lookup explanation should be hover/focus help on the relevant field/control | `#metadata-lookup-value` and `#metadata-lookup` carry `title="Search by title or provider-specific ID using services relevant to the selected media type."`; rendered metrics confirm those title values. | Achieved | The help is on the relevant text box and button, not a separate visible paragraph. |
| 7. Quality authority explanation should be hover/focus help on the relevant button/text/control | The quality mode label and action buttons carry dynamic `title` / `aria-label`; rendered metrics confirm the active label and manual button expose the quality help. | Achieved | The help is on the actual quality mode text/control. |

## Goal Achievement Summary

The current result achieves the audited feedback requirements for the desktop edit-page layout.

Verified evidence:

- Long-result rule `eb4c40e3-d012-4835-bdf2-39c34c064eba`: document width/height equals viewport (`1600x900`), result table wrapper scrolls internally (`20042 > 205`), Rule settings does not overlap the results panel, and the quoted helper text is not visible.
- Filtered-empty rule `ef129ee1-98f9-494d-b502-5d280bf9ba30`: document width/height equals viewport (`1600x900`), Rule settings does not overlap the results panel, the old drawer is absent, and quoted helper text remains hidden from visible body text while present on relevant control titles.
- Internal settings-rail overlap check: targeted rendered metrics for `Quality authority` vs `Criteria / Core Identity` now show both panels stacked full-width (`grid-column: 1 / -1`), `parentOverlap=false`, and no Quality authority descendants intersect the Core Identity rectangle. The earlier gate was insufficient because it checked only outer Rule settings vs result-panel rectangles, not child overflow inside the settings rail.

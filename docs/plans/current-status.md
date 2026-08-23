# Current Status

## Current focus

### SQLite corruption recovery

Closed on `experiment/codex-token-efficiency`. The recovered production database is
healthy, the verified activation rollback remains available, Docker is current on
`v1.4.20`, and deployed F-01/F-02/F-03 previously passed with zero unhandled API
exceptions.

### Scheduled-fetch status reconciliation

The branch now separates historical scheduled-run evidence from current scheduler
health. A persisted historical `partial`/`error` remains available as history, but
current status is derived from scheduler/runtime readiness and scheduled-scope
snapshot freshness. The Rules page should lead with the current healthy/degraded
state instead of presenting an old partial run as the active failure.

Regressions live in `tests/test_scheduled_fetch_current_state.py` and
`tests/test_scheduled_fetch_status_ui.py`. This follow-up still requires local
focused validation, normal gate, Docker deployment, and deployed Rules-page proof.

### Systematic UI regression coverage

The previous generic UI audit sampled only the first eight interactive surfaces per
page, allowing sibling controls such as the rule Language/feed checkbox-dropdown
family to escape coverage. That sampling model has been replaced.

- `UI-04` now treats generic disclosure/menu discovery as exhaustive. The high
  ceiling is only a runaway guard; reaching it fails coverage. Dedicated generic
  exclusions must map to an explicit maintained `UI-*` replacement contract.
- `UI-05` first expands ordinary non-menu disclosures so controls hidden by the
  page's initial collapsed state cannot escape inventory. Menu families remain
  closed until their own open-state checks run.
- `UI-05` inventories every resulting visible interactive control on the maintained
  core-page matrix across light/dark themes and 390/1180/1720 widths. Every control
  must map to a known component family and pass deterministic normal/hover/focus
  contrast, clipping, viewport, focusability, open-panel containment/occlusion,
  and menu-readability checks.
- Checkbox-based menu families exercise one enabled real choice and restore its
  original state in the isolated QA runtime, so appearance-only success is not
  enough.
- QA evidence is value-safe: arbitrary input/textarea values are not persisted in
  component metrics; diagnostics use field metadata or a redacted `[value]` marker.
- `app/static/components.css` moves the shared checkbox-dropdown/search-multiselect
  family and feed option surfaces onto semantic theme palette variables. This
  removes the hard-coded light feed surfaces that could make dark-theme text
  unreadable. The stylesheet is loaded globally and participates in static asset
  cache versioning.
- The maintained rationale and issue-to-family workflow are documented in
  `docs/qa/ui-regression-contracts.md`.

Focused unit regressions were added for exhaustive component coverage, closed-
disclosure inventory, readability, menu behavior, and shared styles. ChatGPT Web
has not executed the local Playwright/browser suite, so this UI work is not closed
until Codex runs the new unit tests, `scripts\browser_qa.bat --suite ui`, the
normal completion gate, updates Docker, and proves the deployed affected controls
pass.

### Changelog freshness

`CHANGELOG.md` had again fallen behind implementation. A deterministic
`scripts/changelog_guard.py` is now part of both `scripts/check.bat` and
`scripts/check.sh`. It fails when implementation/runtime/maintained-QA tooling is
newer than the latest changelog update, and it writes compact evidence to
`logs/qa/changelog-guard.json`. The latest changelog commit is intentionally newer
than the current implementation/QA-tooling commits, turning this closeout convention
into a mechanical gate instead of relying on memory.

### Phase 44

Phase 44 remains in implementation under
`docs/plans/phase-44-acceleration-operations-console.md`. Its unrelated remaining
acceptance item is end-to-end automatic Codex heartbeat pickup/status readback.

## Handoff discipline

`current-status.md` is a short live handoff, not a historical release ledger or a
second policy layer. Historical release detail belongs in Git history,
`CHANGELOG.md`, and phase plans. If status text conflicts with `AGENTS.md`, correct
the stale status instead of introducing another approval boundary.

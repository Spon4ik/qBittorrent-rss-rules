# Current Status

## Current focus

### SQLite corruption recovery

Closed on `experiment/codex-token-efficiency`. The recovered production database is
healthy, the verified activation rollback remains available, and deployed
F-01/F-02/F-03 previously passed with zero unhandled API exceptions.

### Scheduled-fetch status reconciliation

The branch separates historical scheduled-run evidence from current scheduler
health. Historical `partial`/`error` remains available as evidence while current
status is derived from scheduler/runtime readiness and scheduled-scope freshness.
This follow-up still requires local focused validation, normal gate, Docker
rebuild, and deployed Rules-page proof.

### Repository-wide cross-surface consistency

The Language/feed dropdown defect is treated as one example of a broader contract,
not as a special-case UI fix. The repository now has two complementary family
layers.

- **Component families:** `UI-04`/`UI-05` and the cross-surface browser audit
  inventory controls across pages, including controls initially hidden in ordinary
  disclosures. They exercise light/dark and 390/1180/1720 states, normal/hover/
  focus/open behavior, readability/contrast, clipping/containment, keyboard
  behavior, menu occlusion, and reversible checkbox choices. Shared form/menu
  families also get computed foreground/background palette-consistency checks so
  individually readable page-specific styling cannot silently drift.
- **Action families:** `scripts/cross_surface_contracts.py` models common command
  semantics such as Sync, Save + Sync, Fetch snapshot, Queue, Retry, Save/Create,
  taxonomy Add/Move/Remove/Validate/Apply, and destructive Remove/Delete. The
  family owns canonical terminology, scope semantics, destructive policy,
  confirmation, and long-running feedback expectations rather than each page
  inventing its own behavior.
- `scripts/cross_surface_guard.py` is part of the normal check gate. It inventories
  POST forms, individual `formaction` submit commands, submit buttons owned by an
  external form, and frontend POST requests. Unknown command families, inconsistent
  narrow-family terminology, and unsafe destructive form actions fail the gate.
- `scripts/cross_surface_browser_qa.py` discovers stable app pages from the app's
  own navigation plus deterministic dynamic routes, applies the component and
  action contracts across that page set, and accumulates sibling failures instead
  of stopping at the first reported instance. `scripts\browser_qa.bat --suite ui`
  now runs this audit after the focused `UI-*` suite.
- Generic exclusions must map to explicit maintained replacement contracts. A real
  semantic difference must be modeled as a distinct family/mode instead of adding
  aliases or per-page exceptions.
- Taxonomy value removal already exposed and fixed one cross-surface safety defect:
  it now uses danger styling plus concrete confirmation behavior.

The source of truth for the methodology is
`docs/qa/cross-surface-consistency.md`, with UI-specific detail in
`docs/qa/ui-regression-contracts.md` and standing requirements in `AGENTS.md`.

Known current inconsistencies must be fixed, not waived, when the local audit runs.
In particular, the snapshot-fetch family currently uses mixed vocabulary on some
surfaces (`Run now`, `Refresh Search Snapshot`, `Run Search Snapshot`, `Refresh
snapshot`, or `Search`) instead of one Fetch-snapshot vocabulary. The new audit is
expected to turn those into actionable family-level failures.

ChatGPT Web has not executed the new Python tests or Playwright suite. This work is
not closed until Codex runs the focused cross-surface tests, `scripts\check.bat`,
`scripts\browser_qa.bat --suite ui`, fixes every discovered family inconsistency,
runs the normal completion gate, deploys the current checkout, and proves the
current runtime. Because deployable template code changed, the previous Docker
runtime must not be treated as validation of this checkout.

### Changelog freshness

`scripts/changelog_guard.py` is part of both normal check gates and fails when
implementation/runtime/maintained-QA tooling is newer than `CHANGELOG.md`. The
current `[Unreleased]` section records the cross-surface consistency work and its
Taxonomy safety fix; commit `7ce0b93d` changes only `[Unreleased]`.

### Phase 44

Phase 44 remains in implementation under
`docs/plans/phase-44-acceleration-operations-console.md`. Its unrelated remaining
acceptance item is end-to-end automatic Codex heartbeat pickup/status readback.

## Handoff discipline

`current-status.md` is a short live handoff, not a historical release ledger or a
second policy layer. Historical release detail belongs in Git history,
`CHANGELOG.md`, and phase plans. If status text conflicts with `AGENTS.md`, correct
the stale status rather than introducing another approval boundary.

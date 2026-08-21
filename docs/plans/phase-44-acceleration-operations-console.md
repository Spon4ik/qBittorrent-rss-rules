# Phase 44 - Acceleration operations console and variant context

## Status

In implementation. UI/API behavior is implemented and live-smoke-tested; automatic
Codex heartbeat pickup remains pending end-to-end proof after the active task yields.

## Product decision

The global background strip is a progress surface, not an operations console. It
shows only currently queued/running transient work. If acceleration failures need
attention, it shows one compact count linking to `/acceleration`.

`/acceleration` is the centralized torrent-level maintenance screen. It provides:

- problem, active, finished, and all filters;
- torrent-name/hash search;
- full torrent name, provider state/error, update time, and secondary hash reference;
- Retry, Ask Codex, Dismiss, and Remove acceleration actions with explicit scope.

Rule search variants are correlated to acceleration jobs only through exact
infohash equality. A matching card/table row shows current acceleration state and
compact Retry/Ask Codex actions. Category or title inference is forbidden.

## Safety contract

- Retry affects only the exact acceleration job.
- Dismiss changes notification visibility only.
- Remove acceleration removes app-owned web seeds/job state but not torrent/files.
- Ask Codex persists a redacted, deduplicated job request.
- The short hash is diagnostic identity, never a rule label.

## Validation status

- The experiment branch now also has a reusable deterministic UI-invariants audit,
  implemented early by explicit user request before the next UI-fix task. This is
  QA infrastructure only and does not change Phase 44 product behavior or waive
  the remaining automatic heartbeat acceptance criterion. The canonical Windows
  command is `scripts\browser_qa.bat --suite ui`. It checks representative core
  responsive pages for document-level overflow, the qB-diagnostics closed/open
  rule-header transition for overlap/containment/unexpected desktop horizontal
  movement, and the existing Result-toolbar interaction/reflow contract. The
  suite records DOM metrics and uses screenshots only as failure evidence. Known
  deterministic UI failures are allowed to remain red until the later UI-fix task;
  they are not quarantined merely to make the audit pass.
- Browser-QA iteration now has venv-aware wrappers. On Windows,
  `scripts\browser_qa.bat --check P44-03` runs only the maintained Result-toolbar
  regression and `scripts\browser_qa.bat --phase 44` selects all maintained Phase
  44 focused checks. The wrapper follows the repository's existing interpreter
  contract by preferring `.venv\Scripts\python.exe`; direct global-Python execution
  is not the canonical path because it can miss project dependencies. Linux/WSL
  uses `scripts/browser_qa.sh` with the equivalent behavior. Browser-wide legacy
  coverage is reserved for one wrapper `--full` closeout run, which preserves the
  raw report and emits compact dependency/quarantine-aware evidence for Codex.
  Dependency cascades such as P7/P33 after P6-05 are classified as blocked; only
  mechanically audited stale legacy contracts are quarantined, while uncertain
  semantic P5/P6 failures stay actionable.
- Follow-up `v1.4.19` fixes Result controls menu interaction and queue-option
  visibility. The toolbar's three menu-style controls close on outside click,
  Escape, and sibling opening; Queue options no longer overlays Sequential
  download with First and last pieces first. The deterministic P44-03 browser
  check asserts those state transitions plus desktop alignment, no layout
  movement, and narrow-screen overflow invariants.
- Follow-up `v1.4.18` consolidates the result and queue controls into one
  aligned wide-desktop toolbar, uses compact normal-case queue labels, and
  extends readable non-expanding dark disclosures to the left rule-settings
  rail. Live measurements show identical indexer/category/queue dropdown Y
  coordinates, unchanged toolbar height with each menu open, zero downstream
  field shift when Language opens, and zero page overflow. Ruff/mypy and all
  `549` tests pass, WinUI is zero-warning, and Docker serves `v1.4.18`. PR
  `#43`, annotated tag `v1.4.18`, and the GitHub Release are published.
- Follow-up `v1.4.17` UI hardening restores readable dark-mode filtered-result
  text, aligns the rule Result controls responsively, and makes result indexer/
  category menus overlay the table instead of expanding the sticky toolbar.
  Live Docker screenshots cover the closed toolbar, open overlay, visible
  filtered rows, Search page, and acceleration page. The final 1180/2048px
  checks have zero page overflow and opening a menu leaves the toolbar height
  unchanged; the full `549`-test gate and zero-warning WinUI build pass. PR
  `#42`, annotated tag `v1.4.17`, and the GitHub Release are published.
- Ruff/mypy and all 549 tests pass; the WinUI build is zero-warning.
- Live Docker `/acceleration` has zero horizontal overflow at 2048x1150 and renders
  centralized problem rows/actions.
- Live Reacher rule variants expose acceleration context for exact matching hashes;
  notices remain collapsed and there is zero horizontal overflow.
- The real queued Codex request is persisted but has not yet been claimed while
  this owning task is active. Completion requires status transition and UI readback.

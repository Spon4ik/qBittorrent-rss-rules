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

- Follow-up `v1.4.17` UI hardening restores readable dark-mode filtered-result
  text, aligns the rule Result controls responsively, and makes result indexer/
  category menus overlay the table instead of expanding the sticky toolbar.
  Live Docker screenshots cover the closed toolbar, open overlay, visible
  filtered rows, Search page, and acceleration page. The final 1180/2048px
  checks have zero page overflow and opening a menu leaves the toolbar height
  unchanged; the full `549`-test gate and zero-warning WinUI build pass.
- Ruff/mypy and all 549 tests pass; the WinUI build is zero-warning.
- Live Docker `/acceleration` has zero horizontal overflow at 2048x1150 and renders
  centralized problem rows/actions.
- Live Reacher rule variants expose acceleration context for exact matching hashes;
  notices remain collapsed and there is zero horizontal overflow.
- The real queued Codex request is persisted but has not yet been claimed while
  this owning task is active. Completion requires status transition and UI readback.

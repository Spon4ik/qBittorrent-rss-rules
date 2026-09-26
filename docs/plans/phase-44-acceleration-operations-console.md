# Phase 44 - Acceleration operations console and variant context

## Governance follow-up (2026-09-26)

The separate [native GitHub delivery and governance plan](2026-09-25-native-github-delivery-governance.md)
tracks stronger TDD/isolation, CI, protected-main and delivery evidence. G1 and
G2 and G3a repository templates are now implemented on `main`; G3b native Project
inspection is pending access. This
governance work does not complete or change Phase 44's product scope. Keep any
unfinished Phase 44 work separate from governance commits.

## Status

In implementation. UI/API behavior is implemented and live-smoke-tested; automatic
Codex heartbeat pickup remains pending end-to-end proof after the active task yields.

## Active follow-up: Real-Debrid WebSeed 400 (issue #48)

The selected Real-Debrid file was unrestricted and its HTTP Range proxy worked,
but qBittorrent rejected `addWebSeeds` with HTTP 400. The cause was qBittorrent's
extra percent-decoding of form data before strict URL validation. The client now
adds the required encoding layer for add/remove and normalizes raw-Unicode API
readback. A pinned qBittorrent 5.2.3 CI integration test creates a temporary
torrent and verifies add, readback, removal, and cleanup. The exact saved job was
retried against the running app; it reached `webseed_attached`, qBittorrent's
readback matched the saved URL, and the proxy returned HTTP 206 for a one-byte
Range request. Focused unit and integration tests pass (`22 passed`). PR #49 was
squash-merged to protected `main` as `ec3cc845`; pinned qBittorrent integration
passed on the PR and merge commit (runs `36197363920` and `36198173177`). Ruleset
`24023362` requires PRs and the integration check, enforces up-to-date heads,
resolved review threads, squash-only merges, and blocks force-push/deletion
without bypass actors. Issue #48 is closed. Post-merge `Finalize-Backend` passed
Ruff/mypy but stopped before Docker after pytest reported 576 passed, 7 failed,
1 skipped: one startup timing test and six resolution-quality expectations.
Issue #50 tracks full-gate recovery. The running app remains v1.4.21; v1.4.22
deployment and release await a green finalizer.

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

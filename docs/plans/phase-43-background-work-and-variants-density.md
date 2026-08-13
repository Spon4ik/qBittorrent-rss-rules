# Phase 43 - Background work lifecycle and variants density

## Status

Implemented and live-validated for the v1.4.15 patch release.

## Problem

The global `Recent background work` panel renders dozens of persistent
Real-Debrid jobs with hash-only labels and ambiguous actions. Users cannot hide
messages without deleting acceleration state, cannot tell which rule/torrent is
affected, and cannot hand an actionable failure to Codex. On rule-edit pages,
expanded provider notices and loose result controls consume height needed by the
critical release-variants table.

## Contract

- Active operations remain visible globally.
- Completed acceleration jobs are hidden by default and represented by one
  compact count; users may show or clear that finished history.
- Errors remain visible until dismissed. Dismissal hides notification state only
  and never changes the torrent, web seed, provider job, or downloaded files.
- Acceleration rows show rule name when linked, torrent name when known, and a
  short reference only as secondary diagnostic identity.
- `Retry` explicitly retries the provider job. `Remove acceleration` explicitly
  removes app-owned web seeds and job state while retaining torrent/files.
- `Ask Codex to fix` queues a redacted scoped maintenance request. A Codex
  heartbeat processes pending requests within five minutes and records results.
- Search notices are collapsed by default with a count; variants retain the
  largest practical share of the rule workspace.

## Persistence and compatibility

- Add nullable `notification_dismissed_at` and non-null `torrent_name` to
  `download_acceleration_jobs` through Alembic and SQLite startup compatibility.
- Existing jobs remain intact and torrent names are enriched during normal
  acceleration discovery. Rule identity is never inferred from qBittorrent
  category text because categories can be shared or unrelated; a rule link is
  rendered only when an explicit persisted `rule_id` is available.
- Maintenance requests live in ignored runtime data under
  `data/codex-maintenance-requests`; tokens and sensitive query values are
  redacted before persistence.

## Acceptance

- The default status payload cannot be crowded out by completed jobs.
- Finished messages can be shown and cleared; error messages can be dismissed.
- Linked errors navigate to their rule and expose understandable action labels.
- Asking Codex writes one deduplicated redacted request and returns queued state.
- Rule pages show collapsed notice count and materially more visible variant rows
  at the reported wide viewport without losing narrow-screen responsiveness.
- Focused/full tests, browser QA, WinUI, Docker health, and live persisted/API/DOM
  checks pass before release.

## Validation evidence

- Focused route, acceleration-service, and static-asset coverage passes.
- Live Docker health is green and the operations API returns torrent names while
  leaving ambiguous rule identity unlinked.
- Playwright at 2048x1150 confirms the Reacher edit page has zero horizontal
  overflow, collapsed `Search notices (5)`, a compact background-work panel,
  and the variants table occupying the remaining workspace height.
- The live DOM exposes `Ask Codex to fix`, `Dismiss`, and
  `Remove acceleration`; `Copy for Codex` is absent.

# Phase 38 - Durable Rule Fetch Reliability

## Summary

Unify first-snapshot recovery and scheduled per-rule refresh so a rule that is
due is discovered deterministically and fetch intent survives process restart.
This phase resolves the overlapping production defects in issues #122 and #123.

## Scope

- Treat a committed eligible rule with no persisted snapshot as durable initial
  fetch intent, so rule creation and its recoverable state share one transaction.
  Persist retry metadata in SQLite.
- Reconcile eligible rules on the scheduler's first startup tick and later ticks through one due
  selector. Missing snapshots are immediately due for enabled, completion-eligible
  rules regardless of the user-controlled periodic refresh setting. Stale
  snapshots are due only when periodic refresh is enabled and their individual
  interval has elapsed.
- Honor the configured enabled/all scope, completion exclusions, fresh-snapshot
  boundary, bounded work per tick, existing fetch lock, and provider concurrency.
- Keep failed or interrupted work durable with bounded exponential retry delay,
  redacted visible status, and no snapshot timestamp update on failure.
- Preserve explicit manual fetch behavior and never trigger torrent downloads.

## Acceptance

- Regression tests cover missing, exact-boundary stale, overdue stale, fresh,
  disabled/completion-blocked, restart, enqueue rejection, busy, transient failure,
  valid empty-result success, and concurrent duplicate intent.
- A pre-existing eligible rule with no snapshot is recovered after startup,
  including when periodic refresh is disabled.
- A newly created Stremio rule's intent is durable before the transaction commits;
  sync completion does not silently lose it if in-memory enqueue is unavailable.
- Targeted tests, `scripts\check.bat`, release/version policy, and protected CI pass.
- Prepare patch release v1.4.34 through the canonical protected release workflow;
  stop before any production approval gate or production mutation.

## Production and data safeguards

- Do not fetch from production or mutate its database during implementation.
- Do not rebuild, restart, or promote Docker during this phase.
- Preserve historical failed Deployment records.
- Keep #47 open for its separate real-title production acceptance.

## Status

- Status: implementation and protected delivery complete; production runtime
  behavior is verified, but the GitHub Deployment audit is failed and must remain
  unchanged while the verifier correction is delivered.
- Implemented: persisted per-rule failure/backoff fields, a shared per-rule due
  selector, startup/scheduler recovery, bounded selection, and redacted recovery
  status in the operations endpoint.
- Validation: focused regressions pass; `scripts\check.bat` passed with 702
  passed, 0 failed, 0 errors, 1 skipped; WinUI desktop build passed with no
  warnings or errors. PR #124 merged as
  `a09807f9b06fa8a55c80de12fe8b53a20e659922`; exact-main CI/API passed as
  `37998309625` / `37998309540`.
- Release: v1.4.34 was staged and published from the exact merge SHA. Protected
  approval `37999106115` passed. The canonical promoter verified the SQLite
  backup and deployed the release. Read-only backup/live DB comparison proves
  three missing eligible snapshots were persisted after startup; remaining
  snapshotless Stremio rules are disabled or completion-blocked.
- Deployment audit: GitHub Deployment `6972627039` is failed because the
  updater's PowerShell native-command pipeline stopped on Compose progress
  output even though Docker Compose exited 0 and the service is healthy. Preserve
  this historical failure. Correct the updater through a regression and a
  protected corrective release; the app/runtime itself reports healthy v1.4.34.
- Follow-up: phase 39 adds plan-scoped production authorization alongside the
  legacy gate and fixes the native Docker output boundary with a Windows
  regression. Focused updater and promotion tests pass. The fix has not yet been
  merged or deployed, so do not retry or change this historical record. See
  [phase 39](phase-39-plan-scoped-production-authorization.md).

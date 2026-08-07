# Phase 37 - qB Recovery and New-Rule Bootstrap

## Summary

Restore qB rule convergence promptly after a temporary qBittorrent outage and bootstrap each newly created rule with both remote sync and a fresh Jackett snapshot.

## Scope

- Poll only while locally recorded qB sync failures look transport-related.
- When qB becomes reachable, move those rules back to pending and enqueue them through the existing bounded sync queue.
- Do not automatically retry configuration or authentication failures.
- After a new rule is committed, enqueue its qB sync and a forced one-rule snapshot fetch, including disabled rules.
- Deduplicate initial snapshot jobs and wait behind an already-running batch instead of dropping the request.

## Acceptance Criteria

- A rule that failed because qB was unavailable is queued within one recovery poll after qB is reachable.
- qB-down checks do not erase the existing failure or enqueue work prematurely.
- Authentication/configuration errors do not create a retry loop.
- Creating a rule queues both qB sync and snapshot fetch without blocking the HTTP response.
- Focused and full gates, desktop build, Docker rebuild, `/health`, and live recovery/bootstrap checks pass.

## Status

- Status: implemented, validated, and published as patch release `v1.4.8`.
- Implemented: transport-failure recovery scheduler, deduplicated initial snapshot queue, create-route wiring, and focused regressions.
- Validation evidence: focused recovery/create/fetch regressions pass; `cmd.exe /c scripts\check.bat` passes with Ruff/mypy clean and all `529` tests green; WinUI builds with zero warnings/errors; the shared Docker backend rebuilt successfully; `/health` serves `status=ok` / `app_version=1.4.8`; and an in-container recovery tick completed cleanly with zero currently failed transport candidates.
- Release: PR `#30` merged to `main`; tag and GitHub Release `v1.4.8` published on 2026-08-07.

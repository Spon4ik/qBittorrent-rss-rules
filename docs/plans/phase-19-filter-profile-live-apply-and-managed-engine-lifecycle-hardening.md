# Phase 19: Filter-Profile Live Apply And Managed Engine Lifecycle Hardening

## Status

- Plan baseline created on 2026-03-27 from the follow-up report that the filter-profile change still felt stale and the desktop-managed backend shutdown path did not reliably stop the engine.
- Phase 19 is complete and release-validated as `v0.7.6`.
- Scope is patch-sized and compatibility-preserving: harden the live frontend refresh path, make frontend asset versioning request-time instead of startup-time, and make managed backend shutdown/restart behavior reliable without reopening the already-shipped Jellyfin/qB feature scope.

## Goal

Deliver a backward-compatible `v0.7.6` patch that makes rule-form filter-profile changes visibly apply immediately, keeps repository-local desktop edits reflected in the embedded browser without manual backend restarts by refreshing the rendered asset version on each request, and makes managed backend shutdown/restart actions actually terminate the running engine cleanly.

## Requested Scope (2026-03-27)

1. Ensure the rule-form filter profile applies immediately when the selection changes, without waiting for another field edit.
2. Ensure repository-local frontend edits are reflected in the desktop shell automatically, even if filesystem watcher events are missed, so the embedded browser stays in sync without an engine restart, and the rendered asset URL version updates on each request so cached frontend code cannot stay stale after a refresh.
3. If the desktop shell decides to shut down or restart a managed backend, the process tree must actually stop and the shell must not silently treat a still-running backend as if it had exited.
4. Update QA so the patch is verified against the live browser flow and the desktop lifecycle behavior before release.

## In Scope

- Rule-form filter-profile selection handling and derived-field refresh behavior.
- Desktop-side freshness detection for repo/dev-checkout runs, including a polling fallback if watcher events are missed.
- Request-time static asset versioning for `app.css` and `app.js` so frontend refreshes actually load the latest code after the embedded browser reloads.
- Managed backend shutdown/restart reliability, including process-tree termination and state cleanup only after confirmation.
- Deterministic browser and desktop validation for the patch slice.
- Patch-version touchpoints and release documentation for `v0.7.6`.

## Out Of Scope

- New Jellyfin/catalog/qB feature work beyond making the current frontend and engine behavior reliable.
- Stremio sync implementation work beyond the already deferred future phase.
- Desktop packaging redesign or large-scale lifecycle architecture changes that are not required to land the patch safely.

## Key Decisions

### Decision: ship this as `v0.7.6`

- Date: 2026-03-27
- Context: The reported issue is a patchable behavior regression / lifecycle hardening problem after `v0.7.5`, not a new feature slice.
- Chosen option: patch release `0.7.6`.
- Reasoning: The work tightens live refresh and managed-backend behavior without changing the public product direction.
- Consequences: Version touchpoints should move from `0.7.5` to `0.7.6` only after the patch is validated.

### Decision: frontend freshness should not rely on a single filesystem watcher path

- Date: 2026-03-27
- Context: Repo-local edits can be missed or delayed by filesystem events on some machines or sync folders, which can leave the embedded browser behind the saved files.
- Chosen option: keep the watcher flow, but add a polling fallback that checks local app freshness and refreshes the WebView when the on-disk app is newer.
- Reasoning: Live refresh should remain responsive even when event delivery is imperfect.
- Consequences: The desktop shell needs a timer-based freshness check in addition to the current watcher/debounce path.

### Decision: rendered asset versions should be computed per request

- Date: 2026-03-27
- Context: The embedded browser can reload the same page URL after local edits, but stale startup-time asset query strings can still leave cached JavaScript/CSS in place.
- Chosen option: compute the static asset version from the current on-disk `app.css` and `app.js` mtimes during each HTML render and health probe.
- Reasoning: A browser refresh should always have a fresh cache-busting token when local frontend files have changed.
- Consequences: The page templates and health endpoint need request-time asset version plumbing instead of a startup-only cached string.

### Decision: managed-backend shutdown must preserve ownership state until termination is confirmed

- Date: 2026-03-27
- Context: A shutdown attempt that kills the handle but leaves descendants alive can make the shell believe the backend has exited while the stale server is still serving old code.
- Chosen option: only delete managed-backend ownership state after the process tree is confirmed stopped, and fall back to a stronger kill path if the first attempt does not terminate the tree.
- Reasoning: The shell needs to remain honest about whether it still owns a live backend.
- Consequences: Shutdown/restart helpers must report success only when the process is actually gone.

## Acceptance Criteria

- Changing the rule-form filter profile immediately updates the visible quality-token state, the derived quality profile value, and the generated pattern preview without waiting for another unrelated field edit.
- Editing frontend files in a repo/dev checkout causes the desktop shell to refresh automatically without requiring a manual backend restart, and the refreshed HTML includes a new asset version token so cached frontend code is replaced.
- Clicking `Shut Down Engine` actually stops the desktop-managed backend process tree, and the shell does not delete ownership state unless the backend really exited.
- Starting the backend again after a shutdown brings up a fresh managed backend cleanly.
- Browser QA, desktop validation, and repo checks pass on the final worktree before the release is cut.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P19-01 | Harden the rule-form filter-profile live-apply path. | Codex | 2026-03-27 | completed | Selecting a profile updates the quality-token controls and derived preview immediately in the live browser path. | Validated with the live browser closeout flow and `tests/test_routes.py`. |
| P19-02 | Add desktop freshness polling and request-time asset versioning so the embedded browser stays in sync. | Codex | 2026-03-27 | completed | Repo-local frontend file edits are picked up even when watcher events are missed, and the rendered asset version changes after a local file timestamp update. | Validated with `tests/test_static_assets.py` and the browser closeout asset-version check. |
| P19-03 | Make managed backend shutdown/restart reliable. | Codex | 2026-03-27 | completed | A shutdown attempt actually terminates the process tree and keeps state consistent until termination is confirmed. | Validated in `QbRssRulesDesktop/Views/MainPage.xaml.cs` and the release smoke checks. |
| P19-04 | Expand QA and revalidate the patch release. | Codex | 2026-03-27 | completed | Browser and desktop lifecycle checks pass on the final worktree. | `cmd.exe /c scripts\\check.bat` (`231 passed`, `1 skipped`), `cmd.exe /c scripts\\closeout_qa.bat` (all browser closeout checks passed), and `cmd.exe /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`). |

## Risks And Follow-Up

### Risk: polling can be noisy if it runs too often

- Trigger: the desktop shell may see repeated saves while a developer edits multiple files.
- Impact: the browser could reload more often than desired.
- Mitigation: debounce refreshes and keep the poll interval modest.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

### Risk: stronger shutdown logic can still leave stale descendants if the first kill path is insufficient

- Trigger: Windows process trees or Python reloaders can be stubborn about exiting.
- Impact: the shell could think a backend is gone when a child process still holds the port.
- Mitigation: preserve ownership state until exit is confirmed, and add a stronger fallback kill path before deleting the marker.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

## Next Concrete Steps

1. Open the Stremio source-adapter phase as the next planned integration slice.
2. If a future regression appears in the filter-profile or managed-backend paths, capture it as a fresh patch phase instead of extending this completed slice.
3. Keep the roadmap and current-status docs aligned with the next active phase once that work starts.

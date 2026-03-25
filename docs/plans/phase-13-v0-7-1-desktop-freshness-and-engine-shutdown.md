# Phase 13: v0.7.1 Desktop Freshness and Engine Shutdown

## Status

- Plan baseline created on 2026-03-25 from a post-`v0.7.0` desktop release-blocker report.
- Phase 13 is now implemented and release-validated as the shipped `v0.7.1` patch release.
- Final closeout passed on 2026-03-25 via `cmd.exe /c scripts\check.bat` (`227 passed`, `57 warnings`), `cmd.exe /c scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T123912Z/`), `cmd.exe /c scripts\run_dev.bat desktop-build`, and live WinUI launch verification against a managed backend at `http://127.0.0.1:8001/`.
- Scope is patch-sized and compatibility-preserving: fix desktop host behavior without reopening the Jellyfin/qB feature scope that already shipped in `v0.7.0`.

## Goal

Deliver a backward-compatible `v0.7.1` patch that keeps the WinUI desktop shell aligned with current local app script/template changes, fails closed instead of silently serving stale or unreachable backend state during refresh, and gives the operator an explicit in-app way to shut down the managed backend or exit the desktop app.

## Requested Scope (2026-03-25)

1. Ensure the desktop app picks up up-to-date local app changes immediately instead of continuing to show stale browser scripts while the browser is already correct.
2. If the desktop shell cannot connect to the refreshed/current backend, fail closed into the offline state instead of continuing to show stale content.
3. Add an explicit in-app `Exit` and/or managed-backend shutdown control so stopping the desktop-managed Python process does not require Task Manager.

## In Scope

- WinUI shell detection of relevant local app changes for repo/dev-checkout runs.
- Forced WebView reload/navigation refresh when local app files change and the backend is still healthy.
- Fail-closed offline/reconnect behavior when a refresh is required but the backend is temporarily or permanently unavailable.
- Explicit in-app command surface for shutting down the managed backend and exiting the desktop app.
- Desktop build and objective launch verification after the change.
- Patch-version touchpoint and docs closeout for `v0.7.1`.

## Out Of Scope

- New Jellyfin/catalog/qB feature work beyond ensuring desktop parity with already-shipped browser behavior.
- Replacing the WinUI WebView shell with native desktop feature surfaces.
- Installer/distribution redesign.
- Large-scale desktop architecture rewrites that are not required to land the patch safely.

## Key Decisions

### Decision: ship this as `v0.7.1`

- Date: 2026-03-25
- Context: The reported problem is a release-blocking desktop-host bug after the `v0.7.0` feature release, not a new feature slice.
- Chosen option: patch release `0.7.1`.
- Reasoning: The fix changes desktop host behavior and controls, but it is a compatibility-preserving corrective release.
- Consequences: Version touchpoints should move from `0.7.0` to `0.7.1` only after the desktop fix and validation are complete.

### Decision: desktop freshness should be driven by local file change detection, not only backend contract checks

- Date: 2026-03-25
- Context: The current shell already rejects incompatible backend contracts, but local web-script changes can still leave the desktop UI stale while the browser picks up newer assets.
- Chosen option: add desktop-side local change detection for repo/dev-checkout runs and trigger a refresh/reconnect flow from the shell itself.
- Reasoning: Static assets and templates can change without requiring a Python process restart, so relying only on `/health` contract checks is insufficient.
- Consequences: The phase needs desktop-side file watching and a debounced refresh path that reloads or fails closed based on real backend reachability.

### Decision: refresh failures must hide stale content

- Date: 2026-03-25
- Context: Continuing to show an old WebView session after the current backend cannot be reached makes desktop behavior diverge from the browser and obscures failures.
- Chosen option: when a freshness-triggered reconnect cannot reach a compatible backend, switch to the existing offline panel and reconnect workflow.
- Reasoning: Fail-closed behavior is safer and makes stale backend/script problems visible immediately.
- Consequences: The desktop shell must stop treating the currently rendered page as authoritative once a freshness-triggered reconnect is required.

### Decision: add explicit managed-backend shutdown and desktop exit controls

- Date: 2026-03-25
- Context: The operator currently has to kill Python manually when they want to stop the desktop-managed backend.
- Chosen option: add explicit in-app controls for shutting down the managed backend and exiting the desktop app.
- Reasoning: Lifecycle control belongs in the app, not in Task Manager.
- Consequences: The phase needs WinUI command-surface changes plus managed-backend cleanup wiring that works whether shutdown is user-triggered or window-triggered.

## Acceptance Criteria

- Running the desktop app against a repo/dev checkout picks up changed app scripts/templates without needing Task Manager or a full manual reset.
- When a freshness-triggered reconnect cannot reach a compatible backend, the desktop app shows the offline state instead of continuing to display stale content.
- The desktop UI exposes an explicit way to stop the managed backend and an explicit way to exit the desktop app.
- Desktop build succeeds and the patched app launch is verified with an objective window/process check.
- Patch release docs and version touchpoints are synchronized only after validation passes.

## Dated Execution Checklist (2026-03-25 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P13-01 | Define and implement desktop freshness detection plus refresh flow. | Codex | 2026-03-25 | completed | The WinUI shell detects relevant local app changes in dev/repo mode and refreshes the WebView or reconnects accordingly. | Implemented in `QbRssRulesDesktop/Views/MainPage.xaml.cs` via local app change watching plus debounced refresh handling; validated by successful build and live managed-backend launch verification. |
| P13-02 | Enforce fail-closed behavior during freshness-triggered reconnects. | Codex | 2026-03-25 | completed | Required refreshes do not leave stale content visible when the backend is unavailable or incompatible. | Implemented in `QbRssRulesDesktop/Views/MainPage.xaml.cs`; live verification showed the `0.7.1` shell rejecting stale `0.7.0` on `:8000` and switching to a managed `0.7.1` backend at `http://127.0.0.1:8001/` instead of silently reusing stale state. |
| P13-03 | Add explicit managed-backend shutdown and desktop exit controls. | Codex | 2026-03-25 | completed | Users can stop the managed backend and exit the desktop app without Task Manager. | Added `Shut Down Engine` and `Exit Desktop` controls in `QbRssRulesDesktop/Views/MainPage.xaml` with lifecycle wiring in `QbRssRulesDesktop/Views/MainPage.xaml.cs`; build and live launch verification passed. |
| P13-04 | Revalidate desktop patch behavior. | Codex | 2026-03-25 | completed | Desktop build, objective launch verification, and relevant Python/static checks pass on the final worktree. | `cmd.exe /c scripts\run_dev.bat desktop-build` passed, live launch verification confirmed `QbRssRulesDesktop` window handle `1182596` with managed backend state at `http://127.0.0.1:8001/`, `cmd.exe /c scripts\check.bat` passed (`227 passed`, `57 warnings`), and `cmd.exe /c scripts\closeout_qa.bat` passed (artifacts under `logs/qa/phase-closeout-20260325T123912Z/`). |
| P13-05 | Close out docs and patch release touchpoints for `v0.7.1`. | Codex | 2026-03-25 | completed | Version touchpoints, roadmap/current-status, changelog, and phase docs match the shipped patch. | Updated `pyproject.toml`, `app/main.py`, `QbRssRulesDesktop/Views/MainPage.xaml.cs`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, `docs/plans/README.md`, and this phase plan for the shipped `0.7.1` patch release. |

## Risks And Follow-Up

### Risk: overly broad file watching could cause noisy or repeated refreshes during dev

- Trigger: repository-local development can touch multiple files quickly during builds or saves.
- Impact: the desktop shell could reload too often or interrupt active use.
- Mitigation: debounce refresh triggers and scope watchers to the relevant app directories/extensions.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

### Risk: managed-backend shutdown controls must not imply the app can stop arbitrary external backends

- Trigger: the desktop shell may be attached to a manually started backend instead of one it launched itself.
- Impact: the UI could mislead users about what will actually be shut down.
- Mitigation: keep the control semantics explicit around the desktop-managed backend and fail clearly when no managed backend is owned by the current session.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

## Next Concrete Steps

1. Decide whether the next phase returns to post-`v0.7.0` catalog/watch-history work or keeps investing in desktop lifecycle polish.
2. If desktop polish continues, add tighter objective validation around the new shutdown and fail-closed refresh behaviors.
3. Keep version/contract alignment explicit on future desktop patch releases so stale backends stay rejectable.

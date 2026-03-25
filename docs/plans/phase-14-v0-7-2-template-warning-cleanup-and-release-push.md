# Phase 14: v0.7.2 Template Warning Cleanup and Release Push

## Status

- Plan baseline created on 2026-03-25 from the post-`v0.7.1` request to eliminate the repeated test warnings and publish the release upstream.
- Phase 14 is now implemented and release-validated as the shipped `v0.7.2` patch release.
- Scope stayed intentionally patch-sized: remove the repeated template deprecation warnings, keep the release path green, and push the resulting release commit/tag to the configured remote.

## Goal

Deliver a backward-compatible `v0.7.2` patch that removes the repeated Starlette template deprecation warnings from the route test path, reruns the release checks on the cleaned-up worktree, and publishes the release commit/tag to the remote repository.

## Requested Scope (2026-03-25)

1. Eliminate the repeated `TemplateResponse` deprecation warnings currently reported during pytest/check runs.
2. Revalidate the release path after the cleanup.
3. Push the resulting release commit/tag to the remote repository.

## In Scope

- Update `TemplateResponse` call sites to the current Starlette request-first signature.
- Focused route/test verification plus normal release-gate revalidation.
- Patch-version bump and release-doc synchronization for `v0.7.2`.
- Push of the release commit/tag to the configured Git remote if authentication and remote state allow it.

## Out Of Scope

- New product features.
- Desktop shell behavior changes beyond what already shipped in `v0.7.1`.
- Larger route/rendering refactors unrelated to the deprecation cleanup.

## Key Decisions

### Decision: ship this as `v0.7.2`

- Date: 2026-03-25
- Context: The requested work removes repeated warnings and publishes the cleaned-up release state without changing behavior.
- Chosen option: patch release `0.7.2`.
- Reasoning: This is a compatibility-preserving maintenance cleanup after `v0.7.1`.
- Consequences: Version touchpoints should move from `0.7.1` to `0.7.2` only after the cleanup and release validation pass.

### Decision: fix the warnings at the template call sites, not by filtering them in tests

- Date: 2026-03-25
- Context: The warning is a real API deprecation in Starlette and is currently repeated many times during route tests.
- Chosen option: update the template rendering calls to the request-first signature.
- Reasoning: Removing the deprecated usage is cleaner than silencing a warning that will likely become a future break.
- Consequences: The phase should touch only the route/template rendering paths that still use the old signature.

### Decision: publish only after a clean release path rerun

- Date: 2026-03-25
- Context: The user asked to push the release after the warning cleanup.
- Chosen option: rerun the release validation, then push commit/tag only if the remote push succeeds.
- Reasoning: Publication should happen from the validated worktree, not from an unverified intermediate state.
- Consequences: The phase must record both local validation evidence and remote push status.

## Acceptance Criteria

- The repeated Starlette template deprecation warning is eliminated from the release test path.
- The relevant route rendering behavior remains unchanged and tests stay green.
- The final patch worktree passes the chosen release gates.
- The release commit/tag is pushed to the configured remote, or a concrete push blocker is documented.

## Dated Execution Checklist (2026-03-25 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P14-01 | Update deprecated `TemplateResponse` call sites. | Codex | 2026-03-25 | completed | Deprecated request-second signature is removed from the affected route files. | Updated the remaining route/template renderers in `app/routes/pages.py` and `app/routes/api.py` to `TemplateResponse(request, ...)`. |
| P14-02 | Revalidate the warning-cleanup patch. | Codex | 2026-03-25 | completed | Focused tests and release gates pass on the final worktree. | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -q`, `cmd.exe /c scripts\\check.bat` (`227 passed`), `cmd.exe /c scripts\\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T133040Z/`), and `cmd.exe /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`). |
| P14-03 | Close out docs/version touchpoints for `v0.7.2`. | Codex | 2026-03-25 | completed | Version touchpoints and release docs match the shipped patch. | Updated `pyproject.toml`, `app/main.py`, `QbRssRulesDesktop/Views/MainPage.xaml.cs`, `tests/test_routes.py`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, `docs/plans/README.md`, and this phase plan for `0.7.2`. |
| P14-04 | Push the patch release to the remote repository. | Codex | 2026-03-25 | completed | Release commit/tag are published to `origin`, or a concrete remote/auth blocker is captured. | Release publication completed via `git push origin main` and `git push origin v0.7.2`. |

## Risks And Follow-Up

### Risk: remote push may still be blocked by auth or remote divergence

- Trigger: pushing depends on remote permissions and current remote state.
- Impact: local release can be ready while publication remains blocked.
- Mitigation: inspect remote state first, push only after validation, and record any concrete blocker instead of guessing.
- Owner: Codex
- Review date: 2026-03-25
- Status: closed

## Next Concrete Steps

1. No further implementation work remains inside phase 14.
2. Open the next active phase plan before the next code change.
3. Resume post-`v0.7.2` planning around richer catalog providers, watch-history scope, and large-file/module splits.

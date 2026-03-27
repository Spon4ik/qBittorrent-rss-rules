# Phase 16: Desktop Build Portability and NuGet Source Cleanup

## Status

- Plan baseline created on 2026-03-27 after WinUI build validation exposed a machine-specific NuGet restore source path that does not exist on this workstation.
- Phase 16 is now implemented and release-validated as the `v0.7.3` maintenance release.
- Scope stayed intentionally narrow: remove the stale offline NuGet source from repo config, revalidate the desktop build on this machine, and close out a patch release once the build stayed green.

## Goal

Make the WinUI restore/build path portable across cloned machines without assuming `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\` exists locally.

## Requested Scope (2026-03-27)

1. Remove the machine-specific offline NuGet source from repo restore config.
2. Re-run the WinUI build and repo checks on this workstation.
3. If validation stays green, synchronize the next patch release touchpoints and publish the release.

## In Scope

- Cleanup of repo restore configuration that references host-specific package folders.
- Desktop build verification after the restore-path cleanup.
- Patch-version synchronization and release documentation updates if the build is green.

## Out Of Scope

- New product features.
- General machine setup or per-host SDK installation guidance.
- Broader dependency-policy redesign unless it is required to restore the build on a clean clone.

## Key Decisions

### Decision: ship this as `v0.7.3`

- Date: 2026-03-27
- Context: The requested work removes a machine-specific restore blocker and hardens the repo-local backend startup path without changing public product behavior.
- Chosen option: patch release `0.7.3`.
- Reasoning: This is a compatibility-preserving maintenance fix that makes the repo more portable across cloned machines.
- Consequences: Version touchpoints should move from `0.7.2` to `0.7.3` after the cleanup and validation pass.

### Decision: remove the offline Visual Studio package source instead of keeping a broken path in repo config

- Date: 2026-03-27
- Context: `scripts\run_dev.bat desktop-build` failed on this workstation because `NuGet.config` referenced `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\`, which is not present here.
- Chosen option: keep `nuget.org` as the sole configured source in repo restore config.
- Reasoning: project restore should work on any clone without requiring a machine-specific offline package directory.
- Consequences: offline Visual Studio package restores are no longer assumed by the repo, but the build becomes portable and self-contained through the public feed.

## Acceptance Criteria

- `scripts\run_dev.bat desktop-build` succeeds on this workstation after restore.
- The repo no longer references the missing offline NuGet packages path in its restore configuration.
- Patch version touchpoints, release notes, and the remote Git release publication are synchronized for `v0.7.3`.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P16-01 | Remove the machine-specific offline NuGet source from repo restore config. | Codex | 2026-03-27 | completed | Restore config no longer references the missing `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\` path. | Removed the `Microsoft Visual Studio Offline Packages` source from `NuGet.config`, leaving `nuget.org` as the sole restore source. |
| P16-02 | Re-run the WinUI desktop build and repo checks. | Codex | 2026-03-27 | completed | `scripts\run_dev.bat desktop-build` and repo checks pass after the restore-path cleanup. | `.\\.venv\\Scripts\\python.exe -m pytest` via `cmd.exe /c scripts\\check.bat` passed (`226 passed`, `1 skipped`), `cmd.exe /c scripts\\run_dev.bat desktop-build` passed (`0 Warning(s)`, `0 Error(s)`), and `cmd.exe /c scripts\\closeout_qa.bat` passed with artifacts under `logs/qa/phase-closeout-20260327T093517Z/`. |
| P16-03 | Close out the next patch release if validation stays green. | Codex | 2026-03-27 | completed | Version/docs touchpoints are synchronized and the release is ready to publish. | Synchronized `pyproject.toml`, `app/main.py`, `QbRssRulesDesktop/Views/MainPage.xaml.cs`, `tests/test_routes.py`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, `docs/plans/README.md`, and this phase plan for `0.7.3`. |
| P16-04 | Publish the patch release to the remote repository. | Codex | 2026-03-27 | completed | Release commit/tag are published to `origin`, or a concrete remote/auth blocker is captured. | Release publication completed via `git push origin main` and `git push origin v0.7.3`. |

## Risks And Follow-Up

### Risk: removing the offline source could affect users who rely on Visual Studio offline packages

- Trigger: a clone that expected the local offline package folder as a restore source.
- Impact: restore will rely on `nuget.org` instead of the offline folder.
- Mitigation: keep `nuget.org` configured as the canonical source and document the repo's portable restore behavior in the release notes.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

## Next Concrete Steps

1. No further implementation work remains inside phase 16.
2. Open the next active feature phase before the next feature code change.
3. Resume post-`v0.7.3` planning around richer catalog providers, broader watch-history persistence, and targeted large-file/module split work.

# Phase 15: Repo-Local Backend Startup Portability

## Status

- Plan baseline created on 2026-03-27 from the request to realign project docs to product-only scope and recover a backend that no longer started from the OneDrive workspace.
- Phase 15 is now implemented and manually validated as a maintenance-only slice.
- Scope stayed intentionally narrow: remove unrelated host-operation artifacts from project docs/workspace, harden `scripts\run_dev.bat` against broken copied `.venv` launchers, and verify the backend answers `/health` from this repo.

## Goal

Keep project documentation focused on project behavior and make the Windows repo-local backend startup flow recoverable when a copied `.venv` still points at a stale absolute interpreter path.

## Requested Scope (2026-03-27)

1. Remove unrelated host-setup material from project documentation and repo artifacts.
2. Make backend startup failures actionable when the repo-local `.venv` launcher is invalid.
3. Recreate the local environment as needed and verify the backend runs from this workspace again.

## In Scope

- Cleanup of host-operation documentation and helper artifacts that do not belong in the project repo.
- Startup-path hardening in `scripts\run_dev.bat` for invalid checked-in `.venv` launchers.
- Manual `.venv` recreation and local `/health` verification for the OneDrive workspace copy.

## Out Of Scope

- New product features or release-scope behavior changes.
- General machine setup, BIOS, or host virtualization work.
- Cross-machine automation beyond making the repo-local backend failure mode recoverable.

## Key Decisions

### Decision: fail fast with repair instructions when the repo-local `.venv` is unusable

- Date: 2026-03-27
- Context: The copied workspace `.venv\pyvenv.cfg` still referenced a stale absolute interpreter path, which surfaced as a confusing `No Python at ...` launcher error when `scripts\run_dev.bat api` was used.
- Chosen option: probe `.venv\Scripts\python.exe` before startup and stop with explicit recreate commands if that launcher cannot execute.
- Reasoning: The underlying issue is local-environment breakage, not an app import or runtime error, so the script should point directly at the repair path.
- Consequences: Future copied-workspace failures should be self-diagnosing instead of looking like an app/backend regression.

### Decision: keep host-specific machine-operation work out of project docs

- Date: 2026-03-27
- Context: Host-operation notes and helper scripts had been created in this repo workspace even though they described machine-level operations rather than project behavior.
- Chosen option: remove those repo-local artifacts and keep project planning documents focused on codebase-maintenance facts only.
- Reasoning: Project docs should stay resumable for product work without mixing in unrelated host-operations history.
- Consequences: Machine-restore notes should live outside this repository.

## Acceptance Criteria

- Project docs no longer carry unrelated host-setup notes.
- `scripts\run_dev.bat api` prints concrete repair steps when `.venv` is invalid instead of surfacing only the stale absolute Python path error.
- The OneDrive workspace backend answers `/health` successfully after the local environment repair.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P15-01 | Realign project docs to product-only scope and remove stray host-operation artifacts. | Codex | 2026-03-27 | completed | Project docs/workspace no longer contain unrelated host-setup material. | Removed the unrelated host-operations section from `README.md`, deleted the stray non-project helper scripts under `scripts/`, and aligned `ROADMAP.md`, `docs/plans/README.md`, and `docs/plans/current-status.md` with this maintenance slice. |
| P15-02 | Harden Windows backend startup against broken copied `.venv` launchers. | Codex | 2026-03-27 | completed | `scripts\run_dev.bat api` detects an unusable repo-local `.venv` and prints actionable recreate commands. | Updated `scripts/run_dev.bat` to probe `.venv\Scripts\python.exe` before startup and fail fast with `rmdir /s /q .venv`, `python -m venv .venv`, and `.venv\Scripts\python -m pip install -e ".[dev]"` guidance. |
| P15-03 | Recreate the local `.venv` and re-verify backend health from this workspace. | Codex | 2026-03-27 | completed | The OneDrive workspace backend answers `/health` after the environment repair. | Rebuilt `.venv` with `C:\Users\nucc\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv`, reinstalled `-e .[dev]`, and verified `http://127.0.0.1:8000/health` returned `200` with `app_version=0.7.2`. |

## Risks And Follow-Up

### Risk: copied virtual environments remain machine-specific by design

- Trigger: any future copy of a repo-local Windows virtual environment can still carry stale interpreter paths in `pyvenv.cfg`.
- Impact: local startup can fail until `.venv` is recreated.
- Mitigation: keep the fast-fail instructions in `scripts\run_dev.bat` and prefer recreating `.venv` after copying the repo between machines.
- Owner: Codex
- Review date: 2026-03-27
- Status: mitigated

## Next Concrete Steps

1. No further implementation work remains inside phase 15.
2. Open the next active feature phase before the next non-maintenance code change.
3. Resume post-`v0.7.2` planning around richer catalog providers, broader watch-history persistence, and targeted large-file/module split work.

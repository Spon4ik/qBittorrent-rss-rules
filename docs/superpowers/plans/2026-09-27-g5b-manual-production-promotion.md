# G5b Manual Production Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a GitHub-hosted approval record and a locally executed Windows promotion gate that deploys only an approved, published release tag through the existing backend finalizer.

**Architecture:** GitHub Actions validates a manually selected release tag against protected `main` and exact-SHA CI and real-qBittorrent runs, then pauses at a protected Environment and publishes a data-only approval artifact. A local Python command verifies that artifact and live GitHub state, acquires a host lock, checks a stable detached checkout and Compose contract, performs a private SQLite backup plus scratch restore, invokes the existing finalizer, and records the observed production deployment. Production mutation remains on the Windows host.

**Tech Stack:** GitHub Actions YAML, pinned GitHub Actions, Python 3.12 standard library, pytest, `gh`, Docker Compose, SQLite online backup API, existing `Finalize-Backend.cmd` and runtime status command.

**Spec:** `docs/superpowers/specs/2026-09-26-g5b-manual-production-promotion-design.md`

## Global Constraints

- Never expose production credentials, Docker access, database paths, backup contents, or host access to a GitHub-hosted runner.
- Do not deploy from the developer checkout or a transient CI checkout.
- Use the stable checkout `C:\Users\nucc\deployments\qBittorrent-rss-rules`; its directory is currently absent and must be created only by an explicit local promotion invocation.
- Keep the existing production database bind mount and both host mounts unchanged; only the `qb-rss-rules` build context may point to the stable checkout.
- Require a published release tag whose peeled commit is on protected `main`, with successful exact-SHA required CI and real-qBittorrent API runs.
- Record approval separately from production deployment success; only exact-version runtime health can mark a production deployment successful.
- Require the target version to be greater than the currently served production version for the first implementation; reject downgrades.
- Because the deployment checkout is detached at the approved tag, verify its `HEAD` against the published tag SHA and use `runtime_state --require-runtime-current`; do not require a branch upstream in that checkout.
- Never automatically restore production data. Image rollback and database restore are separate operator procedures.
- No production promotion, Compose edit, Environment creation, backup, or Docker rebuild is part of implementation validation.

## Review Focus

- Annotated tags: peel and compare the commit SHA, not the tag-object SHA.
- Duplicated workflow runs: require successful exact-SHA runs and fail closed when no qualifying run exists.
- Stale or mismatched approval artifacts: bind repository, tag, SHA, approval run, Environment, and expiry, then requery GitHub before mutation.
- Detached release checkout: verify source identity explicitly without fabricating an upstream branch.
- Compose drift: compare resolved service, database mount, and host mounts before any rebuild.
- Promotion collision or interruption: hold an exclusive OS file lock for the full operation and release it on process exit.
- Finalizer timeout: terminate the full Windows process tree and reap its parent before marking failure; if termination cannot be confirmed, leave deployment in progress with a cleanup-required local record and no terminal GitHub status.
- SQLite backup integrity: restore the backup to isolated scratch storage before rebuilding.
- Failed health or audit API update: retain prior image identity, distinguish failure from audit-only retry, and never imply success without observed health.

## Task 1: Exact-SHA Approval Workflow

**Files:**
- Create: `.github/workflows/production-approval.yml`
- Create: `tests/test_production_approval_workflow.py`

**Interface:** `workflow_dispatch` input `release_tag`; success uploads `production-approval-manifest` JSON binding repository, tag, peeled full SHA, release URL, CI/API run IDs and URLs, approval workflow run ID/URL, and approval timestamp. Artifact is data only; reviewed local code remains authoritative.

- [x] Write contract tests rejecting non-main dispatch, missing/unpublished release, tag outside main, non-success/missing exact-SHA required runs, unpinned actions, excess permissions, secrets, and cancelling concurrency.
- [x] Run focused tests and confirm they fail because the workflow is absent.
- [x] Implement `workflow_dispatch` with least-privilege permissions, pinned actions, `production-approval` Environment, and `cancel-in-progress: false`.
- [x] Verify successful `CI / required` and `real-qbittorrent-webseed-api` runs for the peeled tag SHA; emit the manifest only after Environment approval.
- [x] Run focused tests, YAML parsing, and workflow policy assertions.
- [x] Commit and push the coherent workflow checkpoint; verify CI and real-qBittorrent checks against its exact pushed SHA.

## Task 2: Local Promotion Contracts and Preflight

**Files:**
- Create: `scripts/production_promotion.py`
- Create: `scripts/promote_production.py`
- Create: `tests/test_production_promotion.py`

**Interfaces:** `PromotionRequest(tag: str, approval_run_id: int)` and `PromotionConfig` for repository root, stable checkout, shared Compose path, env path, private backup root, lock path, and expected mounts. CLI: `python scripts/promote_production.py --tag TAG --approval-run-id RUN_ID`.

- [x] Cover invalid/stale/mismatched approval, unpublished/non-main tags, dirty/wrong-SHA checkout, non-increasing version, missing exact-SHA checks, Compose service/context/mount drift, unavailable Docker, lock contention, and zero-mutation preflight rejection.
- [x] Run focused tests and observe RED.
- [x] Implement GitHub queries through `gh`; download only the named approval JSON artifact to a temporary directory and validate schema and run identity.
- [x] Verify stable detached checkout equals the published peeled tag and is clean; allow initialization/update only under the stable directory after read-only approval checks pass.
- [x] Resolve `docker compose config --format json` using the shared Compose and `.env`; assert service, stable context, database source and `/app/data`, both host mounts, and service name.
- [x] Compare target and live `/health.app_version` with strict SemVer; reject a target not greater than the live version.
- [x] Run the focused invalid-preflight matrix and static checks; approval/promotion tests pass (30), Ruff and targeted mypy pass. Full repository check and exact-SHA Actions evidence are tracked separately below.

## Task 3: Lock, Backup, Finalizer and Deployment Record

**Files:**
- Modify: `scripts/production_promotion.py`
- Modify: `tests/test_production_promotion.py`
- Create: `docs/production-promotion-runbook.md`

**Interfaces:** Transaction stages: `preflight`, `deployment-created`, `backup-verified`, `finalizer-running`, `health-verified`, `deployment-recorded`. Private local record is redacted JSON; GitHub Deployment payload contains release identity, approval run, and evidence digests/references, never private file paths.

- [x] Test cross-process exclusive lock and automatic release after process exit.
- [x] Test SQLite online backup, `PRAGMA integrity_check`, scratch restore, and early stop on integrity/restore failure.
- [x] Implement private backup creation and SHA-256 evidence; backup failure must stop before finalizer invocation.
- [x] Test retaining the currently running image by immutable image ID before rebuild.
- [x] Implement GitHub `production` Deployment status transitions; success requires finalizer exit zero and `/health.app_version` exactly equal to target release version.
- [x] Test backup, finalizer, and health failures record failure without automatic database or image rollback; test initial and failure-journal write failures still attempt GitHub failure status; test post-health GitHub update failure and verify audit retry performs no backup, finalizer, or Docker mutation.
- [x] Contain timed-out finalizer descendants with `taskkill /T /F`; confirm process-tree termination and reap the parent before recording a terminal failure, and fail closed with a cleanup-required record if termination is uncertain.
- [x] Document one-time Compose context edit, stable checkout setup, approval, invocation, expected output, backup retention, image rollback, database recovery boundary, and evidence capture.
- [x] Run focused tests and documentation command checks (32 focused tests pass).

## Task 4: CI and Readiness Closeout

**Files:**
- Modify: `.github/workflows/production-approval.yml` if checks require it.
- Modify: `docs/plans/current-status.md`
- Modify: `docs/plans/2026-09-25-native-github-delivery-governance.md`
- Modify: `CHANGELOG.md`

- [x] Run focused tests, `scripts/check.bat`, and all repository-required PR checks after timeout-tree recovery; the focused approval/promotion suite passes (37 tests), and `scripts/check.bat` passes Ruff, mypy (49 files), and pytest (642 passed, 0 failed, 0 errors, 1 skipped) at code head `185b420dfa18fb4340ca02b4fe7c5b2150b1402b`. All required checks pass on that exact head (CI `36285442249`, qB API `36285442243`). Do not run the production finalizer or alter the running Docker service during implementation validation.
- [ ] Verify detached source against the published peeled tag SHA, then use `runtime_state.bat --require-runtime-current` after an explicitly authorized promotion; do not require an upstream branch for detached `HEAD`.
- [x] Record that first promotion requires a newly published version greater than currently deployed `1.4.24`; v1.4.24 is ineligible in the runbook and current status.
- [x] Record exact tested head, CI/API results, Environment configuration state, stable checkout path, and that production promotion remains unattempted pending explicit operator action. The `production-approval` Environment currently returns 404; `%USERPROFILE%\deployments\qBittorrent-rss-rules` is absent; runtime is current at v1.4.24.
- [x] Commit and push each validated checkpoint; update PR #67 with exact head, validation, blockers, and next action.

## Production Acceptance (separate operator action)

- [ ] Publish a new Windows app + source release from validated protected `main`, with version greater than deployed v1.4.24.
- [ ] Dispatch approval for that tag and record the approving Environment run.
- [ ] After explicit operator authorization, run local promotion on production Windows; verify backup integrity and scratch restore before finalizer.
- [ ] Verify tag SHA, container image identity, `/health.app_version`, and `runtime_state.bat --require-runtime-current` from the stable detached checkout.
- [ ] Confirm GitHub `production` Deployment success and matching private local evidence.

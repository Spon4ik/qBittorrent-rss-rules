# G5b Manual Production Promotion Design

**Status:** Draft for maintainer review
**Date:** 2026-09-26
**Audience:** Repository maintainer and release operator

## Context

G5a publishes a Windows x64 desktop package and GitHub source archives from a validated protected-main commit. Production is a Windows Docker Desktop service. The shared Compose file at `C:\Users\nucc\docker-config\docker-compose.yml` currently builds from `E:\GitHub\qBittorrent rss rules` and binds that checkout's `data` directory to `/app/data`. The repository has no production Environment or deployment workflow. The main checkout may contain unrelated local work, so running the finalizer there cannot prove production is built from published release source.

The existing deployment contract remains authoritative: `Finalize-Backend.cmd --no-pause` runs the full backend gate, invokes the Docker updater only after it passes, and requires deployed `/health.app_version` to equal the checkout version. The updater requires the shared Compose build context to match the checkout it runs from. Production database and host-path mounts must remain intact. No GitHub runner may receive production secrets, Docker access, database paths, or host access.

## Goals and non-goals

### Goals

- Keep CI and a small approval record on GitHub-hosted runners; avoid paid runner minutes and production-host runner access.
- Require operator approval bound to one published tag and exact commit before local production promotion.
- Promote from a clean, stable Windows deployment checkout through the existing finalizer.
- Preserve the existing production database directory and host mounts when the Compose build context changes.
- Record source identity, release tag, image identity, backup/restore evidence, health result, operator, approval run, and rollback instructions.
- Stop on preflight failures and distinguish image rollback from database restore.

### Non-goals

- Automatic production deployment from GitHub Actions.
- Any runner with Docker socket, database, provider credentials, or production network access.
- Publishing/deploying a GHCR image; G5a output is Windows app plus source.
- Automatic production database restore or product behavior/version changes.

## Options considered

1. **Recommended: GitHub-hosted approval plus manual local promotion.** A protected manual workflow validates a selected published tag and exact-SHA CI evidence, waits at a protected `production` Environment for maintainer approval, then records a machine-readable approval. The operator runs a local promotion command from a dedicated clean Windows checkout; it verifies that approval before invoking the existing finalizer. The workflow has no production access and performs no deployment.
2. **Checklist-only manual promotion.** Fewer components, but no machine-verifiable approval gate or serialized GitHub record.
3. **Self-hosted production deployment runner.** Automates host changes but gives public-repository workflows a route to production and requires a persistent trusted runner boundary. Rejected for this phase.

Short hosted workflow runs keep the approval record on GitHub without using a self-hosted runner. All production mutation remains local to the operator-controlled Windows host.

## Proposed design

### GitHub approval workflow

Add a manually dispatched workflow available from protected `main`, with an input naming an already published release tag. It must:

1. Resolve the tag and verify that it points to the expected protected-main commit.
2. Require successful CI and real-qBittorrent API runs on that exact commit; reject missing, failed, cancelled, stale, or mismatched-SHA results.
3. Publish a pre-approval summary with the tag, full commit SHA, release URL, and validation-run links.
4. Wait at a protected GitHub `production-approval` Environment. Approval authorizes that displayed source identity; for a sole maintainer it is recorded operator approval, not independent review. This Environment's deployment history means approval was granted, not that production is running the release.
5. After approval, emit an approval manifest binding repository, tag, SHA, workflow run ID/URL, and approval time. The operator later creates the separate `production` deployment record from the local promotion command.

Serialize approval workflow runs with a `production-approval` concurrency group and `cancel-in-progress: false`; the local promotion command also takes an exclusive host lock because GitHub workflow concurrency cannot serialize a separate local process. Reject an approval if a newer approved release supersedes it before local promotion. The workflow must not build, run Docker, contact production, or release production secrets. Grant least-privilege GitHub permissions, pin actions to full commit SHAs, keep inputs as data, and allow dispatch only from the default branch.

### Stable local deployment checkout

Create a dedicated stable checkout directory on the production Windows host, separate from the developer checkout. It becomes the Compose build context and contains a clean detached checkout of the approved tag. Before changing Compose:

- Record and verify the current database bind-mount source and all required host mounts.
- Confirm the deployment checkout is clean and at the exact approved commit.
- Change only the `qb-rss-rules` build context. Keep the database bind mount at its existing absolute path; do not move, copy, delete, or recreate the database directory.
- Preserve the existing Compose environment file and service name.
- Use read-only Compose configuration output to verify resolved context and mount sources before rebuilding.

For later promotions, update this same checkout to the newly approved tag only after preflight. Never run the finalizer from the developer checkout or a transient CI worktree. This gives the updater one predictable source path while keeping application state outside the source checkout.

### Local promotion gate and record

Provide a Windows operator command accepting a tag and approval run ID. Before invoking `Finalize-Backend.cmd --no-pause`, it verifies:

- No promotion is already running.
- Tag, full SHA, published release, approval artifact, and successful required checks all agree.
- The approval run completed after Environment approval and still names the intended release.
- The stable checkout is clean and at that exact commit.
- Compose resolves to the stable checkout and the expected existing database and host mounts.
- Docker is ready and protected backup storage is available.

On mismatch, stop before Compose or database mutation. Promotion logic comes from reviewed repository code, never an artifact-supplied script. Create a SQLite online backup, verify integrity, restore to isolated scratch storage, and record the result without exposing database contents. Then invoke the existing finalizer from the stable checkout. Capture the exact SHA, local image ID/digest, backup hash and private location reference, finalizer result, and deployed `/health.app_version` in a redacted deployment record. Mark the GitHub deployment successful only after the exact-version health check passes; otherwise mark it failed.

Before mutation, create a GitHub `production` deployment record for the exact release SHA and mark it `in_progress`. After the finalizer succeeds and `/health.app_version` matches, mark it `success`; on any deployment failure, mark it `failure`. Store the approval run ID in its payload/description. Workflow completion means only that approval was granted; a local image build alone never means production succeeded.

### Rollback and failures

- Before rebuild, retain the previous production image by immutable ID and record the running version and source identity.
- If build, startup, or health fails, stop promotion and record failure. Restore the prior image using a documented operator command; do not restore the database automatically.
- Image rollback is permitted only when the schema/data contract is compatible. Database restore is separate and destructive; it requires explicit operator authorization, a verified backup, stopped application, and a recovery plan.
- Backup integrity/restore failure stops before rebuild.
- If GitHub audit update fails after health passes, preserve the observed runtime and provide an audit-only retry that cannot redeploy or overwrite data.
- Keep backups private and apply explicit retention. Never upload them as workflow artifacts or release assets.

## Data flow

`published tag -> exact-SHA CI/API evidence -> protected approval Environment -> approval manifest -> local preflight -> production deployment in_progress -> verified SQLite backup/restore -> finalizer from stable clean checkout -> exact /health version -> production deployment success`

Production data flows only between the live host database and private local backup/scratch storage. No database data or production secret reaches GitHub Actions.

## Failure behavior

| Failure | Required result |
|---|---|
| Tag is missing, unpublished, or not on the validated commit | Reject before approval |
| Required CI/API run is absent or does not match the tag SHA | Reject before approval |
| Approval is declined or expires | No local promotion is permitted |
| Approval record mismatches requested tag/SHA | Exit before Compose or database mutation |
| Compose context or persistent mount differs from recorded contract | Stop and require reviewed configuration correction |
| Backup integrity/restore check fails | Stop before rebuild; leave service untouched |
| Finalizer validation fails | Existing finalizer stops before Docker update; record failure |
| New container fails health/version check | Restore prior image only; no automatic DB restore |
| GitHub status update fails after health passes | Preserve runtime; retry audit update only |

## Rollout

1. Implement and validate the approval workflow and exact-SHA gate without production secrets or host access.
2. Implement local preflight/record tooling and unit-test failures with temporary Compose and SQLite fixtures.
3. Run backup/restore and image rollback drills using disposable data and a disposable Compose project.
4. Review the exact shared Compose diff and independently verify the production data bind-mount path before first promotion.
5. Only after an explicit operator action, take and restore-verify the private backup, run the finalizer, verify `/health`, and record the deployment.

This spec authorizes no production Compose edit, container rebuild, database backup, or deployment.

## Validation and acceptance criteria

- Workflow tests reject missing, failed, cancelled, skipped, stale, and wrong-SHA required runs; only exact-SHA successes reach approval.
- Workflow checks prove minimal permissions, no production secrets, pinned actions, safe inputs, default-branch dispatch, and non-cancelling serialization.
- Approval-manifest tests prove tag/SHA/run matching and reject tampering or mismatches.
- Local preflight tests prove dirty checkout, wrong commit, wrong Compose context, changed data mount, stale approval, and concurrent promotion stop before Docker mutation.
- SQLite checks prove online backup integrity and successful isolated restore; failures stop before rebuild.
- Disposable Compose integration covers image retention, health/version recording, failed health, and image rollback without touching production data.
- The runbook documents exact commands, expected output, private backup retention, manual authorization, recovery, and evidence capture.
- Production acceptance requires an explicitly authorized promotion, existing finalizer success, and `scripts\runtime_state.bat --require-runtime-current --require-upstream-synced` on the exact release SHA. CI evidence alone cannot close G5b.

## Implementation-plan decisions to verify

- Select a stable deployment checkout path and verify its drive and permissions without changing Compose during planning.
- Confirm Environment reviewer identity availability and `gh` permissions/API behavior before implementing approval extraction and production deployment status updates.
- Choose whether to add a redacted release/issue comment in addition to the GitHub Deployment record; never publish private backup paths.
- Define the local promotion lock and image-retention command against the installed Docker Desktop/Compose version.

## References

- [GitHub deployment environments and required reviewers](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub deployment workflows, records, and concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)
- [GitHub REST API for deployment records and statuses](https://docs.github.com/en/rest/deployments/deployments)

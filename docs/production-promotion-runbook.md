# Manual Production Promotion Runbook

G5b keeps production changes on the operator-controlled Windows host. GitHub Actions validates source and records owner approval; it does not receive production credentials, Docker access, database files, or host mounts.

## Current eligibility

The current production runtime is v1.4.24. The first eligible promotion must use a published, validated release newer than v1.4.24. A release tag is not itself permission to deploy: its approval run must pass the protected `production-approval` Environment, and the local command rechecks the live tag, main ancestry, checks, approval, checkout, Compose configuration, health, and version.

The approval Environment must have exactly one required reviewer, `Spon4ik`, self-review allowed, administrator bypass disabled, and deployment restricted to protected branches. The approval workflow fails before queuing that Environment job if any of those settings are absent or differ. Approval is the repository owner's recorded decision, not independent review. The resulting artifact records `approved_by`, release identity, exact-SHA CI/API runs, and the workflow run. An approval artifact does not report a production deployment.

## One-time Windows setup

1. Create the dedicated deployment checkout at `%USERPROFILE%\deployments\qBittorrent-rss-rules`. Check out the approved release tag detached and keep the worktree clean. Do not use the developer checkout or a Codex worktree for promotion.
2. Create its `.venv` and install the release's backend test dependencies:

   ```powershell
   cd "$env:USERPROFILE\deployments\qBittorrent-rss-rules"
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

3. Before changing the shared Compose file, capture the current production contract while it still points at the current checkout and database:

   ```powershell
   .\.venv\Scripts\python.exe scripts\promote_production.py --capture-compose-contract --confirm-current-mounts
   ```

   This reads resolved Compose configuration and `/health`, then writes a private contract and random HMAC key under `%USERPROFILE%\docker-config\qbrss-private`. It does not copy the Compose file, database, credentials, or resolved environment values. The contract protects every resolved Compose setting except the one build-context value that will change.

4. Intentionally edit `%USERPROFILE%\docker-config\docker-compose.yml` once. For service `qb-rss-rules`, change only `build.context` to `%USERPROFILE%\deployments\qBittorrent-rss-rules`. Keep the same Compose file, `.env`, image name, service name, `/app/data` database bind mount, and read-only `/host/C/Users` and `/host/C/ProgramData` mounts. The local command stops if the resulting resolved Compose configuration differs from the captured contract in any other way.
5. Configure the GitHub `production-approval` Environment with the protections above. Do not add secrets to it. A missing or weaker Environment causes the approval workflow and local promotion command to stop.

The stable checkout directory must be created and prepared manually before promotion. The promotion command never moves the database or initializes/replaces that checkout.

## Request and perform a promotion

1. Publish a new Windows app + source release from protected `main`, with a version greater than the currently served version.
2. From the `main` ref, dispatch **Production release approval** with that published tag. The validation job resolves annotated tags to their commit and requires the latest completed push runs for the exact SHA to pass both the `required` CI job and `real-qbittorrent-webseed-api` job. It rejects failed, cancelled, skipped, missing, stale, or mismatched runs.
3. Review the displayed tag, full commit SHA, release URL, and exact run links. Approve the `production-approval` Environment as `Spon4ik`. Wait for the run to complete and retain its run ID. No Docker operation has occurred yet.
4. From the clean stable checkout at that exact release tag, run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\promote_production.py --tag v1.4.25 --approval-run-id 12345678901
   ```

   Replace the example tag and run ID with the values from the approved run. The command downloads the data-only manifest to a temporary directory, revalidates the current main workflow and approval, acquires an exclusive host lock, and runs read-only preflight checks before creating a GitHub `production` Deployment record.
5. After the record enters `in_progress`, the command creates an online SQLite backup, runs `PRAGMA integrity_check`, restores it to private scratch storage, and hashes the backup. It then retains the existing image by immutable ID, invokes `Finalize-Backend.cmd --no-pause` from the stable checkout, and requires exact `/health.app_version` and `runtime_state.bat --require-runtime-current` success before marking the GitHub Deployment successful.

The local journal and backup are stored under `%USERPROFILE%\docker-config\qbrss-private`; that directory's ACL is restricted to the current user, Local System, and local Administrators. No private path or database content is sent to GitHub. The journal records source SHA, image IDs, backup digest and private path, finalizer result, health version, and status transitions.

## Failure and recovery

- Any preflight failure stops before creating a GitHub production Deployment, backup, image tag, finalizer invocation, or container change.
- Backup or scratch-restore failure stops before image retention and rebuild. The incomplete backup is removed.
- A failed finalizer or health check marks the GitHub Deployment failed and leaves the prior image retained as `qbittorrent-rss-rule-manager:rollback-<UTC timestamp>`. The tool does not automatically change the running image or restore the database.
- If a rollback is needed, first inspect the failure and verify the previous image is compatible with the current database schema. The operator may retag the recorded immutable image ID and recreate only the service:

  ```powershell
  & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' image tag '<previous-image-id>' 'qbittorrent-rss-rule-manager:local'
  & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose --env-file "$env:USERPROFILE\docker-config\.env" -f "$env:USERPROFILE\docker-config\docker-compose.yml" up -d --no-build --force-recreate qb-rss-rules
  ```

  Then verify `/health` and record the resulting image and version. Database restoration is separate and destructive; it requires explicit operator authorization, a verified backup, a stopped service, and a recovery plan.
- If health and image verification passed but GitHub status recording failed, use the journal named in the local command's error and run `--retry-audit-record <journal-path>`. This path rechecks exact checkout, live health, current image, and the existing GitHub Deployment, and only retries audit recording; it never reruns Compose, backup, or the finalizer.
- Keep private backups according to the host's retention policy. Do not upload them to Actions artifacts, GitHub Releases, Issues, or pull requests.

## Verification boundary

Focused tests and GitHub PR checks prove checkout behavior. They do not prove production is configured or deployed. G5b production acceptance requires a newly published higher release, successful protected approval, explicit local operator invocation, verified backup restore, finalizer success, exact source/image/health evidence, and a successful GitHub `production` Deployment record. Until that operator action is authorized and completed, production deployment remains unattempted.

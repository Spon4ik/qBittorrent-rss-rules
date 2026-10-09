# Manual Production Promotion Runbook

G5b keeps production changes on the operator-controlled Windows host. GitHub Actions validates source and records owner approval; it does not receive production credentials, Docker access, database files, or host mounts.

## Current eligibility

Production currently serves healthy v1.4.34 from source SHA
`a09807f9b06fa8a55c80de12fe8b53a20e659922`. Deployment `6972627039` must
remain recorded as failed: Compose restarted the service and read-only runtime
checks later proved health, but the canonical promotion's audit proof failed
when PowerShell treated native stderr progress as an error. Its private backup
and all historical failed Deployment records must remain unchanged. No v1.4.35
plan-scoped release has been authorized or promoted yet.

The legacy per-release path remains available and unchanged. Its Environment
approval authorizes one exact release only. The plan-scoped path below may be
used only after its independent review and Environment requirements are
configured, the implementation is merged, and a plan authorization record has
been created successfully.

The approval Environment must have exactly one required reviewer, `Spon4ik`, self-review allowed, administrator bypass disabled, and deployment restricted to protected branches. The approval workflow fails before queuing that Environment job if any of those settings are absent or differ. Approval is the repository owner's recorded decision, not independent review. The resulting artifact records `approved_by`, release identity, exact-SHA CI/API runs, and the workflow run. An approval artifact does not report a production deployment.

## Plan-scoped authorization (one approval per plan)

Plan files live in `docs/plans/authorizations/<plan-id>.json`. Their strict
schema fixes the related issues, baseline SHA, acceptance criteria, exact file
allowlist, permitted operations, explicit exceptions, prohibited operations,
release constraints, expiry, and completion condition. The canonical JSON
digest is displayed with the entire plan before GitHub queues its reviewer.

The issuer is `.github/workflows/production-plan-authorization.yml`, dispatched
from protected `main` with a plan ID and one action: `authorize`, `revoke`, or
`complete`. After approval, it creates a GitHub Deployment in the separate
`production-plan-authorization` environment with the plan and digest, action,
source SHA, run identity, and reviewer identity. GitHub's approval API is
rechecked by the Windows promoter; a plan file or conversational request alone
is never authorization. Revoke and completion add separately approved records;
they do not rewrite earlier records.

### One-time trust setup required before merging this implementation

The current `gh` credential and implementation identity are both `Spon4ik`.
It would not be safe for that same identity to satisfy the new plan approval.
Configure `production-plan-approval` with exactly one trusted human reviewer
whose account is outside Codex's credentials and is not `Spon4ik`; enable
`prevent_self_review`, disable administrator bypass, and restrict deployment to
protected branches. The workflow verifies those exact settings and rejects an
approval by the dispatch actor. The designated reviewer is a plan approver,
not a per-release approver.

Also update active ruleset `24023362` to require one approving pull-request
review and code-owner review, and add `.github/CODEOWNERS` assigning the
authorization workflow, validator, promoter, and CODEOWNERS file to that
independent trusted reviewer. The current ruleset requires zero reviews and no
code-owner review, so adding a CODEOWNERS file alone would not protect the
authorization boundary. Do not change or remove the existing
`production-approval` Environment.

After those controls are active and the reviewed implementation is merged,
dispatch the authorization workflow once for the plan. Each subsequent release
uses the same plan ID; the local promoter resolves the same GitHub record on
every session and checks its current status, approval, expiry, revocation, and
digest. Every release still needs exact-source `required` and
`real-qbittorrent-webseed-api` success, a published release, protected-main
ancestry, and a complete baseline-to-release comparison. Every compared commit
must map to a merged main PR that links a plan issue; every file must match the
allowlist. PRs merged after authorization must also contain the exact line
`Plan: <plan-id>`. A bounded patch-only plan will reject a minor/major release.

Use the plan path from the stable release checkout:

```powershell
.\.venv\Scripts\python.exe scripts\promote_production.py `
  --tag v1.4.35 `
  --plan-id snapshot-recovery-122-123
```

The current candidate plan includes issue #47's initial-snapshot criterion
after a genuine new Stremio library item naturally creates an eligible rule.
It does not authorize manufacturing a provider item or forcing a production
fetch. The separate `tt39062868` discovery criterion remains open until the
configured Stremio account/library prerequisite is satisfied and verified.

The ordinary promotion still verifies the stable detached checkout, immutable
rollback image, private SQLite backup and integrity, Compose HMAC/mounts,
single-service finalizer, `/health`, runtime-current state, and production
Deployment audit. A plan permission cannot override any failed technical gate.
Source-rebuilt rollback, database restoration, or other exceptions stop unless
the exact operation is explicitly listed in `authorized_exceptions`.

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

   This reads resolved Compose configuration, verifies that `/health` responds, and confirms the `/app/data` host mount contains `qb_rules.db`; it then writes a private contract and random HMAC key under `%USERPROFILE%\docker-config\qbrss-private`. It does not copy the Compose file, database, credentials, or resolved environment values. The contract protects every resolved Compose setting except the build-context value. The database source may remain at the existing persistent data directory even when that path differs from the stable code checkout; the host mount is captured and checked unchanged during preflight. The source checkout may be newer than the running version; the promotion preflight separately verifies that the approved target is newer than live production.

4. After contract capture, set `%USERPROFILE%\docker-config\docker-compose.yml` service `qb-rss-rules` `build.context` to `%USERPROFILE%\deployments\qBittorrent-rss-rules` if it does not already match. Keep the same Compose file, `.env`, image name, service name, `/app/data` database bind mount, and read-only `/host/C/Users` and `/host/C/ProgramData` mounts. The local command stops if the resulting resolved Compose configuration differs from the captured contract in any other way.
5. Configure the GitHub `production-approval` Environment with the protections above. Do not add secrets to it. A missing or weaker Environment causes the approval workflow and local promotion command to stop.

### Owner-approved v1.4.31 source fallback

The deployed v1.4.31 immutable image was not recoverable from Docker or trusted archives. The owner approved a source-rebuilt fallback from protected source SHA `c2abf87db7172b8444fb3b8b7c159f6e21735c20`. This fallback proves source/version lineage and scratch database compatibility; it does **not** prove binary identity with the unavailable image.

After the stable checkout and Compose contract are ready, build and verify the private fallback using the preserved private deployment backup as a read-only source. The builder makes a separate scratch DB copy, verifies the v1.4.31 container health and DB integrity/rule count, and writes private provenance under `%USERPROFILE%\docker-config\qbrss-private\rollback`:

```powershell
python scripts\build_rollback_fallback.py `
  --compose-file "$env:USERPROFILE\docker-config\docker-compose.yml" `
  --env-file "$env:USERPROFILE\docker-config\.env" `
  --scratch-source "$env:USERPROFILE\docker-config\qbrss-private\backups\<verified-v1.4.32-backup>.sqlite3" `
  --private-root "$env:USERPROFILE\docker-config\qbrss-private" `
  --repository-root "<developer-repository-root>" `
  --docker "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
```

Promotion still requires the exact prior image by default. Only with the explicit `--allow-source-rebuilt-fallback` flag will preflight accept `v1.4.31-source-fallback-verified.json`; it rechecks the protected source SHA, resolved Compose contract HMAC, Dockerfile digest, inspectable immutable fallback image ID, v1.4.31 health, and scratch DB evidence. The private journal records that the rollback is source-rebuilt and not byte-identical. This option does not bypass the protected approval gate or any backup/finalizer/health checks.

The stable checkout directory must be created and prepared manually before promotion. The promotion command never moves the database or initializes/replaces that checkout.

## Request and perform a promotion

1. Publish a new Windows app + source release from protected `main`, with a version greater than the currently served version.
2. From the `main` ref, dispatch **Production release approval** with that published tag. The validation job resolves annotated tags to their commit and requires the latest completed push runs for the exact SHA to pass both the `required` CI job and `real-qbittorrent-webseed-api` job. It rejects failed, cancelled, skipped, missing, stale, or mismatched runs.
3. Review the displayed tag, full commit SHA, release URL, and exact run links. Approve the `production-approval` Environment as `Spon4ik`. Wait for the run to complete and retain its run ID. No Docker operation has occurred yet.
4. From the clean stable checkout at that exact release tag, run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\promote_production.py --tag v1.4.28 --approval-run-id 12345678901
   ```

   Replace the example tag and run ID with the values from the approved run. The command downloads the data-only manifest to a temporary directory, revalidates the current main workflow and approval, acquires an exclusive host lock, and runs read-only preflight checks before creating a GitHub `production` Deployment record. Preflight must inspect the running container's immutable image ID and verify Docker can resolve that same ID for rollback retention; an absent or mismatched image stops promotion before the Deployment record, SQLite backup, or Docker mutation.
5. After the record enters `in_progress`, the command creates an online SQLite backup, runs `PRAGMA integrity_check`, restores it to private scratch storage, and hashes the backup. It then retains the existing image by immutable ID, invokes `Finalize-Backend.cmd --no-pause` from the stable checkout, and requires exact `/health.app_version` and `runtime_state.bat --require-runtime-current` success before marking the GitHub Deployment successful.

The local journal and backup are stored under `%USERPROFILE%\docker-config\qbrss-private`; that directory's ACL is restricted to the current user, Local System, and local Administrators. No private path or database content is sent to GitHub. The journal records source SHA, image IDs, backup digest and private path, finalizer result, health version, and status transitions.

The updater's lifecycle inspection passes the Compose service label key to Docker's Go template. In PowerShell, build the key's double-quote delimiters explicitly (for example with `[string][char]34`) so the exact format argument contains `{{index .Config.Labels "com.docker.compose.service"}}`. The lifecycle regression test checks this argument; a malformed template can fail after Compose has already recreated the service and must leave the Deployment recorded as failed.

## Failure and recovery

- Any preflight failure stops before creating a GitHub production Deployment, backup, image tag, finalizer invocation, or container change.
- If Docker cannot inspect the exact immutable image ID reported by the running production container, do not substitute the mutable `local` tag, a different rollback tag, a rebuild, or a committed/exported container. Restore the exact image from a trusted archive if one exists. Otherwise, keep promotion stopped until the owner explicitly approves a documented alternative rollback guarantee and its tooling is reviewed.
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

Focused tests and GitHub PR checks prove checkout behavior. They do not prove production is configured or deployed. G5b production acceptance requires a newly published higher release, successful protected approval, explicit local operator invocation, verified backup restore, finalizer success, exact source/image/health evidence, and a successful GitHub `production` Deployment record. A failed promotion attempt remains incomplete until a validated release passes the full sequence.

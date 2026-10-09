# Phase 39 - Plan-Scoped Production Authorization

## Goal

Replace per-release human production approval with one verifiable authorization
for a bounded plan. The repository owner requests authorization for a canonical
plan, and a separately configured human reviewer approves that plan once.
Every release still passes exact-source CI, release, rollback, backup, Compose,
health, and Deployment-audit checks. The existing `production-approval` gate
remains active until the replacement is merged, tested, and proven in production.

## Security boundary

- A plan document in Git is scope input, not proof of approval.
- The owner dispatches `.github/workflows/production-plan-authorization.yml`
  from protected `main`. It validates and displays the complete canonical plan
  before waiting on the separate `production-plan-approval` Environment.
- The plan Environment has exactly one configured GitHub user other than
  `Spon4ik`, requires self-review prevention, disables administrator bypass, and
  restricts deployment to protected branches. GitHub's approval-history API
  authenticates that reviewer. The workflow rejects approvals by the dispatch
  actor, so the current Codex `gh` identity cannot approve its own request.
- After approval, the workflow writes a GitHub Deployment record containing
  the canonical plan and SHA-256 digest, action, workflow run, source SHA,
  reviewer identity, and timestamp. The Deployment is durable and does not
  depend on a 90-day Actions artifact. Its success status disables automatic
  inactivation so historical authorization records remain verifiable.
- The Windows promoter accepts only bot-created records linked to the trusted
  workflow, its successful record job, and the successful independent-review
  Environment approval. It validates the record on every release.
- Revoke and complete are separately approved append-only state transitions.
  They preserve earlier authorization records and production Deployments.
- The legacy exact-release approval path remains available and fail-closed
  during migration. Plan-authorized releases use the new path without invoking
  the legacy per-release Environment job.

## Authorization contract and scope

Each strict-schema plan records a unique ID, related issues, baseline SHA,
acceptance criteria, path allowlist, permitted operations, explicit exceptions,
prohibited operations, protected-source and exact-check requirements, release
version policy, expiry, and completion condition. Unknown contract fields are
rejected. No secret, provider credential, or host/database location is included.

For each release, compare the plan baseline to the exact release SHA using
paginated GitHub comparisons, associated PRs, and complete PR file lists. Fail
closed if the release does not contain the authorization implementation or is
not an ancestor of protected `main`, a comparison is incomplete, a commit has
no merged-main PR, a PR lacks a related issue reference, a post-authorization
PR lacks the exact `Plan: <plan-id>` marker, or any file is outside the
allowlist. Continue requiring successful `required` CI and
`real-qbittorrent-webseed-api` runs for each exact release SHA. Enforce the
plan's stable/patch version policy.

The candidate `snapshot-recovery-122-123` plan relates to issues #47, #122, and
#123. Its production acceptance for #47 is specifically the initial-snapshot
criterion after a genuine new Stremio title naturally creates an eligible rule.
The separate `tt39062868` library-discovery criterion remains subject to the
documented provider-account/library prerequisite and stays open until separately
verified. The plan permits scoped fixes, tests, patch releases, and canonical
single-service production promotion. It prohibits manufacturing provider items,
manually fetching production rules, database restoration, Compose/credential
changes, rollback-image substitution, rewriting failed Deployments, and
validation bypasses. Its patch-only policy rejects major/minor version changes.
Source-rebuilt rollback is not an authorized exception for this plan.

Every plan-authorized promotion still requires the stable detached checkout,
exact immutable rollback image, private SQLite backup and integrity check,
Compose HMAC/mount validation, finalizer, exact `/health` and runtime version,
and successful GitHub production Deployment audit. Authorization cannot turn a
failed safety gate into success.

## Migration and one-time trust setup

The legacy `production-approval` Environment remains unchanged. Live ruleset
`24023362` currently has `required_approving_review_count=0` and
`require_code_owner_review=false`; `Spon4ik` is the only collaborator and is
also the implementation author. The current implementation credential must not
be able to self-approve plan scope or the authorization controls.

Before merging the issuer/validator, the owner must designate an independent
human reviewer outside Codex credentials, grant that person repository read
access, configure `production-plan-approval` with that single reviewer,
`prevent_self_review=true`, no administrator bypass, and protected-branch
policy, and assign that same reviewer in `.github/CODEOWNERS` for the issuer,
validator, promoter, and CODEOWNERS file. The owner must update ruleset
`24023362` to require one approving PR review and code-owner review. This is a
one-time trust setup; each plan receives one Environment approval, and releases
inside that plan do not receive additional approvals.

Do not disable the legacy gate before the plan path is merged, exercised, and
proven. No ruleset, Environment, or production configuration is changed by this
implementation branch.

## Regression and acceptance

Tests prove canonical digests, approved-plan reuse across multiple releases,
reviewer identity separation, forged/changed records, expired/revoked/completed
plans, issue/PR/file scope, patch-only releases, and fail-closed promoter API
resolution. Existing gates continue to block invalid release identity, failed
CI, missing rollback, failed backup, changed Compose mounts, and runtime/audit
failure. Historical failed Deployment records remain unchanged. Separate
processes resolve authorization from GitHub's Deployment ledger rather than
local state.

End-to-end acceptance requires one plan approval, at least two in-scope release
iterations without a second plan approval, the complete canonical production
promotion safeguards on each, and production snapshot/runtime evidence. It is
not proven by local tests or by an unapproved candidate plan.

## Current execution state

- v1.4.34 serves healthy production. Deployment `6972627039` remains failed in
  GitHub because the updater's PowerShell native-command boundary failed to
  prove the service. Preserve it and all earlier failed Deployment records.
- A private pre-promotion backup and read-only live-database comparison prove
  three missing eligible snapshots were persisted after startup. Fourteen
  remaining snapshotless Stremio rules are disabled or completion-blocked.
- The updater now uses a native PowerShell process boundary with regression
  coverage. Focused updater, promoter, and plan-authorization tests pass (55
  total); full `scripts\check.bat` passes Ruff, mypy (49 files), and pytest
  (720 passed, 0 failed, 1 skipped).
- Candidate plan, issuer workflow, strict validator, promoter integration,
  tests, changelog, and runbook are validated locally on the feature branch.
  Release commit enumeration uses the paginated GitHub commits endpoint rather
  than the compare endpoint's capped commit list. UTC timestamp checks account
  for host local/UTC clock skew. No plan authorization run, ledger record, new
  release, or production Deployment has been created.
- The validated branch is pushed as
  `codex/plan-scoped-production-auth` at
  `139895b7e010b2f1ed8c096297dd975d2a9b8821`; draft PR #125 is open with all
  required checks passing on that exact head. No workflow, release, or
  production promotion is active.
- Live GitHub still has only collaborator `Spon4ik`, ruleset `24023362` requires
  zero approving reviews and no CODEOWNERS review, and the
  `production-plan-approval` Environment is not configured. The one-time
  independent reviewer, Environment, CODEOWNERS, and ruleset setup remains the
  external boundary before merge or plan authorization. The legacy
  `production-approval` gate and production configuration remain unchanged.

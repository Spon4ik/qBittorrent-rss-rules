# Phase 44 - Acceleration operations console and variant context

## Governance follow-up (2026-09-26)

The separate [native GitHub delivery and governance plan](2026-09-25-native-github-delivery-governance.md)
tracks stronger TDD/isolation, CI, protected-main and delivery evidence. G1 and
G2 and G3a repository templates are now implemented on `main`; G3b native Project
inspection is pending access. This
governance work does not complete or change Phase 44's product scope. Keep any
unfinished Phase 44 work separate from governance commits.

## Status

Implementation is complete through v1.4.31 and protected approval. The current
series acceptance/handoff correction is in PR #112; the independent promotion
audit reconciliation is tracked by #113.

## Series progress and selective queue recovery (2026-09-29)

### Corrective v1.4.31 continuation (2026-09-29)

The published v1.4.30 release is superseded and must not be promoted. Its
approval run `36563977371` failed at the protected approval step. Corrective
review reopened #99, #100, and #101; #97 remains open, #98/#105 remain closed,
and #102 tracks v1.4.31 promotion and acceptance. PR #109 merged as
`c2abf87db7172b8444fb3b8b7c159f6e21735c20`; current main is
`81295202747f224a4aac0e6da2024c8e11e43f0f`. Fresh approval run `36612074541`
passed all jobs from current main and remains bound to published v1.4.31 at the
exact PR #109 merge SHA. Docs-only main commits were not deployed.

Production promotion Deployment `6742723277` used the documented stable
checkout and canonical finalizer. Ruff, mypy, and pytest passed (692 passed, 1
skipped); the service now runs healthy on image
`sha256:b668f091553797bdbb797f9ee9dfdb96c2ac92c42e8afb373ab0a769f0167cac`,
`/health.app_version` is 1.4.31, and stable checkout is clean at the approved
SHA. Compose still mounts the intended persistent database and read-only host
paths. The first updater verification failed and left the GitHub Deployment
and private journal at failure; a subsequent canonical updater run succeeded,
but the promotion tool does not support audit retry from that failure stage.
The verified online SQLite backup remains private and intact.

The original #97/#99 regression target is The Boys (`tt1190634`), established
by PR #103's deterministic tests and #99's episode-9 acceptance case. Running
Point (`tt14879018`) was chosen later as an inferred substitute because its
live state resembled the scenario; it is not the reproduced target. The
current read-only production DB has The Boys at floor S05E09, Jellyfin watched
through S05E08, no existing-unwatched episodes, and Stremio-known episodes
through S05E08 with no persisted watched keys. This does not reproduce the
historical season-1 stale-floor case. The old raw provider payload observation
was for Running Point and cannot establish The Boys' current raw payload.
Classify production acceptance as C: historical reproduction is presently
unprovable, not failed, and no implementation defect is demonstrated. Its
effective search floor is the persisted S05E09. Do not change provider/DB
state, run another sync, queue a production torrent, or use Running Point as
acceptance evidence.

Deployment `6742723277` and its private journal retain their original failed
status. Its first lifecycle audit recorded one container ID and Compose exit
0, but Docker inspect failed both before and after Compose, leaving metadata
empty. A later canonical updater run from the same approved checkout
successfully audited the running healthy service with the same single-argument
inspect template. An isolated mocked lifecycle snapshot using that template
also passes. The initial failure is not reproduced; there is no demonstrated
source/template defect, and the earlier undefined-`com` diagnosis is
withdrawn. Treat it as a transient/invocation-level inspect failure. A
separate follow-up should support recovery evidence when a later deterministic
audit proves runtime after the deployment status has become immutable-failed.
The series code and queue retry remain covered by merged regression tests;
the open series acceptance is only the historical production reproduction
boundary. Project #2 must track this separately from audit recovery.

Issues #97-#102 tracked a reproduced series queue defect and initial fixes. PR
#103 merged head `9b0c486cac3d05a2ab8f45a21a80a6c2d1bb6501` to protected main
as `31c5c0fdf01c7b3657489bdd1945a4b7e462253e`. Corrective review found
acceptance gaps; #99-#101 are reopened and #97 remains In Progress.
Stremio completion is now derived from its catalog episode bitfield; a selected
episode ID or aggregate watch time alone cannot mark an in-progress episode as
watched. Queueing can optionally retry existing-but-unwatched files for one
request, while still excluding watched episodes. Result queue errors can be
dismissed. CI also requires a synchronized SemVer increment and release notes
for deployable changes, with commit SHA identity used for non-deployable-only
changes. v1.4.30 is superseded/not for production; corrective target is v1.4.31.

Focused regressions and maintained UI check `P44-03` pass. The full backend
gate and WinUI/package/smoke evidence above apply to the historical v1.4.30
source only. Approval run
[36563977371](https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/36563977371)
ended in failure at `Record production approval`; production remains v1.4.28.
They do not qualify v1.4.30 for production. See [current
status](current-status.md) for corrective branch validation and next steps.

### Version policy path coverage follow-up (#105)

Review after #103 merged found that `scripts/check_version_policy.py` omitted
some inputs copied or used by Docker and Windows release packaging. Issue #105,
a child of #97, is complete through PR #106. The follow-up adds Alembic,
Docker build-context, and desktop package/install paths to the deployable
classifier with deterministic coverage. PR CI and exact-main CI/API checks
passed; exact current main is `a0b86d93fc7b1663a545e870f88b443d800d8953`.
Because this follow-up changes policy tooling and tests only, no app-version
bump or release was needed; commit SHA remains the source identity.

## Provider and production-start follow-up (2026-09-28)

- Issue #88 is closed as **cleanup recommended but not required**. The completed
  Real-Debrid object has no current app job reference by hash or provider ID and
  no persisted text/JSON record refers to either identifier. It consumes no
  active-torrent slot (`0/100`). Maintained app cleanup does not delete provider
  torrents. Optional removal from the account's torrent list was not performed;
  provider storage retention/cost and historical ownership remain unknown. No
  provider or database state changed.
- Issue #89 is closed through PR #92. The maintained updater records before and
  after container/image identity, state/health, Compose result, identity change,
  unique attempt ID, shared run ID, and whether one matching service container
  is proven running. A successful Compose exit without that proof fails the
  updater. Mocked-output tests cover identity, retries, false-success rejection,
  and secret exclusion. CI and qBittorrent API checks passed on PR head
  `afb353ffe75b9bf60c5eb3919257f14f3a2701ef` and exact main
  `36d2b4545b78dafea09b6d4dbd0c61c4abaeaf8d`.
- Maintained start path: `scripts/update_docker.ps1` through its wrapper and
  finalizer; approved production promotion invokes that finalizer. Possible
  external/manual paths are Docker Desktop/UI/CLI, the runbook's direct Compose
  rollback, and Docker daemon restart-policy activity. Scheduled maintenance
  targeted only Jackett and Audiobookshelf and failed before the historical
  start. Retained lifecycle events do not identify the historical caller.
  Attribution remains limited to the maintained updater. No production Docker
  operation, deployment, database/volume operation, provider mutation, or
  release was performed; production remains at v1.4.28. Full evidence is in
  [current-status](current-status.md).
- The only pre-existing open product issue, #47, was re-triaged against current
  state. A read-only Stremio library query returned 539 raw items with no
  `tt39062868` reference, and the DB contains no exact rule. The latest persisted
  auto-sync succeeded; the issue is not currently reproducible and remains
  Backlog pending confirmation that the title is still in the intended library.

## Deterministic maintenance follow-up (2026-09-26)

The `docs/repository-agent-skills` branch carries two additional application
changes for review: persist one redacted maintenance incident only after an
acceleration job reaches a terminal state, and retry failed rules once within the
same scheduled fetch batch. Regression tests and the issue-test inventory are
included. These changes remain unreleased and undeployed. Focused validation
passes (`32 passed`); Ruff and mypy pass; the full suite passes (`605 passed,
0 failed, 0 errors, 1 skipped`). Compose path auto-repair is excluded; the shared
build context and database bind mount must be changed intentionally. Production
deployment remains pending.

## Closed historical follow-up: Real-Debrid WebSeed 400 (issue #48)

Issue #48 was closed after PR #49 fixed percent-encoding for qBittorrent's
`addWebSeeds` contract and verified the exact job's WebSeed readback and Range
response. Current provider reconciliation for the separate lost historical job
is tracked in issue #88 above.

The selected Real-Debrid file was unrestricted and its HTTP Range proxy worked,
but qBittorrent rejected `addWebSeeds` with HTTP 400. The cause was qBittorrent's
extra percent-decoding of form data before strict URL validation. The client now
adds the required encoding layer for add/remove and normalizes raw-Unicode API
readback. A pinned qBittorrent 5.2.3 CI integration test creates a temporary
torrent and verifies add, readback, removal, and cleanup. The exact saved job was
retried against the running app; it reached `webseed_attached`, qBittorrent's
readback matched the saved URL, and the proxy returned HTTP 206 for a one-byte
Range request. Focused unit and integration tests pass (`22 passed`). PR #49 was
squash-merged to protected `main` as `ec3cc845`; pinned qBittorrent integration
passed on the PR and merge commit (runs `36197363920` and `36198173177`). Ruleset
`24023362` requires PRs and the integration check, enforces up-to-date heads,
resolved review threads, squash-only merges, and blocks force-push/deletion
without bypass actors. Issue #48 is closed. Post-merge `Finalize-Backend` passed
Ruff/mypy but stopped before Docker after pytest reported 576 passed, 7 failed,
1 skipped: one startup timing test and six resolution-quality expectations.
Issue #50 tracks full-gate recovery. The running app remains v1.4.21; v1.4.22
deployment and release await a green finalizer.

## Product decision

The global background strip is a progress surface, not an operations console. It
shows only currently queued/running transient work. If acceleration failures need
attention, it shows one compact count linking to `/acceleration`.

`/acceleration` is the centralized torrent-level maintenance screen. It provides:

- problem, active, finished, and all filters;
- torrent-name/hash search;
- full torrent name, provider state/error, update time, and secondary hash reference;
- Retry, Ask Codex, Dismiss, and Remove acceleration actions with explicit scope.

Rule search variants are correlated to acceleration jobs only through exact
infohash equality. A matching card/table row shows current acceleration state and
compact Retry/Ask Codex actions. Category or title inference is forbidden.

## Safety contract

- Retry affects only the exact acceleration job.
- Dismiss changes notification visibility only.
- Remove acceleration removes app-owned web seeds/job state but not torrent/files.
- Ask Codex persists a redacted, deduplicated job request.
- The short hash is diagnostic identity, never a rule label.

## Validation status

- Follow-up `v1.4.18` consolidates the result and queue controls into one
  aligned wide-desktop toolbar, uses compact normal-case queue labels, and
  extends readable non-expanding dark disclosures to the left rule-settings
  rail. Live measurements show identical indexer/category/queue dropdown Y
  coordinates, unchanged toolbar height with each menu open, zero downstream
  field shift when Language opens, and zero page overflow. Ruff/mypy and all
  `549` tests pass, WinUI is zero-warning, and Docker serves `v1.4.18`. PR
  `#43`, annotated tag `v1.4.18`, and the GitHub Release are published.
- Follow-up `v1.4.17` UI hardening restores readable dark-mode filtered-result
  text, aligns the rule Result controls responsively, and makes result indexer/
  category menus overlay the table instead of expanding the sticky toolbar.
  Live Docker screenshots cover the closed toolbar, open overlay, visible
  filtered rows, Search page, and acceleration page. The final 1180/2048px
  checks have zero page overflow and opening a menu leaves the toolbar height
  unchanged; the full `549`-test gate and zero-warning WinUI build pass. PR
  `#42`, annotated tag `v1.4.17`, and the GitHub Release are published.
- Ruff/mypy and all 549 tests pass; the WinUI build is zero-warning.
- Live Docker `/acceleration` has zero horizontal overflow at 2048x1150 and renders
  centralized problem rows/actions.
- Live Reacher rule variants expose acceleration context for exact matching hashes;
  notices remain collapsed and there is zero horizontal overflow.
- The real queued Codex request is persisted but has not yet been claimed while
  this owning task is active. Completion requires status transition and UI readback.

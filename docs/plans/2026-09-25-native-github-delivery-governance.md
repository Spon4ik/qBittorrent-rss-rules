# Native GitHub delivery and project governance plan

## Status and scope

**Status: IN PROGRESS.** This plan was prepared on 2026-09-25 and is being executed
in small, separately validated pull requests. G1 test isolation and G2 hosted CI /
main protection are complete on `main`; repository ownership remains `Spon4ik` and
no transfer is in scope. G3 is next. Its repository-local templates can proceed
now; native Project inspection and configuration await Project API access. G4-G6
remain future work and are not implied by this update.

Scope: deterministic TDD, isolated validation, CI/CD, protected `main`, native
GitHub work tracking, dependency/security maintenance, and truthful release evidence.
The application remains Python/FastAPI/SQLite with a Windows WinUI shell and a
Docker runtime. Phase 44 remains the active product phase; this is a separate
governance track, not a replacement phase or a declaration that Phase 44 is done.

## 1. Does the repository need to move first?

**No.** The current public personal repository can use GitHub-hosted Actions,
repository rulesets, issues, milestones, and Projects. Public repository rulesets
are available under GitHub Free. [GitHub rulesets][rulesets]

**Recommended direction:** move to `Spon4ik-Labs` before configuring organization
issue types/fields or adopting shared organization runners, if those remain the
desired end state. Planning, test isolation, and hosted CI do not depend on that
decision. An organization-owned Project can also track personal-repository issues;
that alone is not a reason to transfer. [Issue types][types], [issue fields][fields],
[runner access][runner-access]

| Capability | Stay under `Spon4ik` | Transfer to `Spon4ik-Labs` |
| --- | --- | --- |
| TDD and temporary test databases | Fully available | Same requirements |
| Hosted PR CI and repository rulesets | Fully available for this public repo | Available, plus applicable organization policy |
| Issues, sub-issues, dependencies, milestones | Available | Available |
| Projects | User or organization Project | Organization Project fits shared ownership |
| Organization issue types and issue fields | Not an organization-repository baseline | Configure/reuse organization definitions |
| Existing organization runner pool | Cannot be assigned to this personal repo | Eligible only after access and host-safety review |
| Repository-scoped self-hosted runner | Possible without transfer | Possible, but avoid unnecessary duplicate infrastructure |
| Native merge queue | Not this personal-repository option | Possible for public organization repos; deferred until needed |

GitHub documents runner scopes and merge queue availability in [runner access][runner-access]
and [deployment concepts][merge-queue]. The recommendation above is a design choice
for this project, not a GitHub requirement to move.

### Transfer gate: separate, explicitly authorized operation

Before any future transfer, the maintainer must choose the destination and approve
the concrete migration inventory. Keep the name and public visibility unchanged
unless separately requested. Required preparation:

1. Confirm source admin access, target create-repository permission, name/fork
   conflicts, organization defaults, inherited rulesets, Actions policy, and member
   access. Export a redacted settings inventory; never include credential values.
2. Review runner groups **before transfer**. At this audit, `Default` permits all
   repositories, permits public repositories, and is not restricted to selected
   workflows. A transferred public repo must not inherit usable access to a
   privileged persistent runner. Agree on selected-repository/workflow restrictions
   or retain a hosted-only design. Changes affecting other repos require their own
   impact review; do not silently change the shared pool.
3. Inventory GitHub Apps, webhooks, secret/variable names, deploy keys, OIDC trust
   subjects, Packages/GHCR links, Pages, release/download URLs, and hardcoded owner
   references. Check actual integrations rather than assuming redirects fix them.
4. After transfer, verify repository identity, Git history, PR #46, issue #47,
   releases/tags, access, and integrations. Update remotes in known clones and
   worktrees. Record any assignee changes. Do not recreate the old repository URL.
5. Leave the local checkout at `E:\GitHub\qBittorrent rss rules` and its production
   data mounts in place. A GitHub ownership change does not require a filesystem move.

Issues/PRs and Git history transfer; secrets/webhooks/deploy keys remain associated.
Personal-to-organization transfers can clear non-member issue assignees, organization
defaults apply, and Pages/package links need separate attention. Recovery is an
audited follow-up, not an assumed one-click undo. [Transfer documentation][transfer]

If transfer is deferred, use hosted CI, repository rulesets, existing labels for
work type, and Project fields for priority. Keep these concepts easy to map later.

## 2. Observed baseline

Read-only baseline audit on **2026-09-25**; recheck live settings before any further
GitHub configuration because state can change. G1/G2 implementation evidence is
recorded below and in `docs/plans/current-status.md`.

| Area | Evidence / limitation |
| --- | --- |
| Repository | Public `Spon4ik/qBittorrent-rss-rules`, default `main`; admin access available |
| Main protection | Rulesets list empty; branch-protection API returns `404 Branch not protected` |
| Actions | Workflow inventory count 0; no `.github` directory in the inspected checkout |
| Runner configuration | Repository runner count 0; org pool previously inventoried with `generic-01`, `generic-02`, `browser-01` online; shared group access rechecked as described above |
| Organization | `Spon4ik-Labs` reports Team plan and default repository permission `read`; host isolation, current ACLs, issue fields, and Project automation were not verified |
| Work tracking | Current audit: open issue #47 is a bug without a milestone; no repository milestones; Project inventory is unverified because the CLI token lacks `read:project` |
| Skills / PR | Skills are on open PR #46, branch `docs/repository-agent-skills`; pre-plan head `f94628bcadab2eabde60005aa9eb967c5f27fdb8`; they do not configure GitHub enforcement |
| Existing local checks | `scripts/check.bat` / `check.sh`: Ruff, mypy, then compact pytest wrapper; `browser_qa.py` has isolated process/stub support |
| Existing isolation | `configured_app_env` supplies a per-test SQLite path and disables several integrations/schedulers, but is not autouse; import-time, subprocess, and teardown isolation still need an audit |
| Deployment | `Finalize-Backend.cmd --no-pause` runs full checks, Docker update, and runtime-version validation; it is an operator deployment gate, unsuitable for ordinary PR jobs |
| Read-only runtime snapshot | `scripts\runtime_state.bat` exited 0 and reported running v1.4.21 equals the dirty checkout's v1.4.21; this is version equality, not proof of deployed source SHA or of this branch's committed contents |
| Version / docs drift | Committed branch is based on the v1.4.20 release; local edits contain v1.4.21. ROADMAP's v1.4.11 heading and historical status statements require reconciliation against release/runtime evidence before becoming current claims |
| Workspace | Uncommitted Phase 44/application changes predate this plan. They must remain separate from governance commits; exact deployed-source identity remains unverified |

Audit APIs: repository metadata; `branches/main/protection`; `rulesets`;
`actions/workflows`; `actions/runners`; `milestones`; org metadata and
`orgs/Spon4ik-Labs/actions/runner-groups`. Preserve future inventories as small,
redacted artifacts with date, repository ID, and observed commit.

## 3. What to reuse from tab-rule-manager

Reference snapshot: `Spon4ik-Labs/tab-rule-manager` commit
`83d2f7f7e048a4025e2ebb4803b8b1fb69ec1f7f`, verified present on GitHub. Relevant files:

- [`docs/CODEX-WORKFLOW.md`][tab-workflow]: deterministic TDD, layered validation,
  native merge enforcement, and separate post-merge evidence.
- [`docs/ISSUE-HIERARCHY.md`][tab-issues]: hierarchy, dependencies, milestones, and
  Project views represent different facts; evidence determines completion.
- [`pr-qualification.yml`][tab-qualification]: live policy inspection and native
  auto-merge illustrate enforcement beyond local instructions.

Adopt those principles. Start with ordinary GitHub checks and native relationships.
Defer Tab's custom qualification publisher, dispatch progression, synthetic candidate
commits, issue-comment command parser, recovery control plane, and custom branch
cleanup. Add such machinery only for a demonstrated gap, with its own tests and
documented permissions. Do not import extension-specific browser scheduling or a
blanket ban on reruns: classify infrastructure failures and retain the failed evidence.

## 4. Proposed operating model

### TDD and data safety

- Every confirmed behavior defect gets a deterministic regression reproducing its
  actual triggering state: RED for the expected reason, minimal repair, GREEN, then
  affected-module and full relevant validation. Record test node ID, command, exit
  status, and commit; do not infer success from a screenshot or a model's opinion.
- PR evidence should include RED/GREEN results; the final PR head must be green.
  A workflow cannot prove historical TDD from a green final commit alone. Review
  the reproduction and evidence instead of inventing a synthetic “TDD passed” check.
- Use synthetic fixtures and a unique temporary SQLite database for each owning
  test/process. Install a safe environment before importing application modules.
  Deny production database paths, production service endpoints, real credentials,
  and user Stremio/Jellyfin paths in automated tests. Allow loopback stub servers.
  Pytest provides per-test temporary directories and scoped environment changes.
  [Temporary directories][pytest-temp], [environment patching][pytest-env]
- Audit cache resets, queue/scheduler ownership, worker shutdown, subprocess
  environment inheritance, `.env` loading, and parallel execution. A test must join
  its workers before releasing its temporary database/configuration.
- A local reproduction needing real state uses an explicitly scoped, sanitized
  snapshot with integrations disabled. Routine TDD and CI never run against the
  production database. Live diagnostics and read-only deployment smoke evidence
  are separate activities; even GET endpoints require review for side effects.
- Preserve compact logs/JUnit and relevant DOM/API assertions. Retain screenshots
  only when useful for a failure; exclude databases, user settings, tokens, and
  provider payloads from public artifacts.

### Native work tracking

| Fact | Authority and proposed rule |
| --- | --- |
| Work item | GitHub Issue with expected behavior, scope/non-goals, acceptance evidence, owner, and dependencies |
| Work type | Organization `Bug`, `Feature`, `Task` where available; labels only as a temporary personal-repo fallback |
| Hierarchy | Native parent/sub-issues only for independently deliverable slices; a one-PR fix stays one issue |
| Ordering | Native blocked-by/blocking relationships; avoid a second dependency list in comments |
| Delivery target | Milestone per agreed delivery increment; assign deliverable leaves once, avoid counting both parent and children or both issue and PR |
| Priority / dates | Reuse organization issue fields when available; otherwise one set of Project fields, with no competing Priority label/field |
| Progress view | One Project: Backlog, Ready, In progress, In review, Done; show parent, sub-issue progress, milestone, priority, assignee |
| Implementation evidence | PR linked to issue, commit/check URLs, redacted test result, changelog and version decision |
| Deployment evidence | GitHub Environment/deployment record plus exact deployed commit/image, health evidence, and rollback target |

Use built-in Project auto-add/status/archive workflows where they fit. Issue closure
means its acceptance criteria are met. Use `Closes #N` for implementation-only work;
for issues requiring deployment/release evidence, keep them open until that evidence
exists, or explicitly split delivery acceptance into a linked item before merging.
Do not mark everything Done because a PR merged. Docs retain design decisions;
GitHub holds live work state. [Projects guidance][projects], [sub-issues][subissues]

### CI and main protection

Proposed `.github/workflows/ci.yml`: hosted runners; `pull_request` and `push` to
`main`, plus manual dispatch for diagnosis. Start with Python 3.12 on Windows and
Linux, matching the Windows operator environment and Linux container target.

- Reuse `scripts/check.bat` / `scripts/check.sh` after G1 proves isolation. Audit
  handling of vendored `.agents/skills` scripts so application checks neither
  rewrite upstream code nor silently exclude application-owned code.
- Run maintained browser UI checks against a temporary app/stubs, initially on
  Windows. Run the WinUI x64 build on a hosted Windows image with the .NET 10,
  Windows SDK and MSBuild workload required by the actual project. Pin the
  Windows App SDK dependency after compatibility qualification; it currently uses
  `1.*`. Browser checks prove checkout behavior, not deployed Docker freshness.
- Initial lanes all run on every PR; optimize conditional heavy jobs only after
  measured cost and a deterministic change classifier. One stable aggregate job
  `required` uses `if: always()` and explicit expected job results; it fails on any
  mandatory failed, cancelled, missing, or unexpectedly
  skipped lane. No blanket `continue-on-error`, success-on-skip, or workflow-level
  path filter that leaves a required check absent. If CI is cancelled, merge blocks.
- Default `GITHUB_TOKEN` to `contents: read`; checkout without persisted credentials;
  action/reusable-workflow references pinned to reviewed full commit SHAs. Pass
  untrusted text through arguments/environment, never interpolate it as shell code.
  Fork PR jobs receive no deployment secrets or persistent-host access. [Actions
  security guidance][actions-security]
- Use per-PR cancellation, bounded timeouts, lockfile/OS/toolchain cache keys,
  dependency caches only, and short artifact retention (initial proposal: 14 days).
  Release/deployment evidence is retained separately. Never promote PR artifacts or
  writable PR caches into privileged release execution.
- Establish and observe real CI on a bootstrap PR and on `main` **before** enabling
  required checks. Select the exact emitted aggregate context and its expected
  GitHub Actions source in the ruleset. Do not assume the display name in this
  plan is the API context; record what GitHub actually emits.
- Main ruleset: PR required, force pushes/deletion blocked, required CI, branch
  up-to-date, conversations resolved, and linear history. Configure repository
  merge settings separately: squash enabled, merge commits and rebase merging
  disabled. Audit both the ruleset and merge settings. No routine bypass actors.
  Start with zero mandatory approving reviews for a sole maintainer; enable an
  independent review/CODEOWNER requirement when an eligible reviewer exists.
  Workflow/deployment/data-migration changes still receive explicit maintainer review.
- Use native auto-merge after checks are stable. Defer merge queue; if adopted later,
  add and prove `merge_group` CI before requiring it. Never manufacture statuses,
  directly merge around a red gate, or weaken tests to produce green.

Keep PR head SHA, GitHub's tested PR merge SHA, and the resulting squash/main SHA
distinct in evidence. Post-merge CI proves the actual main commit. Version equality
alone is insufficient to identify deployed code. [Rulesets][rulesets]

### Trusted runners, release, and deployment

Hosted PR CI is the default even after an organization transfer. A label selects a
runner; it provides no isolation. Several Windows services on one desktop share a
host trust boundary. Environment approval also does not sandbox an already
compromised host. [GitHub self-hosted security][selfhost-security]

Self-hosted adoption requires a demonstrated hosted-runner limitation and G4
acceptance. Prefer an isolated disposable VM with a dedicated identity; no
production database mounts, personal profile, Docker socket, or provider secrets in
test runners. A public repository must not be able to route arbitrary PR code onto
the production host. Keep privileged deployment in a separately controlled trusted
mechanism, potentially a private deployment repository after an explicit design review.

Build release artifacts from an exact protected-main commit; tag and publish the
same commit after gates pass. Use native GitHub Releases, immutable image digests,
and provenance/attestations when supported by the selected build path. Automate
delivery to an isolated staging runtime before production deployment. Keep production
promotion manual initially, associated with a GitHub `production` Environment and
trusted branch/tag selection, with least-privilege credentials released at that gate.
For a sole maintainer, self-approval must be allowed if that maintainer started the
run; describe this as a recorded operator approval, not independent review.
[Environments][environments], [reviewing deployments][deployment-review]

G5a may build and smoke-test staging artifacts and publish an approved release.
It receives no production environment or host access. Only G5b may create a
production deployment record or touch the production Compose/runtime paths, after
the separate production design and operator gate are satisfied.

Serialize production deployment with `cancel-in-progress: false`. Prevent stale
queued commits from replacing a newer deployment. Check exact source identity and
image digest before promotion; do not execute arbitrary artifact-supplied scripts.
Create a protected SQLite online backup and prove restore on a disposable copy;
copying only a live `.db` file can miss WAL state. Keep backups private. Separate
image rollback from schema/data rollback and require explicit authorization before
any destructive restore. [SQLite backup API][sqlite-backup]

**Existing deployment contract remains binding during adoption.** Until a reviewed
change to `AGENTS.md` and deployment scripts proves equivalent or stronger checks,
backend closeout still requires `Finalize-Backend.cmd --no-pause`. Invoke it only
from the intentionally selected, clean production checkout at the intended commit.
Never call it from a CI worktree: the updater can modify the shared Compose context
and data mount. Never silently repoint production Compose at a runner workspace.
The later immutable-artifact deployment design must explicitly reconcile this
rebuild-based contract before becoming the new production path.

## 5. Sequenced implementation backlog

Each row is a proposed future issue, not an issue created by this planning session.
Maintainer owns product acceptance and repository policy; the organization owner
owns shared runner/access changes. Use small PRs and preserve the existing dirty
Phase 44 work. Future behavior repairs remain subject to the repository's normal
SemVer, synchronized version touchpoints, validation, push, deployment and release
policy. Planning-only documentation does not bump the application version.

| ID | Deliverable and proposed edit surface | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| G0 | Keep the public repository under `Spon4ik` for this work; reconcile the current release/Phase 44 handoff; preserve separation from uncommitted product work | Plan review | Decision recorded; no repository transfer; exact main CI and release facts recorded; unfinished Phase 44 kept separate |
| G0-T | Optional transfer with runner-access prerequisite and post-transfer audit from section 1 | G0 and separate transfer authorization | Same repository/history/issues/PRs, intended permissions, remotes updated, integration checks, production paths unchanged |
| G1 | Audit/enforce test isolation in `tests/conftest.py`, affected test fixtures, `scripts/test.bat`, `scripts/test.sh`, `scripts/browser_qa.py`; add isolation regressions and TDD guidance | G0; independent of transfer | **COMPLETE** on main. PR #56; safe-path guard, lifecycle teardown, isolated app databases, and browser QA cleanup. See current-status evidence and `ci-migration.md`. |
| G2a | Establish hosted CI in `.github/workflows/ci.yml`; deterministic aggregate; pin reviewed action/tool inputs | G1 | **COMPLETE** on main. Windows/Ubuntu checks, maintained Windows UI suite, WinUI build, stable required aggregate, and separate real-qBittorrent API lane pass on main. |
| G2b | Enable native main ruleset, squash-only repository merge settings, and document policy | G2a working on default branch; G0-T if selected | **COMPLETE** on main. Ruleset `24023362` requires the exact CI and real-qBittorrent contexts; PR-only, up-to-date, resolved conversations, squash-only, no force-push/deletion or bypass. |
| G3a | Add English GitHub issue forms, PR template, and contribution guidance for reproducible scope, acceptance evidence, privacy, and test proof; no CODEOWNERS without additional owners | G0 | **COMPLETE** in PR #46, merged as `d227db3`. YAML/schema validation, all PR checks, and exact-main CI plus real-qBittorrent integration passed. |
| G3b | Inspect and configure one native Project, fields/status workflows, milestones, and native issue hierarchy/dependencies if useful | G0; Project API access | Project inventory recorded; one real item follows backlog → ready → in progress → review → done with acceptance evidence; no duplicate custom tracker or double-counted parent/child milestone. |
| G4 | Optional trusted runner onboarding; changes in runner-pool repo and selected access policy, not application fixture hacks; `docs/ci-runner-operations.md` | G2b, explicit need, org access decision | Dedicated identity/host boundary, repo/workflow restrictions, no production access, exact runner/job assignment, cleanup/update/recovery proof; unavailable restrictions mean remain hosted |
| G5a | Reproducible build/staging/release lane: `.github/workflows/release.yml`, dependency lock/constraints, `scripts/release_prep.py`, release/deployment runbook | G2b; G4 only if technically needed | Version touchpoints synchronized; trusted main SHA equals tag/artifact source; disposable-container health/contract smoke; staged release assets; no accidental live mounts |
| G5b | Design and implement gated production promotion, environment/concurrency, backup/restore and provenance; reconcile finalizer, updater and `AGENTS.md` before automation | G5a and separately approved production design | Existing finalizer gate or approved proven successor; verified backup restore in scratch environment; exact deployed SHA/digest and health; rollback drill; recorded approval; delivery item closed only with evidence |
| G6 | Native security/dependency maintenance and compact governance upkeep: `.github/dependabot.yml`, `SECURITY.md`, default CodeQL where suitable, dependency review, release checklist | G2b, G3 | Update PR traverses normal gate; supported Python/.NET/Actions dependencies covered; initial findings triaged; redacted artifacts; no scheduled AI issue hunting |

Sequence: G0 -> G1 -> G2a -> G2b -> G3a; G3b requires Project API read/write
access. This repo stays personal, so organization-only issue types and fields are
not prerequisites. G0-T is not selected. G4 is optional.
G0-T is required only for selected organization-specific dependencies. G4 is optional.
G5a precedes G5b; G6 follows baseline CI. A failed gate stops dependent work, not
independent documentation. No artificial calendar dates or next app version are
assigned before the maintainer chooses scope.

### Validation matrix to implement later

| Layer | Trigger / environment | Commands or assertions | What it proves |
| --- | --- | --- | --- |
| Focused TDD | Each behavior change; developer temp DB | `scripts\test.bat tests/<file>.py -k <case>`; recorded expected RED then GREEN | Reproduction and repaired behavior |
| Application CI | Every PR and push to main; hosted Windows + Linux | `scripts\check.bat` / `scripts/check.sh`, exit status + compact JUnit | Static/type and suite result for recorded tested SHA |
| Browser UI | Hosted Windows temporary app/stubs | `scripts\browser_qa.bat --suite ui`; JSON assertions; unique port/process cleanup | Checkout UI invariants, not live deployment |
| Desktop | Hosted Windows with audited build toolchain | Existing `scripts\run_dev.bat desktop-build` after proving it builds only; alternatively equivalent explicit MSBuild command captured in G2a | WinUI compiles; backend contract/version stays aligned |
| Packaging/staging | Trusted main/release lane; disposable database/mounts | Build/install from locked dependencies; container health and synthetic-data smoke | Artifact can start and meet its contract |
| Production | Approved trusted operator/deployment lane | Current finalizer contract, `runtime_state --require-runtime-current --require-upstream-synced`, exact SHA/digest assertion, bounded read-only smoke | Intended code is persisted and running; no claim that all real-provider behavior was tested |

Commands above are future acceptance steps and were **not executed for this plan**.
Only the unflagged read-only `scripts\runtime_state.bat` status query was executed.
Before G1 runs the full suite, inspect module imports and subprocess entry points;
test fixtures alone cannot make a late environment override safe.

Use #47 (`tt39062868` missing after Stremio sync) as a candidate first TDD example
only when its investigation/repair is authorized. Establish the actual source item,
type/IMDb identity, persisted sync state, and failure transition before designing a
sanitized regression. The cause is unverified; do not presuppose a title-matching bug.

### Security and upkeep details for G6

Start with weekly grouped dependency updates for Python, NuGet and GitHub Actions
(plus Docker if an applicable manifest is present). Qualify a reproducible lock or
constraints strategy against both OS lanes before treating caches as reproducibility.
Use dependency review on PRs and native vulnerability/secret alerts available to this
repo; triage existing findings before turning new checks into required gates. Prefer
CodeQL default setup when it covers the languages/build; avoid duplicate default
and advanced scans. [Dependabot][dependabot], [dependency review][dependency-review],
[CodeQL setup][codeql]

Review changes through the same rules as feature work; do not auto-merge majors or
security-policy changes without review. Keep `SECURITY.md` private-reporting guidance,
supported versions, backup retention, runner updates, and incident ownership explicit.
Measure queue time, job duration, flaky cases, and restore success from deterministic
records. No periodic AI polling, duplicate status database, or automatic public
issue creation from unredacted production logs is part of this plan.

## 6. Failure handling and completion criteria

- **Bootstrap failure:** fix and demonstrate CI before adding required contexts.
  A PR cannot be assumed to repair default-branch permissions used to run itself.
  If policy recovery later needs a privileged operation, document exact failing
  SHA/policy and obtain that specific authorization; never fake a check or bypass
  protection as routine recovery.
- **Runner failure:** keep hosted CI available. Do not redirect untrusted jobs to
  the production host to unblock a queue. Inventory error, permissions, unavailable
  SDK, test failure, and deployment failure are separate failure classes.
- **Test failure:** keep the actual assertion and representative fixture. Correct
  lifecycle/environment defects rather than weakening tolerances, suppressing
  failures, or repeatedly rerunning an unchanged failure. Permit a justified rerun
  for a demonstrated transient runner/network failure, retaining both attempts.
- **Deployment failure:** record FAILED/NOT ATTEMPTED and leave the delivery item
  open. Do not describe a merge, a version match, or a published tag as deployment
  success. Use the recorded rollback target and approved data-recovery procedure.
- **Doc drift:** current-status is a short handoff; link old evidence instead of
  copying historical green counts into today's status. Update the affected phase
  plan and changelog in the same delivery as the work they describe.

Planning completion: this plan and its status/roadmap links are committed and pushed
for review, with the pre-existing application work preserved. Implementation remains
NOT STARTED. No transfer, CI run, runner provisioning, ruleset/Project change,
application release, or production deployment is implied by this document.

Implementation completion later requires separate evidence for: application change,
focused test, full CI, native protected merge, GitHub persistence, exact production
runtime, and release/tag, wherever applicable. State PASS/FAIL/BLOCKED or NOT RUN/
NOT APPLICABLE explicitly. Do not mark G0-G6 complete from documentation alone.

## Primary references (reviewed 2026-09-25)

Links above point to primary documentation and pinned reference files. Recheck
feature availability and organization policy when implementation is authorized.

[transfer]: https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository
[rulesets]: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
[types]: https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/managing-issue-types-in-an-organization
[fields]: https://docs.github.com/en/issues/planning-and-tracking-with-projects/understanding-fields/about-issue-fields
[projects]: https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/best-practices-for-projects
[subissues]: https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
[runner-access]: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access
[merge-queue]: https://docs.github.com/en/pull-requests/concepts/deploying-code
[actions-security]: https://docs.github.com/en/actions/reference/security/secure-use
[selfhost-security]: https://docs.github.com/en/actions/concepts/runners/self-hosted-runners
[environments]: https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
[deployment-review]: https://docs.github.com/en/actions/how-tos/managing-workflow-runs-and-deployments/managing-deployments/reviewing-deployments
[pytest-temp]: https://docs.pytest.org/en/stable/how-to/tmp_path.html
[pytest-env]: https://docs.pytest.org/en/stable/how-to/monkeypatch.html
[sqlite-backup]: https://sqlite.org/backup.html
[dependabot]: https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions
[dependency-review]: https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review
[codeql]: https://docs.github.com/en/code-security/concepts/code-scanning/setup-types
[tab-workflow]: https://github.com/Spon4ik-Labs/tab-rule-manager/blob/83d2f7f7e048a4025e2ebb4803b8b1fb69ec1f7f/docs/CODEX-WORKFLOW.md
[tab-issues]: https://github.com/Spon4ik-Labs/tab-rule-manager/blob/83d2f7f7e048a4025e2ebb4803b8b1fb69ec1f7f/docs/ISSUE-HIERARCHY.md
[tab-qualification]: https://github.com/Spon4ik-Labs/tab-rule-manager/blob/83d2f7f7e048a4025e2ebb4803b8b1fb69ec1f7f/.github/workflows/pr-qualification.yml

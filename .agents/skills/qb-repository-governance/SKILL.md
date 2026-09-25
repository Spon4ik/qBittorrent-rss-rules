---
name: qb-repository-governance
description: Use when planning or auditing repository maintenance, protected main, GitHub issues and hierarchy, progress tracking, milestones, branch and PR lifecycle, GitHub Actions, or self-hosted CI/CD runner operations for qBittorrent RSS Rules.
---

# Repository governance and maintenance

Start with `AGENTS.md`, `docs/plans/current-status.md`, and the active phase plan. They define project-specific policy and current state. Use the pinned source skills in `../UPSTREAM.md` for focused GitHub features, then apply the repository constraints below.

## Upstream skills to compose

- `github-issues`: issue types, parent/sub-issues, dependencies, metadata, milestones and Projects.
- `breakdown-plan`: turn an approved plan into an actionable hierarchy.
- `repo-standardizer`: audit repository templates, labels, rulesets, CODEOWNERS and CI surfaces.
- `github-actions-hardening`: review workflow trust, token permissions, untrusted inputs and runner exposure.
- `github-actions-efficiency`: inspect measured Actions waste and workflow critical paths.
- `gh-fix-ci`: inspect and diagnose failing GitHub Actions PR checks using bounded evidence.
- `security-best-practices`: consult only for an explicitly requested security review or secure-by-default coding task in a supported language.
- `skill-creator`: use when authoring or updating skills in this repository.
- `qb-tdd`: deterministic RED/GREEN implementation discipline.
- `qb-runner-operations`: self-hosted runner inventory, lifecycle and usage.

`AGENTS.md` and live GitHub configuration outrank generic examples. Do not copy generic Agile hierarchies, scorecards, labels, custom project boards, workflows, or runner examples without showing that they fit this repository.

## Protected `main` and delivery lifecycle

1. Inspect `git status`, branch and remotes before changing branch or staging anything. Preserve unrelated user changes. Never branch-switch with a dirty worktree unless the current changes are safely isolated and preserved.
2. Keep feature work off `main`. Use a short `docs/`, `feat/`, `fix/`, or `chore/` branch. Do not commit, push, force-push, or merge directly to protected `main`.
3. Before changing branch protection or Actions policy, inspect actual repository and organization rulesets, required check names, merge methods, auto-merge and qualification workflow. Native protection is the authority; workflow YAML or a green local test is not proof of enforcement. If no workflows/checks exist, do not invent required check names; identify the lack of CI as a prerequisite and propose PR-only/no-force-push protections separately from required-status protection.
4. Deliver through the repository's authorized GitHub PR workflow. Do not bypass required checks, fabricate evidence, weaken rules to make a run green, or silently replace self-hosted required checks with hosted runners.
5. After merge, follow project-required validation and deployment gates. For backend changes, the required closeout is `.\Finalize-Backend.cmd --no-pause`; report GitHub persistence, Docker deployment and release/tag state separately.

## Issues, hierarchy, milestones and progress

- Read the existing issue inventory and project plan before creating work. Do not create duplicate issues or duplicate progress databases.
- Use native issue type for classification, parent/sub-issues for decomposition, dependency links for blockers, native fields for priority/dates when available, milestones for a coherent release target, and Projects for status/iteration views when they add value.
- A milestone groups deliverables; it does not define execution order. Use dependencies for order. Keep each logical delivery unit counted once toward milestone completion.
- Tie issues to `docs/plans/` phase scope and acceptance evidence. Keep `docs/plans/current-status.md` as the short handoff and the phase plan as detailed implementation truth. Update both at meaningful closeout.
- Progress updates state completed, active, blocked, next action, and evidence. Do not mark work complete based on estimates, comments, local green checks, or a running job alone.
- Avoid creating org-level issue types, custom fields, or Project configurations until the actual organization capabilities and existing conventions have been inspected.
- The generic `breakdown-plan` skill's Epic/Feature/Story hierarchy and milestone examples are suggestions, not GitHub's only valid model. Use the smallest native issue hierarchy that matches this repository's phase plan; do not make a milestone a parent or a second progress ledger.

## CI/CD and self-hosted runners

- Inspect the actual workflow and runner group/labels before editing `runs-on`. A label is a scheduling selector, not a security boundary.
- The known `Spon4ik-Labs` pool baseline is documented in `UPSTREAM.md` and maintained in `Spon4ik-Labs/ci-workflows`. Treat runner names, labels and state as staleable; query GitHub before routing any job.
- Treat self-hosted runners as persistent machines with workspace, process and network exposure. On public or untrusted contributions, do not execute untrusted code on privileged persistent runners. Use least-privilege tokens, isolated ephemeral workers where available, and explicit trusted-event boundaries.
- Keep runner credentials out of the repository. Registration tokens are short-lived; never store them in files, logs, skills, or workflow output. Do not bootstrap, register, delete, transfer, or reconfigure runner services without an explicitly authorized infrastructure task.
- Separate runner pool health from workflow correctness. Verify runner online/service state, labels, group access, concurrency and actual job assignment from GitHub evidence. A successful local script does not prove a workflow used the intended runner.
- Pin third-party actions to full commit SHAs when policy requires it; set minimal workflow/job permissions; pass untrusted event fields through environment variables or safe action inputs rather than interpolating into shell source. Run the repository's actual security and CI gates.

## Maintenance execution

1. Determine whether the task is diagnosis, planning, or implementation. Do not turn an audit into unsolicited GitHub writes.
2. Check phase/status and current remote policy before proposing changes. Identify what GitHub already enforces natively and what gap remains.
3. For confirmed application defects, add a deterministic regression reproducing the trigger before considering the repair complete. Keep AI investigation opt-in; do not schedule polling to find work.
4. Make the smallest change. Validate from focused check through the repository's required final gate. Do not rerun unchanged expensive gates.
5. Close the loop: update the phase plan and current status, report exact evidence, branch/commit/PR state, Docker state, and release state distinctly.

## Stop conditions

Pause only when a necessary action would risk destructive data loss, expose credentials, change broad policy outside the task, or requires an unavailable owner/organization capability. Record exact evidence and the smallest authorized next step. Do not invent a bypass.

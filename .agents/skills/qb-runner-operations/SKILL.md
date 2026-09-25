---
name: qb-runner-operations
description: Use when inspecting, using, securing, troubleshooting, or planning GitHub Actions self-hosted runners and CI/CD for this repository or its organization.
---

# Self-hosted runner operations

Read the relevant workflow, repository/organization runner policy, and `AGENTS.md` before proposing runner changes. Prefer read-only inventory first.

The known organization pool is documented in `UPSTREAM.md` and maintained in `Spon4ik-Labs/ci-workflows`. It has two `generic` Windows runners and one `browser` Windows runner; verify live runner state and repository access each time because this inventory can change. The separate `Spon4ik/tab-rule-manager` repository has repository-scoped runners that are not eligible for this repository.

## Inventory and workflow fit

- Inspect workflow triggers, `runs-on`, permissions, concurrency, artifacts/cache and required check names.
- Inspect runner group access, online/idle state, labels, service identity and machine ownership through authorized GitHub and host surfaces.
- Match workloads to the intended labels and trust boundary. Do not assume a label uniquely identifies a machine or restricts who can schedule it.
- Use `generic` for ordinary trusted CI workloads and `browser` only for workflows that need the browser runner's installed browser/test environment, after confirming those labels remain accurate.
- Prove assignment and concurrency from workflow-run/job evidence; do not infer from a green workflow alone.

## Safety

- Never expose or persist GitHub registration tokens, credentials, private keys, or environment secrets in repo files, logs or skill references.
- Do not execute fork-controlled code on a persistent privileged runner via `pull_request_target`, `workflow_run`, issue/comment triggers, or equivalent privileged contexts.
- Use ephemeral/isolated runners for untrusted work where possible; otherwise enforce trusted-event and repository access restrictions. Apply least-privilege `GITHUB_TOKEN` permissions and separate deployment environments/approvals.
- Do not change organization runner groups, labels, service accounts, ACLs, registration, or repository assignment as a side effect of a workflow edit. Treat provisioning/migration as a separately scoped infrastructure operation.

## Validation and incident handling

- For a failed job, identify run, job, exact runner, event, commit SHA, and bounded failure evidence before changing workflow or host configuration.
- Separate scheduler/runner availability from checkout, dependency, test, network, and workflow logic failures.
- After a change, verify exact check and SHA, runner assignment, expected isolation, and cleanup. Report when infrastructure access prevents proof.
- Keep reusable workflows pinned/reviewed, avoid unnecessary runner time, and use concurrency only where canceling or serializing the work is semantically safe.

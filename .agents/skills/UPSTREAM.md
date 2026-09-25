# Vendored skill sources

These skills are pinned snapshots. Review upstream changes before updating them; do not auto-update in place.

| Skill | Source | Pinned ref | Purpose |
|---|---|---|---|
| `github-issues` | [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/6c4d33b9cfca967a28bb2962ef4d55e4a384c88c/skills/github-issues) | `6c4d33b9cfca967a28bb2962ef4d55e4a384c88c` | Issues, hierarchy, dependencies, fields, milestones, projects |
| `breakdown-plan` | [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/6c4d33b9cfca967a28bb2962ef4d55e4a384c88c/skills/breakdown-plan) | `6c4d33b9cfca967a28bb2962ef4d55e4a384c88c` | Plan-to-issue decomposition |
| `repo-standardizer` | [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/6c4d33b9cfca967a28bb2962ef4d55e4a384c88c/skills/repo-standardizer) | `6c4d33b9cfca967a28bb2962ef4d55e4a384c88c` | Repository governance surfaces and audit |
| `github-actions-hardening` | [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/6c4d33b9cfca967a28bb2962ef4d55e4a384c88c/skills/github-actions-hardening) | `6c4d33b9cfca967a28bb2962ef4d55e4a384c88c` | Workflow security and self-hosted runner exposure |
| `github-actions-efficiency` | [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/6c4d33b9cfca967a28bb2962ef4d55e4a384c88c/skills/github-actions-efficiency) | `6c4d33b9cfca967a28bb2962ef4d55e4a384c88c` | CI runtime, cost, concurrency and workflow efficiency |
| `gh-fix-ci` | [openai/skills](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/gh-fix-ci) | `49f948faa9258a0c61caceaf225e179651397431` | Inspect and diagnose GitHub Actions PR checks |
| `security-best-practices` | [openai/skills](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/security-best-practices) | `49f948faa9258a0c61caceaf225e179651397431` | Language/framework security guidance |
| `skill-creator` | [openai/skills](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.system/skill-creator) | `49f948faa9258a0c61caceaf225e179651397431` | Create and validate future skills |

The CLI injected source/ref/tree metadata in each upstream `SKILL.md`. `github/awesome-copilot` is GitHub's public community-contributed collection, not a guarantee that each skill is authored or security-reviewed by GitHub. GitHub's installation documentation says skills are not verified by GitHub. A copy of the upstream MIT `LICENSE` is included as `LICENSE.txt` in each GitHub skill directory. Inspect changes and referenced scripts before executing an update. No third-party scripts are granted pre-approved shell access.

## OpenAI catalog

The official [openai/skills](https://github.com/openai/skills) repository is organized under hidden `.curated` and `.system` scopes, so specify exact paths and `--allow-hidden-dirs` when needed. At `49f948faa9258a0c61caceaf225e179651397431`, the three relevant skills above were installed by exact path. Do not bulk-install unrelated catalog skills.

## Licensing

Retain upstream license and attribution requirements when redistributing vendored material. The OpenAI snapshots carry their per-skill Apache-2.0 `LICENSE.txt`; GitHub snapshots carry the collection's MIT `LICENSE.txt`. Preserve those files. Verify current terms before republishing these snapshots elsewhere.

## Live repository baseline (2026-09-25)

- `Spon4ik/qBittorrent-rss-rules` is public and uses `main` as default branch.
- GitHub reports no branch protection on `main` and no repository rulesets.
- Actions are enabled, all actions are allowed, SHA pinning is not required, and fork PR approval is required only for first-time contributors.
- No workflow files or recent Actions runs were found on the repository's default branch; therefore no required status-check names can currently be selected from observed evidence.
- The `Spon4ik-Labs` organization runner pool had `generic-01`, `generic-02` (label `generic`) and `browser-01` (label `browser`) online at audit time. Verify ownership, access and online state before relying on this snapshot.
- The reviewed runner-management source is [Spon4ik-Labs/ci-workflows](https://github.com/Spon4ik-Labs/ci-workflows), which documents organization versus repository runner scope and the pool's bootstrap, verification and concurrency-proof scripts.

This baseline is diagnostic context only, not enforcement. Re-query live settings before any change. The install task did not mutate branch protection, Actions settings, issues, milestones, organization configuration, or runners.

## Reinstall reviewed versions

Run from the repository root. `gh skill` writes into `.agents/skills/` and records source metadata. Review diffs and licenses after every install.

```powershell
gh skill install github/awesome-copilot github-issues --agent universal --scope project --pin 6c4d33b9cfca967a28bb2962ef4d55e4a384c88c
gh skill install github/awesome-copilot breakdown-plan --agent universal --scope project --pin 6c4d33b9cfca967a28bb2962ef4d55e4a384c88c
gh skill install github/awesome-copilot repo-standardizer --agent universal --scope project --pin 6c4d33b9cfca967a28bb2962ef4d55e4a384c88c
gh skill install github/awesome-copilot github-actions-hardening --agent universal --scope project --pin 6c4d33b9cfca967a28bb2962ef4d55e4a384c88c
gh skill install github/awesome-copilot github-actions-efficiency --agent universal --scope project --pin 6c4d33b9cfca967a28bb2962ef4d55e4a384c88c
gh skill install openai/skills skills/.curated/gh-fix-ci --agent universal --scope project --pin 49f948faa9258a0c61caceaf225e179651397431
gh skill install openai/skills skills/.curated/security-best-practices --agent universal --scope project --pin 49f948faa9258a0c61caceaf225e179651397431
gh skill install openai/skills skills/.system/skill-creator --allow-hidden-dirs --agent universal --scope project --pin 49f948faa9258a0c61caceaf225e179651397431
```

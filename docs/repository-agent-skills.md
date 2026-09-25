# Repository Agent Skills

This repository stores portable Agent Skills under `.agents/skills/`. GitHub Copilot also supports project skills under `.github/skills/`; the shared `.agents/skills/` location is chosen here so compatible agents can use the same source. Keep broadly applicable, always-on constraints in `AGENTS.md`; put task-specific procedures in skills.

## Installed skills

- `qb-repository-governance`: protected `main`, GitHub-native issue hierarchy/milestones/progress, CI/CD, runner safety and project maintenance. Composes the skills below.
- `qb-tdd`: deterministic regression-first implementation and validation.
- `qb-runner-operations`: self-hosted runner and workflow operations.
- `github-issues`, `breakdown-plan`, `repo-standardizer`, `github-actions-hardening`, `github-actions-efficiency`: source-pinned skills from GitHub's community-contributed `awesome-copilot` collection.
- `gh-fix-ci`, `security-best-practices`, `skill-creator`: source-pinned skills from OpenAI's curated/system catalog.

The source refs, per-skill provenance, license notes, and live GitHub baseline are recorded in `.agents/skills/UPSTREAM.md`. Main protection and runner configuration must be checked live; installing skills does not enable or enforce those controls.

## Updating

1. Inspect the source repository, exact skill files, scripts, license and current GitHub/Copilot documentation.
2. Choose an immutable tag or commit SHA. Preview and read the complete skill before installing.
3. Install one skill at a time into `.agents/skills/`, review the resulting diff, and update `.agents/skills/UPSTREAM.md` with source, ref and rationale.
4. Check the skill against `AGENTS.md`, current phase/status documents, and our protected-main/runner policies. Resolve conflicts in project-specific guidance; do not weaken project gates to match generic templates.
5. Validate `SKILL.md` frontmatter and references, then use `git diff --check`. Do not enable pre-approved shell tools for third-party skills.

Upstream content is a dependency: pin it, inspect it, preserve required attribution/licensing, and update deliberately. GitHub documents that skills are not verified by GitHub. See the [GitHub Copilot skill format and installation guide](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills) and [OpenAI skills catalog](https://github.com/openai/skills).

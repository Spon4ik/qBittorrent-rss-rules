---
name: versioning-manager
description: Manage software version lifecycle using Semantic Versioning with explicit bump decisions, cross-file version synchronization, and release-prep documentation updates. Use when Codex needs to choose or justify the next version number, apply version bumps across code/config/docs, audit version drift between files or tags, or prepare changelog/release notes before tagging.
---

# Versioning Manager

## Overview

Drive version changes from decision to release-ready verification.
Keep SemVer rationale explicit, update all version touchpoints consistently, and leave clear release handoff notes.

## Run Workflow

1. Build version context first.
- Locate authoritative and derived version fields with fast repo scans.
- Identify the current released tag and working version.
- Record current version, proposed target version, and assumptions.

2. Classify the bump.
- Use [references/semver-bump-rules.md](references/semver-bump-rules.md) to choose patch/minor/major.
- Treat API/schema/config/workflow breaks as major unless compatibility is fully preserved.
- Use prerelease labels only when explicitly requested.

3. Map touchpoints before editing.
- Use [references/version-touchpoints-checklist.md](references/version-touchpoints-checklist.md) to identify all files that must change (including WinUI `RequiredDesktopBackendAppVersion` and paired `/health` + Stremio manifest pytest asserts).
- Separate authoritative version sources from documentation mentions.
- Update planning/status docs first when release scope assumptions change.

4. Apply synchronized edits.
- Update authoritative version fields first, then docs and release notes.
- Keep formatting stable and avoid unrelated edits in the same slice.
- Document user-visible behavior changes and upgrade notes in changelog/release artifacts.

5. Verify before handoff.
- Re-scan for stale or mixed version strings.
- Run required quality checks for the release path.
- Summarize new version, touched files, validation evidence, and unresolved risks.

## Output Contract

- Provide current version, target version, bump rationale, and exact changed files.
- Call out blockers and follow-up tasks required before tagging.
- Prefer concrete commands and artifact paths over abstract guidance.

## Use References

- Use [references/semver-bump-rules.md](references/semver-bump-rules.md) for bump decisions and compatibility checks.
- Use [references/version-touchpoints-checklist.md](references/version-touchpoints-checklist.md) for update order and verification commands.

# Contributing

## Branch naming

Use short, explicit branch names:

- `feat/<short-topic>`
- `fix/<short-topic>`
- `docs/<short-topic>`
- `chore/<short-topic>`

## Commit style

Use small commits with imperative subjects. Example:

- `feat: add qBittorrent sync service`
- `fix: preserve manual regex override on save`
- `docs: update release checklist`

## Local development checks

Run before opening a PR:

```bash
ruff check .
mypy app
pytest
```

Or use:

```bash
./scripts/check.sh
```

Pytest removes inherited `QB_RULES_*` configuration before importing the app,
uses a per-test temporary SQLite database by default, and rejects file-backed
SQLite URLs outside the operating-system temporary directory before opening
them. Tests that launch app processes must pass an explicit temporary database
URL and stub provider endpoints; browser QA keeps reports/logs as artifacts but
removes its temporary database after the process exits. Add regressions for
these boundaries before changing their behavior.

## Pull request checklist

- Link one primary issue and map its acceptance criteria to observable evidence.
- Keep issue, parent, and child scope distinct; do not count a parent and its
  deliverable children as separate completed work for one milestone.
- Record focused regression evidence, affected checks, and deployment/release
  evidence when those are part of the issue's acceptance criteria.
- The code is typed and lint-clean.
- Tests cover the changed behavior.
- Docs and roadmap are updated if behavior changed.
- New architecture decisions include a new or updated ADR.
- User-facing errors remain actionable.

## ADR workflow

Add a new file under `docs/adr/` when a change affects architecture, data flow, storage, security posture, or external integrations. Use the existing ADR structure:

- Context
- Decision
- Consequences
- Alternatives considered

## Definition of done

A change is complete only when:

- implementation is finished
- lint, typing, and tests pass
- docs reflect the actual behavior
- roadmap status is current
- any material architecture decision is recorded


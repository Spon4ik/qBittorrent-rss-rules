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

## Pull request checklist

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


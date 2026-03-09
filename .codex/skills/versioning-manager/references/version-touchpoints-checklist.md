# Version Touchpoints Checklist

## Authoritative Version Sources

- `pyproject.toml` (`[project].version`)
- Runtime constants (`__version__`, API version fields) when present

## Derived Mentions

- `CHANGELOG.md` release heading and notes
- `ROADMAP.md` current/next release target lines
- `README.md` and docs that mention pinned release numbers
- Release docs under `docs/` (upgrade notes, release process references)

## Update Sequence

1. Decide target version and record bump rationale.
2. Update authoritative version fields first.
3. Update changelog and release/upgrade notes.
4. Update roadmap and planning docs if release scope or ordering changed.
5. Re-scan and verify all version mentions are consistent.

## Verification Commands

```bash
rg -n "version\\s*=|__version__|v[0-9]+\\.[0-9]+\\.[0-9]+" pyproject.toml README.md CHANGELOG.md ROADMAP.md docs app
git diff --stat
git diff
```

## Repo-Local Reminder

- Keep `docs/plans/current-status.md` and the active phase plan aligned when version planning changes release assumptions.
- Update `ROADMAP.md` only when phase ordering or long-term direction changes.

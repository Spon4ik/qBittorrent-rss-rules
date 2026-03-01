# Releases

## Versioning policy

The project follows Semantic Versioning:

- patch: fixes and internal improvements
- minor: backward-compatible features
- major: breaking API, schema, or workflow changes

## Release process

1. Update `CHANGELOG.md`
2. Confirm `ROADMAP.md` status reflects the current release
3. Run:
   - `ruff check .`
   - `mypy app`
   - `pytest`
4. Perform manual QA against a real local qBittorrent instance
5. Tag the release
6. Document known limitations and upgrade notes

## Upgrade notes

- Record schema changes in release notes
- Include any new environment variables
- Note any changed sync behavior or route additions

## Rollback expectations

- Keep a backup copy of the SQLite DB before upgrading across schema changes
- If a release causes sync regressions, stop the app and restore the prior DB backup
- qBittorrent remote rules can be rebuilt from the local DB via sync once the app is healthy again


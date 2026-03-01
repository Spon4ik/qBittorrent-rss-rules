# Roadmap

## Current release target: v0.1.0

### In progress

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Rule form with metadata lookup, grouped quality filters, and reusable saved filter profiles
- Baseline docs, ADRs, and test suite

### Release focus

- Keep the first release localhost-only
- Keep the data model stable and explicit
- Avoid undocumented qBittorrent rule fields
- Prefer correctness and maintainability over broad feature count

## Next release: v0.2.x

- Bulk rule creation from list or CSV
- Rule clone/duplicate flows
- Improved feed grouping UX
- Dry-run sync preview
- Manual drift resolution UX
- Rule export back to normalized JSON
- Basic DB backup and restore
- Better category template editor

## Future / North Star

- Rule templates and preset libraries
- Metadata providers beyond OMDb
- Sample feed simulation before save
- Desktop packaging for Windows
- Optional LAN-safe auth
- Background health checks
- Snapshot rollback
- Browser automation tests
- Release automation and compatibility matrix

## Explicit non-goals for v0.1.0

- Multi-user access
- Cloud deployment
- Remote hosting defaults
- Background workers
- Advanced auth and RBAC
- Raw qBittorrent JSON editing UI

## Deferred items

- Strong secret storage: deferred until a concrete platform-specific strategy is selected
- Automatic drift healing: deferred to avoid surprising overwrites in early releases
- Additional metadata providers: deferred until the base sync workflow is stable

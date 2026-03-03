# Roadmap

## Current release target: v0.1.0

### In progress

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Phase 1-5 work is already implemented in the current branch; remaining work is full test and manual validation
- Baseline docs, ADRs, and test suite

### Current phase track

- Phase 1: JSON-backed quality taxonomy loader (implemented, awaiting final validation)
- Phase 2: richer taxonomy schema (implemented, awaiting final validation)
- Phase 3: taxonomy management UI (implemented, awaiting final validation)
- Phase 4: feed selection UX improvements (implemented, awaiting final validation)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, awaiting final validation)

### Release focus

- Keep the first release localhost-only
- Close phase 4 and phase 5 validation before widening scope
- Keep the data model stable and explicit
- Avoid undocumented qBittorrent rule fields
- Prefer correctness and maintainability over broad feature count

## Next release: v0.2.x

- Phase 6: Jackett-powered active search workspace with advanced query expansion and search-to-rule handoff
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

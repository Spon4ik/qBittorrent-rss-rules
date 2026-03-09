# Roadmap

## Current release target: v0.2.0

### In progress

- Phase 6: Jackett-powered active search hardening and follow-up UX validation
- Phase 4 and Phase 5 manual browser validation closeout
- Release-process polish and release automation improvements

### Current phase track

- Phase 6: Jackett-backed active search workspace (initial implementation complete, follow-up validation/polish in progress)
- Phase 4: feed selection UX improvements (implemented, closeout validation pending)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, closeout validation pending)

### Release focus

- Keep localhost-only defaults while phase-6 workflows mature
- Close remaining phase 4 and phase 5 validation before broadening scope
- Keep Jackett active search explicitly separate from persistent RSS feed rule sources
- Keep the data model stable and explicit
- Avoid undocumented qBittorrent rule fields
- Prefer correctness and maintainability over broad feature count

## Recently released: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.2.x

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

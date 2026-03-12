# Roadmap

## Current release target: v0.3.0

### In progress

- Phase 7: cached-refinement responsiveness and category-catalog integrity for `/search`
- Release closeout automation adoption and evidence-driven phase sign-off
- Release-process polish and release automation improvements

### Current phase track

- Phase 7: cached-refinement responsiveness and category-catalog integrity (`docs/plans/phase-7-cached-refinement-and-category-catalog.md`)
- Phase 6: Jackett-backed active search workspace (implemented and release-validated in v0.2.0; follow-up polish completed, deeper persistence still deferred)
- Phase 4: feed selection UX improvements (implemented, automated closeout validated)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, automated closeout validated)

Phase 7 detail pointer:
- Detailed checklist and dated execution tracker for immediate cached filtering responsiveness and normalized category mapping is tracked in `docs/plans/phase-7-cached-refinement-and-category-catalog.md` under `Dated execution checklist (2026-03-12 baseline)`.

Phase 6 detail pointer:
- Detailed checklist and dated execution tracker for the latest search/rules UX hardening request is tracked in `docs/plans/phase-6-jackett-active-search.md` under `Request Checklist` and `Dated execution checklist (2026-03-10 baseline)`.

### Release focus

- Keep localhost-only defaults while phase-7 workflows mature
- Keep phase-4/phase-5 closeout green via deterministic browser QA automation
- Keep Jackett active search explicitly separate from persistent RSS feed rule sources
- Keep category-label mapping deterministic via indexer-scoped normalization
- Keep the data model stable and explicit
- Avoid undocumented qBittorrent rule fields
- Prefer correctness and maintainability over broad feature count

## Recently released: v0.2.0 (2026-03-11)

- Phase-6 Jackett active search shipped with IMDb-first and title-fallback split workflows
- `/search` UX density pass shipped (wider layout, compact criteria/filter-impact composition, refined result-view controls)
- Deterministic browser closeout automation + optional live-provider smoke evidence adopted for release gating
- WSL qBittorrent localhost rewrite shipped for mixed Windows/WSL topology

## Previously released: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.3.x

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
- Expanded browser automation coverage (live-provider smoke + CI gating)
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

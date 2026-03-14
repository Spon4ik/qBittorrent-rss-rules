# Roadmap

## Current release target: v0.4.0

### In progress

- Phase-8 persistent rule-search snapshots and unified rule/search results workspace
- Rule-page UX modernization for compact criteria + result operations with minimal scrolling

### Current phase track

- Phase 8: persistent rule-search snapshots and unified results workspace UX (active; tracked in `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md`)
- Phase 7: cached-refinement responsiveness and category-catalog integrity (implemented and release-validated in v0.3.0; follow-up polish folded into phase-8 workspace scope)
- Phase 6: Jackett-backed active search workspace (implemented and release-validated in v0.2.0; follow-up polish completed, deeper persistence still deferred)
- Phase 4: feed selection UX improvements (implemented, automated closeout validated)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, automated closeout validated)

Phase 8 detail pointer:
- Detailed checklist and dated execution tracker for persistent per-rule snapshots, unified IMDb-first/title-fallback results, and compact rule-page UX is tracked in `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md` under `Dated execution checklist (2026-03-14 baseline)`.

Phase 7 detail pointer:
- Detailed checklist and dated execution tracker for immediate cached filtering responsiveness and normalized category mapping is tracked in `docs/plans/phase-7-cached-refinement-and-category-catalog.md` under `Dated execution checklist (2026-03-12 baseline)`.

Phase 6 detail pointer:
- Detailed checklist and dated execution tracker for the latest search/rules UX hardening request is tracked in `docs/plans/phase-6-jackett-active-search.md` under `Request Checklist` and `Dated execution checklist (2026-03-10 baseline)`.

### Release focus

- Persist one refreshable search-result snapshot per rule so local refinement is reusable across sessions.
- Redesign rule-page information architecture to keep search criteria, local filters, and results in the same visible workspace with less scrolling.
- Unify `IMDb-first` and `Title fallback` rows in one table and add a query-source key per row.
- Retire the standalone filter-impact panel in the unified-table flow, so `0 fetched / 0 filtered` states show only clean empty-state context.
- Use an interactive sortable table: clicking/tapping column titles toggles `A-Z` / `Z-A` (or low-high / high-low) and supports compact multi-level sort.
- Compact queue-to-qB actions into a smaller high-signal toolbar while preserving advanced options.
- Keep deterministic browser QA and route/service regressions as release gates for every UX contract change.
- Keep the data model explicit and maintainable; avoid undocumented qBittorrent rule fields.

## Recently released: v0.3.0 (2026-03-13)

- Phase-7 cached-refinement/category-catalog slice shipped, including persisted indexer category mapping and scoped category option diagnostics.
- Saved-rule `Run Search` now renders inline rule-page results with feed-aware scope handling, queue actions, and table-first sort/view parity.
- Rule model and generated-pattern behavior now include episode-progress floor fields plus stricter grouped quality include semantics.
- Deterministic browser closeout automation now covers phase-7 inline local recompute, queue paused semantics, table/sort parity, and stale-category scope warnings.

## Previously released: v0.2.0 (2026-03-11)

- Phase-6 Jackett active search shipped with IMDb-first and title-fallback split workflows
- `/search` UX density pass shipped (wider layout, compact criteria/filter-impact composition, refined result-view controls)
- Deterministic browser closeout automation + optional live-provider smoke evidence adopted for release gating
- WSL qBittorrent localhost rewrite shipped for mixed Windows/WSL topology

## Earlier release: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.4.x

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

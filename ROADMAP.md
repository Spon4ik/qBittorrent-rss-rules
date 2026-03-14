# Roadmap

## Current release target: v0.5.0

### In progress

- Phase-9 rules main-page release-aware operations and Jackett fetch orchestration
- Main-page UX pass: table-first rules workspace with richer visual context and lower scrolling overhead

### Current phase track

- Phase 9: rules main-page release-aware operations + Jackett fetch orchestration (active; tracked in `docs/plans/phase-9-rules-main-page-release-ops.md`)
- Phase 8: persistent rule-search snapshots and unified results workspace UX (implemented and release-validated in v0.4.0)
- Phase 7: cached-refinement responsiveness and category-catalog integrity (implemented and release-validated in v0.3.0)
- Phase 6: Jackett-backed active search workspace (implemented and release-validated in v0.2.0; follow-up polish completed, deeper persistence still deferred)
- Phase 4: feed selection UX improvements (implemented, automated closeout validated)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, automated closeout validated)

Phase 9 detail pointer:
- Detailed checklist and dated execution tracker for the table-first rules page UX, poster hover/cards behavior, on-demand/scheduled Jackett rule fetch orchestration, and rule sorting by post-filter release availability is tracked in `docs/plans/phase-9-rules-main-page-release-ops.md`.

Phase 8 detail pointer:
- Detailed checklist and dated execution tracker for persistent per-rule snapshots, unified IMDb-first/title-fallback results, and compact rule-page UX is tracked in `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md` under `Dated execution checklist (2026-03-14 baseline)`.

Phase 7 detail pointer:
- Detailed checklist and dated execution tracker for immediate cached filtering responsiveness and normalized category mapping is tracked in `docs/plans/phase-7-cached-refinement-and-category-catalog.md` under `Dated execution checklist (2026-03-12 baseline)`.

Phase 6 detail pointer:
- Detailed checklist and dated execution tracker for the latest search/rules UX hardening request is tracked in `docs/plans/phase-6-jackett-active-search.md` under `Request Checklist` and `Dated execution checklist (2026-03-10 baseline)`.

### Release focus

- Make the rules main page table-first by default, with poster preview on row hover and visible poster media when cards mode is explicitly selected.
- Add on-demand Jackett fetch orchestration for either all rules or selected rules from the main page.
- Add scheduled Jackett fetch orchestration with clear cadence controls and deterministic status feedback.
- Add rule sorting by release availability outcome after all rule filters apply (for example new movie release found, new episode found, no match).
- Keep deterministic browser QA and route/service regressions as release gates for every workflow change.
- Preserve data-model clarity and explicit sync contracts while adding schedule execution state.

## Recently released: v0.4.0 (2026-03-15)

- Phase-8 persistent per-rule snapshot workflow shipped, including centralized replay/refresh behavior for inline rule results.
- Unified IMDb-first/title-fallback rendering shipped as a single source-keyed table with compact empty-state diagnostics and no standalone filter-impact panel.
- Rule-page workspace modernization shipped (sticky split rail/results layout, header-driven sorting, compact queue controls, and active local-filter chips).
- Inline affected-feed scope now applies both to rule RSS listener configuration and immediate indexer visibility in cached unified results.

## Previously released: v0.3.0 (2026-03-13)

- Phase-7 cached-refinement/category-catalog slice shipped, including persisted indexer category mapping and scoped category option diagnostics.
- Saved-rule `Run Search` now renders inline rule-page results with feed-aware scope handling, queue actions, and table-first sort/view parity.
- Rule model and generated-pattern behavior now include episode-progress floor fields plus stricter grouped quality include semantics.
- Deterministic browser closeout automation now covers phase-7 inline local recompute, queue paused semantics, table/sort parity, and stale-category scope warnings.

## Earlier release: v0.2.0 (2026-03-11)

- Phase-6 Jackett active search shipped with IMDb-first and title-fallback split workflows
- `/search` UX density pass shipped (wider layout, compact criteria/filter-impact composition, refined result-view controls)
- Deterministic browser closeout automation + optional live-provider smoke evidence adopted for release gating
- WSL qBittorrent localhost rewrite shipped for mixed Windows/WSL topology

## Initial release: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.5.x

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

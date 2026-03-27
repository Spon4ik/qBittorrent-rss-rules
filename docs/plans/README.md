# Implementation Plans

This directory tracks implementation-ready work and the current execution state for active phases.

Primary documents:

- `docs/plans/current-status.md`: live resumability snapshot and next actions
- `docs/plans/phase-1-json-taxonomy-loader.md`: completed phase 1 compatibility plan
- `docs/plans/phase-2-rich-taxonomy-schema.md`: implemented phase 2 schema expansion plan pending full-environment validation
- `docs/plans/phase-3-taxonomy-management-ui.md`: implemented phase 3 taxonomy management UI plan pending full-environment validation
- `docs/plans/phase-4-feed-selection-ux.md`: implemented phase 4 feed selection UX plan pending final validation
- `docs/plans/phase-5-media-aware-rule-form-and-metadata.md`: implemented phase 5 validation and closeout plan
- `docs/plans/phase-6-jackett-active-search.md`: implemented phase 6 Jackett active-search plan with deferred follow-up decisions
- `docs/plans/phase-7-cached-refinement-and-category-catalog.md`: implemented phase 7 cached-refinement and category-catalog integrity plan
- `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md`: implemented phase 8 persistent per-rule snapshot and unified rule/results workspace UX plan
- `docs/plans/phase-9-rules-main-page-release-ops.md`: implemented phase 9 rules main-page release-operations UX, poster presentation, and Jackett run orchestration plan
- `docs/plans/phase-10-winui-desktop-bootstrap.md`: implemented and release-validated phase 10 WinUI desktop bootstrap baseline (`v0.6.0`), with follow-up now shipped in phase 11
- `docs/plans/phase-11-v0-6-1-stabilization-and-desktop-hardening.md`: implemented and release-validated `v0.6.1` stabilization plan covering desktop single-instance behavior, poster request-path hardening, Windows packaging/install flow, and Jellyfin read-only sync
- `docs/plans/phase-12-v0-7-0-catalog-aware-jellyfin-and-missing-only-queue.md`: implemented and release-validated `v0.7.0` plan covering catalog-aware Jellyfin season boundaries, retained skip memory after local file cleanup, episode-`0` floors, and rule-backed qB missing/unseen file selection
- `docs/plans/phase-13-v0-7-1-desktop-freshness-and-engine-shutdown.md`: implemented and release-validated `v0.7.1` patch plan covering WinUI desktop freshness parity with the browser, fail-closed backend refresh behavior, and explicit in-app managed-backend shutdown/exit controls
- `docs/plans/phase-14-v0-7-2-template-warning-cleanup-and-release-push.md`: implemented and release-validated `v0.7.2` patch plan covering Starlette template deprecation cleanup, release-gate revalidation, and remote push publication
- `docs/plans/phase-15-repo-local-backend-startup-portability.md`: implemented and manually validated maintenance plan covering project-scope docs cleanup plus repo-local backend startup portability after copied `.venv` breakage
- `docs/plans/phase-16-desktop-build-portability-and-nuget-source-cleanup.md`: implemented and release-validated maintenance plan covering removal of the machine-specific offline NuGet source and desktop build portability revalidation
- `docs/plans/phase-17-shared-watch-state-arbitration-foundation.md`: implemented and release-validated foundation plan covering source-agnostic watched-state decisions and the later Stremio split

`ROADMAP.md` remains the high-level product roadmap. The files in `docs/plans/` are the detailed source of truth for work that is actively being implemented or prepared. Phases 5 through 16 are implemented, Phase 17 is release-validated in `v0.7.4`, and the next active phase should be opened before the next code change.

# Phase 25: Stremio Add-on Removal And Sync Retention

## Status

- Plan created on 2026-04-19 after the product decision to split qBittorrent RSS Rules from the Stremio add-on and use `jackett-stremio-fork` as the separate addon host.
- Phase 25 implementation landed locally on 2026-04-19:
  - removed the native Stremio addon router/service/local-playback stack from the qB RSS Rules backend;
  - removed addon-only settings, queue APIs, frontend controls, smoke scripts, and release-version touchpoints;
  - kept Stremio library/watch-progress synchronization, auto-sync scheduling, and settings test/sync flows intact;
  - kept the old DB columns for provider manifests/preferred languages as compatibility debt to avoid bundling a destructive schema migration into the boundary split.
- Real-world validation is complete on 2026-04-19; release publication is the remaining closeout step.

## Goal

Make qBittorrent RSS Rules a qB + sync app again: no native Stremio addon hosting, no addon queue bridge, and no addon-provider configuration, while retaining Stremio library/watch-progress sync as the only Stremio-facing feature set.

## Context

- The user has decided to run Stremio addon behavior from a separate project (`jackett-stremio-fork`) instead of this repository.
- Keeping both addon hosting and Stremio sync in qB RSS Rules creates overlapping responsibility, extra maintenance cost, and misleading roadmap direction.
- The sync path still belongs here because it feeds watched/library state back into rule progression and queue decisions.

## Requested Scope (2026-04-19)

1. Record the split in the roadmap and active phase docs.
2. Remove the native Stremio addon routes/services/UI/settings from qB RSS Rules.
3. Keep Stremio library sync and watch-progress sync operational.
4. Validate the resulting app in real local runs, not only unit tests.
5. Cut and publish a release version for the boundary change.

## In Scope

- Remove `/stremio/*` addon endpoints and addon CORS behavior.
- Remove addon-enriched desktop/search baselines and addon queue bridges.
- Remove addon-only settings fields and settings-page copy.
- Remove addon/local-playback helper modules, addon smoke scripts, and addon-only regression files.
- Keep `/api/settings/test-stremio`, `/api/settings/sync-stremio`, and the Stremio auto-sync scheduler.
- Update versioning/release tooling, docs, and release notes for the split.

## Out Of Scope

- Database cleanup migrations for the legacy addon-only columns.
- Replacing the external addon project or importing its code here.
- Broad refactors unrelated to the boundary split.

## Key Decisions

### Decision: retain sync but remove addon hosting

- Date: 2026-04-19
- Context: the product boundary changed, but rule progression still depends on Stremio watch/library state.
- Chosen option: keep sync-only Stremio flows in this repo and remove the addon host/queue/provider surfaces.
- Reasoning: this matches the new ownership boundary while preserving the Stremio-derived state the qB rule engine still uses.
- Consequences: qB RSS Rules no longer advertises addon capabilities, and future Stremio work here should be limited to sync/state integration unless the roadmap changes again.

### Decision: defer schema cleanup

- Date: 2026-04-19
- Context: removing addon-only DB columns in the same release would couple a product-boundary change with a data migration.
- Chosen option: leave the legacy columns in place for now and remove only the live product surface.
- Reasoning: the lowest-risk release is to make the code/UI stop using the fields first, then handle migration debt separately if it becomes worthwhile.
- Consequences: `AppSettings` and the DB schema still carry unused addon-era columns temporarily.

## Acceptance Criteria

- `/stremio/manifest.json` and the rest of the native addon surface are no longer served by qB RSS Rules.
- `/search` and rule-page flows no longer use addon-baseline enrichment or expose “Queue Stremio Variant”.
- `/settings` exposes Stremio sync controls only, not addon manifest/provider/preferred-language controls.
- Stremio test/sync actions still work against a real local Stremio setup.
- Desktop/backend capabilities no longer advertise `stremio_native_addon`.
- Focused regression coverage passes, and live local validation confirms the split on the running app.

## Dated Execution Checklist (2026-04-19 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P25-01 | Update roadmap and phase docs for the repo split. | Codex | 2026-04-19 | completed | Roadmap/current-status/phase docs state that addon hosting moved out of this repo and sync remains. | This phase plan plus 2026-04-19 roadmap/current-status updates. |
| P25-02 | Remove native addon codepaths while keeping Stremio sync intact. | Codex | 2026-04-19 | completed | Native addon routes/services/UI/settings/scripts/tests are gone, and the backend/desktop capability contract reflects sync-only Stremio support. | 2026-04-19 changes in `app/main.py`, `app/routes/pages.py`, `app/routes/api.py`, `app/services/selective_queue.py`, `app/services/settings_service.py`, `app/static/app.js`, templates, desktop contract constants, deleted addon modules/scripts/tests, and focused green pytest/ruff runs. |
| P25-03 | Validate the split in the real local environment. | Codex | 2026-04-19 | completed | Running backend/desktop proves addon endpoints are gone while Stremio sync flows still work. | 2026-04-19 live checks on backend `1.0.0`: `/stremio/manifest.json` returned `404`; `/settings` and `/search` no longer exposed addon/provider/variant-queue UI; `/api/settings/test-stremio` succeeded against the local Stremio WebView storage; `/api/settings/sync-stremio` completed for `147 active title(s)`; `scripts\\check.bat` passed (`308 passed`); and `scripts\\run_dev.bat desktop-build` succeeded with `0 Warning(s)` / `0 Error(s)`. |
| P25-04 | Cut and publish the breaking-change release. | Codex | 2026-04-19 | in progress | Version is bumped consistently, changelog/docs are updated, and the release commit/tag are published to git. | Pending release closeout. |

## Risks And Follow-Up

### Risk: stale docs or release scripts could still imply addon ownership

- Trigger: old docs/tests/scripts still refer to addon manifests or addon smoke gates.
- Impact: future work could accidentally restore or depend on removed surfaces.
- Mitigation: remove addon touchpoints from release/version tooling now and follow with README/docs cleanup in this release.
- Owner: Codex
- Status: active

### Risk: leftover schema fields may confuse future maintenance

- Trigger: the DB and ORM still contain addon-era columns that are no longer used.
- Impact: future engineers may assume those settings are still live.
- Mitigation: document them as deferred cleanup debt and keep them out of all active UI/API paths.
- Owner: Codex
- Status: accepted

## Next Concrete Steps

1. Run the live backend/desktop validation pass against the actual local app and Stremio data.
2. Bump the release to the next major semver because native addon hosting/configuration was removed.
3. Publish the release commit and tag after the real-world checks pass.

# Phase 25: Stremio Add-on Removal And Sync Retention

## Status

- Plan created on 2026-04-19 after the product decision to split qBittorrent RSS Rules from the Stremio add-on and use `jackett-stremio-fork` as the separate addon host.
- Phase 25 implementation landed locally on 2026-04-19:
  - removed the native Stremio addon router/service/local-playback stack from the qB RSS Rules backend;
  - removed addon-only settings, queue APIs, frontend controls, smoke scripts, and release-version touchpoints;
  - kept Stremio library/watch-progress synchronization, auto-sync scheduling, and settings test/sync flows intact;
  - kept the old DB columns for provider manifests/preferred languages as compatibility debt to avoid bundling a destructive schema migration into the boundary split.
- Parallel qB-only follow-up work landed locally on 2026-04-20 without changing the Stremio split scope:
  - rules now expose a language selector that resolves matching Jackett-backed qB RSS feeds under the hood, while the old manual affected-feed checklist remains visible for this release as a compatibility fallback;
  - real local Jackett/qB validation on this machine proved the current configured language groups are `ru` and `he`, and the rule-form browser capture verified the language-managed feed UX on `/rules/new`.
- A qB-only follow-up hardening patch landed locally on 2026-04-22 without changing the Stremio split scope:
  - saved-rule active search now keeps the original Jackett-first product boundary when qB RSS feeds are unavailable by falling back from feed-derived scope to Jackett configured-indexer language scope, instead of treating missing live qB feeds as a blocker for language-managed rule search;
  - focused route regressions now lock both feed-derived scope precedence and the language-to-Jackett-indexer fallback path for inline rule search and the `/search?rule_id=...` workspace flow.
- A second qB-only hardening patch landed locally on 2026-04-22 without changing the Stremio split scope:
  - qB RSS feed availability is now treated as the passive rule-subscription module only, so language-managed rule creates/updates no longer fail just because qB is offline or its RSS feed list cannot be read at save time;
  - same-language edits preserve the previously resolved passive feed URLs when qB feeds are temporarily unavailable, while language changes save the new language intent without reusing stale feed URLs from the old language;
  - the rule form now keeps saved feed URLs visible during qB feed outages and shows the existing helper-text warning instead of silently blanking the affected-feed list.
- A focused rules-page sync-error UX patch landed locally on 2026-04-23 without changing phase scope:
  - rules with qB sync failures now display the stored `last_sync_error` inline in both table and card views, making `sync=error` inspection actionable without opening each rule or retrying sync blindly;
  - focused verification is green with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "rules_page" -q` and `.\\.venv\\Scripts\\python.exe -m ruff check tests\\test_routes.py`.
- A qB-only saved-search filter hardening patch landed locally on 2026-04-24 without changing the Stremio split scope:
  - same-season rows that are clearly marked as complete/full season packs now remain visible in saved-rule local filtering when the rule is in `jellyfin_search_existing_unseen` mode, even if the explicit episode range ends below the synced watched floor;
  - the backend-side release-filter cache and the browser-side hidden-row diagnostic now share that exception so relevant upgrade candidates are no longer mislabeled as `Does not match the generated rule pattern.`;
  - active Jackett searches for keep-searching series rules now derive the primary structured season/episode from watched progress instead of the stored known-episode floor, so the live `The Miniature Wife` rule builds primary requests around `S01E02` rather than `S01E11` and can admit full `S1E1-10` packs into the exact lane when Jackett returns them there;
  - focused verification is green with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_rule_fetch_ops.py -k "complete_pack_when_keep_searching_enabled or zero_based_ranges_below_episode_floor" -q`, `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "inline_local_generated_pattern" -q`, `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_rule_builder.py -k "zero_based_ranges or keep_searching_existing_unseen" -q`, `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_jackett.py -k "watched_progress_for_keep_searching_existing or carries_series_episode_floor" -q`, `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "rule_search or inline_search or jackett_search_api or transform" -q`, and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\jackett.py tests\\test_jackett.py`.
- Real-world validation is complete on 2026-04-19, and the local release train is now version-synced to `1.1.0`; git publication is the remaining closeout step.

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
4. Publish the now-combined `1.1.0` release train after the Stremio split plus qB rule-language follow-up local validations.
5. Decide whether the passive qB feed-resolution state now needs its own persisted warning/status field before the next rules UX cleanup slice.
6. Decide whether the keep-searching watched-progress search floor should remain active-search-only or also influence generated qB RSS rules later.

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
- A release-blocking patch landed locally on 2026-04-29 without changing the Stremio split scope:
  - Stremio sync now retries older discovered local auth keys when the newest LevelDB key fails with `Session does not exist`, and the auth-key extractor no longer captures punctuation instead of the real key;
  - quality/source filters now use release-token boundaries across backend and browser-side filtering so titles such as `Camelot` and `The Secrets` do not accidentally satisfy or trip `cam`/`ts` tags;
  - the language-managed feed edit page again shows the qB-feeds-unavailable warning while preserving saved feed URLs for visibility;
  - focused regressions were added in `tests/test_stremio.py`, `tests/test_quality_filters.py`, and `tests/test_routes.py`, and the release train is now version-synced to `1.1.1`.
- Real-world validation is complete on 2026-04-29 for the `1.1.1` candidate: live `/health` reports `app_version=1.1.1`, the local Stremio desktop storage test found `159 active` movie/series items out of `262` total, the real sync pass completed with `0 errors`, `cmd /c scripts\\check.bat` passed with `329 passed`, and `cmd /c scripts\\run_dev.bat desktop-build` succeeded with `0 Warning(s)` / `0 Error(s)` after stopping a stale desktop process.
- Docker backend support landed locally on 2026-04-30 without changing the Stremio split scope:
  - added a backend `Dockerfile`, `.dockerignore`, and a `qb-rss-rules` service in `C:\\Users\\nucc\\docker-config\\docker-compose.yml` so the FastAPI app can run in the shared Docker stack with SQLite persisted at `/app/data`;
  - documented host-service URL handling for qBittorrent/Jackett via `host.docker.internal` and the WinUI `QB_RSS_DESKTOP_URL` override for using a containerized backend;
  - updated `AGENTS.md` so future code-editing sessions must refresh the shared Docker `qb-rss-rules` service with the real Docker CLI path (`C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe`) and verify `/health` before closeout, or document any Docker blocker;
  - focused backend health-route verification is green with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k health_endpoint -q`;
  - real container smoke is now green after bypassing the broken zero-byte `C:\\Windows\\System32\\docker` shim: `qb-rss-rules` is running through the shared Compose file and `http://127.0.0.1:8000/health` reports `app_version=1.1.1`.
- Docker DB restore landed locally on 2026-04-30 after the project moved to `D:\\GitHub\\qBittorrent rss rules`:
  - the app now resolves relative SQLite URLs from `app.config.ROOT_DIR` so local launches keep using the repo `data\\qb_rules.db` regardless of process working directory;
  - the shared Docker `qb-rss-rules` service now bind-mounts `D:\\GitHub\\qBittorrent rss rules\\data` to `/app/data` instead of using an empty named volume;
  - live Docker proof shows the container is healthy and the mounted DB contains `190` rules.
- Docker host-path sync hardening landed locally on 2026-04-30:
  - Stremio and Jellyfin local file paths now use a shared resolver that maps saved Windows paths into the container under `/host/C/...`;
  - the shared Docker service now mounts `C:\\Users` and `C:\\ProgramData` read-only so saved Stremio LevelDB and Jellyfin DB paths remain usable from Docker;
  - live Docker proof shows Stremio sync completes for `159 active title(s)` with `0 errors`, and Jellyfin DB connection resolves to `/host/C/ProgramData/Jellyfin/Server/data/jellyfin.db`.
- qB RSS quality/feed reconciliation hardening landed locally on 2026-05-01 without changing the Stremio split scope:
  - selected quality profiles now drive qB RSS rule regexes, Jackett search payloads, and local result filtering even when per-rule token lists are empty, fixing the low-quality-result leak for `Ultra HD HDR`;
  - the Russian language default and passive RSS feed scope now come from Jackett configured indexers rather than qB's existing subscription list, and full sync reconciles qB RSS feeds to Jackett additions/removals;
  - app startup now attempts a guarded full qB sync when qB is configured so rule/feed updates are pushed after Docker/app restarts;
  - focused lint/tests are green, but Docker closeout is blocked because the shared Compose rebuild and Docker CLI status commands timed out on this machine and `/health` was unreachable after the attempts.
- A follow-up Jackett scope UX patch landed locally on 2026-05-01 without changing the Stremio split scope:
  - the rule language control is now a multi-select checkbox dropdown backed by distinct language metadata from configured Jackett indexers;
  - rules can persist multiple languages as one comma-separated scope, and feed resolution / active-search fallback use the union of matching Jackett indexers;
  - affected-feed options and `/api/feeds/refresh` now render Jackett configured indexers only instead of mixing qB RSS feed names, `Jackett/...` subscriptions, and unresolved saved-feed pseudo-options;
  - focused validation is green for `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "multiple_languages or language or feed_urls or feeds_refresh or quality_profile" -q`, `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_sync_service.py tests\\test_jackett.py -k "language or feed or quality" -q`, `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\jackett.py app\\routes\\pages.py app\\routes\\api.py app\\services\\sync.py app\\schemas.py`, and `node --check app\\static\\app.js`;
  - Docker closeout remains blocked after relaunching Docker Desktop because `docker ps` returns `500 Internal Server Error` from `dockerDesktopLinuxEngine` and `com.docker.service` cannot be started from this non-elevated session.
- Docker closeout completed after the PC restart on 2026-05-01:
  - the shared Compose rebuild succeeded and recreated `qb-rss-rules` with the current frontend asset version;
  - Docker validation exposed a startup regression where synchronous startup `SyncService.sync_all()` could block Uvicorn before `/health` was available, so startup sync now runs in a daemon background thread;
  - `tests/test_main.py::test_startup_rule_sync_does_not_block_app_startup` covers that regression and focused pytest/ruff checks are green;
  - live container proof shows `/health` is OK, the Docker DB has `197` rules, Jackett reports `he:1` and `ru:11` configured language groups with `12` feed URLs, and qBittorrent `v5.1.4` has `197` RSS rules plus exactly `12` `Jackett/...` RSS feeds after syncing the one stale error rule left from the period when qB was not running after reboot.
- A manual Jackett language override patch landed locally on 2026-05-02 without changing the Stremio split scope:
  - `/settings`, `QB_RULES_JACKETT_LANGUAGE_OVERRIDES`, and `JackettClient(..., language_overrides=...)` can now assign languages to configured indexers whose Jackett metadata is missing or wrong, such as mapping a metadata-less `noname-clubl` entry to `ru`;
  - saved override syntax uses one `indexer=lang[,lang]` mapping per line, env override syntax also supports JSON (`{"noname-clubl":["ru"]}`) and semicolon assignments (`noname-clubl=ru;thepiratebay=en,multi`), and the shared Compose service passes the env variable into the container;
  - configured-indexer language options, language-managed passive feed resolution, and active-search language scope all consume the override after live Jackett discovery, so adding/removing indexers still flows from Jackett;
  - `/taxonomy` now has structured add/remove/move controls for common value edits, numeric resolution values are inserted in numeric order, moving values updates both group order and rank order, and taxonomy updates write to runtime `data/quality_taxonomy.json` seeded from `app/data/quality_taxonomy.json`, protecting user-managed taxonomy and preset choices from ordinary source edits;
  - the structured taxonomy editor UI was tightened after screenshot review with compact rows, non-overlapping label/key columns, and small `⇧`/`⇩`/`×` icon buttons instead of large action buttons;
  - the local runtime taxonomy was repaired so the existing `400p` Resolution value is ordered between `360p` and `480p` and appears in the `resolution` rank list;
  - focused pytest/ruff/node checks are green, and the shared Compose rebuild plus `/health` proof succeeded with `app_version=1.1.1` and static asset version `1777754308000000000-1777659946000000000`.
- A taxonomy/profile inheritance patch landed locally on 2026-05-02 without changing the Stremio split scope:
  - built-in video filter profiles now derive lower-resolution exclusions and higher-resolution inclusions from the live runtime `resolution` rank, so adding `240p`, `400p`, or a future higher resolution updates `At Least Full HD`, `At Least Ultra HD`, and `Ultra HD HDR` automatically;
  - uncustomized stored default profile rules are refreshed from the live taxonomy defaults during settings normalization, while genuinely customized profiles remain untouched;
  - rules that carry a built-in `quality_profile` plus an older explicit token snapshot are treated as profile-owned when the only missing values are taxonomy-added resolution tokens, preserving real manual edits while fixing stale built-in selections;
  - the rule form can keep showing the selected built-in profile instead of falling back to `Current manual selection` after taxonomy changes, and rule/search active local filters consume the refreshed profile token set;
  - focused and full validation are green for `tests/test_quality_filters.py`, rule/search quality-profile consumers, `cmd /c scripts\\check.bat`, desktop build, and Docker `/health`; version touchpoints are now synced to `1.1.2` for the patch release.
- A Docker runtime SQLite-lock hardening patch landed locally on 2026-05-05 without changing the Stremio split scope:
  - live Docker logs showed `sqlite3.OperationalError: database is locked` causing transient `Internal Server Error` responses on regular page reads while background work was active;
  - SQLite connections now set `PRAGMA busy_timeout = 30000` and `PRAGMA journal_mode = WAL`, reducing reader/write contention during scheduled fetch or startup sync work;
  - regression coverage now verifies the SQLite engine busy-timeout/WAL contract, with focused config tests and Ruff passing.


- Product/design follow-up planning session completed on 2026-05-05 without changing phase-25 implementation scope:
  - created cross-cutting contract docs for application behavior, data/state model, UI/UX layout rules, current implementation gaps, phased refactoring roadmap, and test strategy to guide upcoming qB-rule quality/taxonomy UX hardening work;
  - identified the top risk as managed preset linkage semantics potentially drifting through inference-heavy save/normalization paths when taxonomy/preset state evolves, so the next implementation slice should start with explicit managed/manual mode contract guardrails before UI redesign work.

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
| P25-04 | Cut and publish the breaking-change release. | Codex | 2026-04-19 | in progress | Version is bumped consistently, changelog/docs are updated, and the release commit/tag are published to git. | `1.1.1` candidate is version-synced and release-validated locally on 2026-04-29; commit/tag/push remain pending. |
| P25-05 | Add backend Docker runtime support. | Codex | 2026-04-30 | completed | Backend has Dockerfile/Compose support with persistent data, documented host-service configuration, and a running shared-stack container. | `Dockerfile`, `.dockerignore`, `C:\\Users\\nucc\\docker-config\\docker-compose.yml`, README/.env docs, AGENTS closeout instruction, green health-route pytest, and live Docker `/health` proof on 2026-04-30. |
| P25-06 | Restore repo-move-safe database pathing. | Codex | 2026-04-30 | completed | Local and Docker backends read the repo-owned `data\\qb_rules.db`, and relative SQLite URLs no longer depend on process working directory. | `app/config.py`, `tests/test_config.py`, `C:\\Users\\nucc\\docker-config\\docker-compose.yml`, README/AGENTS docs, green config tests, and live Docker DB count of `190` rules. |
| P25-07 | Harden Docker host file-path integrations. | Codex | 2026-04-30 | completed | Stremio LevelDB and Jellyfin DB paths saved as Windows paths work from the Docker backend. | `resolve_runtime_path(...)`, Stremio/Jellyfin service updates, shared Docker `C:\\Users` and `C:\\ProgramData` mounts, focused pytest/ruff checks, and live Docker Stremio/Jellyfin probes. |
| P25-08 | Enforce quality profiles and Jackett-owned passive RSS feeds. | Codex | 2026-05-01 | completed | qB rule generation, app search/filtering, and qB RSS feed subscriptions are driven by effective quality profiles and Jackett configured indexers, with Russian as the default language-managed scope and multi-language scope support. | Focused ruff/pytest/node checks are green; shared Compose rebuild succeeded; `/health` is current; live Docker proof shows `197/197` rules OK in DB, `197` qB RSS rules, and `12` qB RSS feeds under `Jackett/...`. |
| P25-09 | Add manual Jackett language overrides and runtime taxonomy persistence. | Codex | 2026-05-02 | completed | Unknown or misclassified configured Jackett indexers can be assigned language codes from UI/settings without hardcoding them in source, while Jackett remains the source of truth for indexer membership; taxonomy edits persist in runtime data and common value edits no longer require raw JSON editing. | `/settings` `Indexer language overrides`, `QB_RULES_JACKETT_LANGUAGE_OVERRIDES`, `JackettClient(language_overrides=...)`, structured `/taxonomy` add/remove/move controls with compact non-overlapping rows and `⇧`/`⇩`/`×` icon buttons, runtime `data/quality_taxonomy.json`, README/.env/Compose docs, focused pytest/ruff/node checks, and shared Docker rebuild plus `/health` proof on 2026-05-02. |
| P25-10 | Preserve filter-profile intent across runtime taxonomy changes. | Codex | 2026-05-02 | completed | Built-in video profiles inherit newly added lower/higher resolution tokens from the live taxonomy rank, stored uncustomized defaults and profile-owned rule snapshots refresh safely, and release validation proves Docker serves `1.1.2`. | `cmd /c scripts\\check.bat` passed (`348 passed`), `cmd /c scripts\\run_dev.bat desktop-build` passed (`0 Warning(s)`, `0 Error(s)`), shared Compose rebuild succeeded, Docker `/health` reports `app_version=1.1.2`, and the live rule `a6a60200-7533-4733-bd1a-0f8ea1e8fbdf` renders `Ultra HD HDR` selected with `240p` in the effective filters. |
| P25-11 | Harden SQLite concurrency for Docker background work. | Codex | 2026-05-05 | completed | Normal page reads no longer fail fast with `database is locked` during short background write contention. | Live Docker logs captured the root `sqlite3.OperationalError: database is locked`; `app/db.py` now applies a 30 second SQLite busy timeout plus WAL mode; `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_config.py -q` and `.\\.venv\\Scripts\\python.exe -m ruff check app\\db.py tests\\test_config.py` passed. |

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

1. Finish validation for the `1.1.2` taxonomy/profile inheritance patch, then publish the release commit and tag to git.
2. Verify qBittorrent and Jackett connectivity from the running Docker backend using `host.docker.internal` URLs.
3. If the repo moves again, update the shared Docker bind mount to the new repo `data` path before rebuilding `qb-rss-rules`.
4. Keep using `resolve_runtime_path(...)` for any future settings/env path that points at a local host file needed by Docker.
5. Keep qBittorrent running before future Docker closeout probes; after reboot it was not listening on `127.0.0.1:8080`, and the Docker backend could not complete qB sync until the desktop qB process was started.
6. Decide whether the passive qB feed-resolution state now needs its own persisted warning/status field before the next rules UX cleanup slice.
7. Decide whether the keep-searching watched-progress search floor should remain active-search-only or also influence generated qB RSS rules later.
8. Continue broadening the structured taxonomy editor for bundle/rank/alias reordering; raw JSON remains available for those advanced edits today.

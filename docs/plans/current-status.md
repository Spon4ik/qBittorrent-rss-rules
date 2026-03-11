# Current Status

## Current focus

- Phase 6: post-v0.2.0 follow-up hardening and scope decisions
- Release-process automation and evidence-driven phase sign-off

## Implemented

- Added a repo-local `ui-ux-designer` Codex skill under `.codex/skills/ui-ux-designer` with reusable UX workflow guidance plus handoff/checklist templates for implementation-ready UI design outputs.
- Added a repo-local `jackett-api-expert` Codex skill under `.codex/skills/jackett-api-expert` with capability-aware Torznab query strategy and fallback/triage references.
- Added a repo-local `qa-engineer` Codex skill under `.codex/skills/qa-engineer` with a risk-based QA workflow plus reusable test-plan and bug-report templates.
- Added a repo-local `project-management` Codex skill under `.codex/skills/project-management` with reusable templates for current-status updates, active phase updates, and risk/decision logging.
- Added a repo-local `project-design-documentation-engineer` Codex skill under `.codex/skills/project-design-documentation-engineer` with workflow guidance and templates for synchronized project plans, design specs, ADRs, QA plans, and resumable handoffs.
- Added a repo-local `versioning-manager` Codex skill under `.codex/skills/versioning-manager` with SemVer bump guidance, cross-file version sync workflow, and release-prep verification checklists.
- Added a repo-local `programming-sprint-manager` Codex skill under `.codex/skills/programming-sprint-manager` with a small-slice sprint execution workflow plus reusable sprint-board and slice-sizing templates for fixes, features, and improvements.
- Built-in `At Least UHD` filter profile can now be overwritten without duplicating the preset in the profile selector.
- Repo-local resumability instructions now live in `AGENTS.md`.
- Phase planning docs now live under `docs/plans/`.
- `app/data/quality_taxonomy.json` now stores the current quality taxonomy as an editable JSON source of truth.
- `app/services/quality_filters.py` now loads, validates, and caches taxonomy data from JSON while preserving current token behavior.
- `tests/test_quality_filters.py` now covers compatibility behavior, validation failures, and cache reset behavior for the taxonomy loader.
- Initial implementation plans for phases 2-4 now exist under `docs/plans/` to align roadmap intent with implementation-ready scope.
- `app/data/quality_taxonomy.json` now ships schema version 2 metadata for bundles, ranks, and aliases while preserving the existing leaf token list and order.
- `app/services/quality_filters.py` now accepts taxonomy schema versions 1 and 2, validates phase-2 metadata, and resolves bundle or alias inputs back to flat leaf token IDs.
- `tests/test_quality_filters.py` now covers schema-version compatibility plus bundle, alias, and rank validation paths.
- `docs/architecture.md` and `docs/api.md` now document the richer taxonomy model and the flat-token persistence contract.
- `app/services/quality_filters.py` now provides taxonomy draft preview, apply, cache refresh, and local audit-log helpers for the editor workflow.
- `app/routes/pages.py` and `app/routes/api.py` now expose `/taxonomy`, `/api/taxonomy/validate`, and `/api/taxonomy/apply`.
- `app/templates/taxonomy.html` now provides a server-rendered editor with impact analysis and recent audit entries.
- `tests/test_routes.py` now covers taxonomy page rendering plus safe apply and orphan-token rejection flows.
- Taxonomy apply now blocks only draft-induced orphaning, so label-only bundle renames still save even when older rules already contain stale unknown tokens; those existing invalid references are reported separately in the preview.
- Built-in quality profile labels now follow the matching taxonomy bundle labels, so renaming `at_least_hd` in the taxonomy editor updates the rule-form and settings labels.
- Rule form feed UX now uses checkbox-based selection with `Select all` / `Clear all` controls and a default-on remember-defaults toggle on create and edit forms backed by `AppSettings.default_feed_urls`.
- Feed refresh now preserves currently selected saved-feed entries in the form even if qBittorrent no longer returns them during that edit session.
- `tests/test_routes.py` now posts repeated form values using dict/list payloads so route coverage stays compatible with the current `httpx` test client behavior.
- `scripts/test.sh` and `scripts/test.bat` now refresh `logs/tests/pytest-last.log` and `logs/tests/pytest-last.xml` on every pytest run so test failures leave repo-local artifacts for follow-up debugging.
- `app/data/quality_taxonomy.json` now ships schema version 3 with media-aware video/audio groups and audiobook/music codec, bitrate, and channel tags.
- `app/services/quality_filters.py` now validates taxonomy `media_types`, infers media scopes for legacy saved profiles, and serves media-aware built-in filter profiles including audiobook and music presets.
- `app/services/metadata.py` now supports normalized lookup dispatch to OMDb, MusicBrainz, OpenLibrary, and Google Books while keeping the legacy IMDb lookup path compatible.
- `app/templates/rule_form.html` and `app/static/app.js` now filter visible quality options, filter profiles, metadata providers, and the IMDb field based on the selected media type with warning-and-clear behavior for incompatible switches.
- `app/templates/index.html` now exposes a top-level `Create Rule` action in the Rules header.
- Added targeted test coverage for taxonomy v3 media scopes, metadata provider dispatch, and the updated metadata lookup route contract.
- Planning docs now treat phases 1-5 as current-branch work, and a dedicated phase-6 plan exists for Jackett-backed active search.
- Added separate Jackett app/qB connection settings so Docker-aware URL differences are modeled explicitly instead of assuming Jackett search is just another RSS feed.
- Added a first `/search` workspace backed by a normalized Jackett client, optional-keyword query expansion, and a search-to-rule handoff that prefills rule fields without touching the RSS feed selector.
- Saved rules can now launch `/search` directly, and rule-derived Jackett searches use the saved title plus structured include/exclude terms instead of sending the generated regex to Jackett as plain text.
- Rule list and edit views now expose a one-click `Run Search` action, and regex-derived searches now preserve multiple any-of groups from saved lookaheads instead of flattening everything into one loose term bucket.
- Rule-derived Jackett search now degrades to a title-only search with a visible warning when regex expansion exceeds the structured search limits, instead of failing with a 500 error page.
- The `/search` page now also catches unexpected setup, rule-loading, saved-rule derivation, and search-time exceptions, keeps the form visible, and surfaces an inline error instead of returning a server error.
- Saved-rule fallback now prefers a reduced inherited keyword set before dropping to title-only fallback, so regex-heavy rules still carry forward usable include/exclude terms when strict derivation overflows.
- Saved-rule Run Search now clamps overlong derived titles and still auto-runs a title-only fallback when reduced keyword derivation stays invalid, instead of dropping straight to the manual-only error state.
- Jackett searches now reuse saved IMDb IDs, release years, and media-type category narrowing when available, so rule-derived searches can call richer Torznab parameters instead of only `q`.
- Jackett `imdbid` requests now keep the full `tt1234567` form expected by Jackett instead of stripping the `tt` prefix, fixing live `400 Bad Request` failures from the richer search mode.
- Jackett searches now retry `400 Bad Request` responses in stages, first dropping narrower fields like `year` while keeping `imdbid` when possible, and only falling back to broad text search last.
- The `/search` form now auto-enforces an IMDb-first flow for movie or series searches whenever an `IMDb ID` is present; it now keeps primary requests strict `imdbid`-only (aggregate plus optional direct-indexer retries) and keeps broader title text in the separate `Title fallback` section.
- Jackett Torznab XML error payloads such as `<error code="203" ...>` are now treated as real request failures, so unsupported TV `imdbid` searches no longer look like empty successes.
- Live Jackett capability inspection still confirms the current configured set advertises `movie-search imdbid` for some trackers but not `tv-search imdbid`; when that happens, the app now keeps the failed IMDb-first attempts in the primary section and renders a separate broad title-fallback section instead of silently switching the main search to result-level IMDb metadata filtering.
- Jackett timeout errors now include the actual Torznab request summary (for example `t=search q="American Classic" cat=5000`), so UI errors expose which search variant hung instead of only saying `timed out`.
- Timed-out Jackett request variants now degrade per variant instead of aborting the full search immediately: the client can fall through to that variant's safer fallback params (such as dropping `year`) and, when later variants still succeed, the page returns partial results plus an inline warning for the skipped timeout.
- Jackett search requests now retry transient timeout failures before surfacing an error to the UI.
- Jackett standard searches now run a single broad remote fetch (title/media/indexer scope) and apply keyword/year/size/indexer/category filtering locally against cached results instead of expanding remote keyword variants.
- IMDb-first searches now always execute a separate broad title fallback fetch pass (split section), even when primary IMDb-constrained results are present.
- Jackett result normalization now captures richer Torznab metadata (`published_at`, `category_ids`, `year`, `seeders`, `peers`, `leechers`, `grabs`, `download_volume_factor`, `upload_volume_factor`) plus raw `torznab_attrs` for future local filtering slices.
- `/search` now renders fetched-versus-filtered counts for both primary and fallback sections, embeds raw result pools in page JSON, and applies local filter edits interactively in the browser without calling Jackett again.
- `/search` now includes a card/table toggle, 3-level hierarchical local sorting controls, and per-section filter-impact diagnostics showing each active filter value's standalone keep/drop counts plus blocker highlighting when the filtered list is empty.
- `/search` now uses rule-style quality include/exclude checkbox groups plus an explicit `Filter by release year` checkbox, so quality/year local filters align with the rule form interaction model instead of only text fields.
- `/search` now strictly honors the `Filter by release year` toggle end-to-end: unchecked runs no longer pass `release_year` into Jackett/rule-derived payloads, and checkbox state binding now targets the actual checkbox input instead of the hidden fallback field.
- `/search` filter-impact rows now render explicit sentence separators and clearer blocker messaging, fixing merged plain-text output like `Release year = 20260 ...` / `2160p1 ...` and clarifying when other active filters are still the reason results stay at zero.
- Jackett search result normalization now falls back to title-derived year extraction when Torznab omits year attrs, so `release_year` local filtering and the rendered Year column stay aligned for titles like `The Rip (2026) ...`.
- `/search` now accepts grouped any-of keyword syntax using `|` between groups (for example `uhd, 4k | hdr, hdr10`), and local filtering plus filter-impact diagnostics enforce group semantics instead of flattening all variants into one bucket.
- Short excluded keywords such as `sd` / `ts` now use token-level matching instead of broad substring matching, preventing false positives from hidden Torznab metadata text like `sdr` or URL fragments.
- Jackett local filtering now enforces title-query matching (so unrelated titles no longer survive fallback refinement), and short included keywords such as `hdr` now use token-level matching to avoid substring false positives from metadata text like `HDRezka`.
- Title/query local matching now supports non-Latin text (for example Cyrillic titles), so Unicode-heavy libraries are filtered correctly instead of bypassing query checks.
- IMDb-first local filtering now preserves localized titles when the result IMDb ID matches the requested IMDb ID exactly, even if title text differs from the query language.
- IMDb-first request construction now uses strict `imdbid` input only (aggregate and direct-indexer retry paths), while broader title text matching is always kept in the separate `Title fallback` section.
- Search result view defaults are now persisted in `AppSettings` (`search_result_view_mode`, `search_sort_criteria`) with a new `/api/search/preferences` endpoint; `/search` defaults to `Table` and can save current sort/view from the result-view panel.
- Result-view controls now render as a redesigned panel above both `IMDb-first` and `Title fallback` sections, stay synchronized between the two copies, and show clearer availability metric context (`Peers`, `Leechers`, `Grabs`).
- Rules and search pages now opt into a wider responsive shell/content layout to use more horizontal space and reduce vertical scrolling on large displays.
- Jackett result parsing now also reads indexer labels from non-`attr` tags (for example `<jackettindexer>`), and search tables no longer label unknown indexers as `Jackett`.
- When `IMDb-first` fetched count is `0`, the primary summary now suppresses filter-impact diagnostics and shows only query/request context for that empty primary section.
- Saved-rule derivation now treats legacy sentinel overrides like literal `None`/`null` as empty optional text instead of converting them into required keyword filters.
- Required/any keyword matching now treats season and episode shorthand tokens as equivalent variants (`s3` ~= `s03`, `e7` ~= `e07`, `s3e1` ~= `s03e01`) so local filtering no longer drops obvious season hits.
- Jackett active search now appends per-run debug summaries (query/filter inputs plus raw/filtered counts) to `logs/search-debug.log` and includes local drop-reason counts at debug level to make refinement feedback loops easier.
- Added contract tests for the latest search UX/request slice: duplicated result-view panels, IMDb-first zero-fetch filter-impact suppression, dynamic availability column visibility, and Torznab indexer/peer-grab parsing semantics.
- Added regression coverage for title-derived release-year matching, title-query local filtering, short included/excluded token matching, and pipe-delimited any-of keyword groups in `tests/test_jackett.py` and `tests/test_routes.py`.
- Added a DB-driven phase-6 release QA matrix plan at `docs/plans/phase-6-release-qa-plan.md` covering multilingual titles, IMDb-first localized titles, regex-derived rules, and legacy imported rule edge cases.
- Targeted Jackett pytest coverage now passes in the project `.venv` for `tests/test_jackett.py` and `tests/test_routes.py`, including the new Torznab-parameter narrowing path and the fixed keyword-list validator.
- The full pytest suite now passes in the project `.venv` (`95 passed`), including a fix for `RuleBuilder` default category rendering when `AppSettings()` has in-memory `None` template fields.
- Release-validation reruns on 2026-03-09 now pass in both the Windows `.venv` and Linux `.venv-linux` (`117 passed`, `24 warnings`) for full-suite pytest, and `tests/test_jackett.py` + `tests/test_routes.py` targeted coverage passes (`63 passed`, `24 warnings`).
- Executed the DB-driven phase-6 QA matrix on 2026-03-09 using live `data/qb_rules.db` and recorded artifacts at `logs/qa/phase6-matrix-20260309T220744Z.{json,md}` with `15/15` scenarios passing (`0 critical/high`) plus one structured `logs/search-debug.log` event per run.
- Verified Linux release-gate wrappers on 2026-03-09 via `source .venv-linux/bin/activate && ./scripts/check.sh` (`ruff`, `mypy`, full pytest) with `117 passed`, `24 warnings`.
- Prepared v0.1.0 release documentation on 2026-03-10 by updating `CHANGELOG.md` with dated release notes and transitioning `ROADMAP.md` to `v0.2.0` as the active target.
- Re-ran release gates on 2026-03-10 in Linux `.venv-linux` via `source .venv-linux/bin/activate && ./scripts/check.sh` (`117 passed`, `24 warnings`).
- Created local annotated git tag `v0.1.0` on 2026-03-10 from the release-prep `main` commit.
- `scripts/test.sh` now defaults to `--capture=sys` when no capture mode is passed, fixing Linux/WSL wrapper failures from pytest capture teardown `FileNotFoundError` while preserving explicit user capture args such as `-s`.
- Added `docs/native-python-pytest.md` with resumable Linux/WSL bootstrap steps for native `python3 -m pytest` usage, and added `.venv-linux/` to `.gitignore` for the Linux-native virtual environment path.
- `scripts/test.sh` now also auto-detects `.venv-linux/bin/python` ahead of system Python, so Linux/WSL wrapper runs work without manual activation when the repo-local Linux venv exists.
- Mypy cleanup for the release-gating stack is now complete (`mypy app` passes), including typing fixes across `quality_filters`, `jackett`, `api` routes, `pages` routes, and supporting service modules.
- Ruff policy now explicitly ignores FastAPI dependency-in-default warnings for route handlers (`B008` via `app/routes/*.py`) and defers bulk formatting/modernization churn (`E501`, `UP040`, `UP042`); after that policy update and safe auto-fixes, `ruff check .` now passes.
- Added initial service and route coverage for the Jackett client, search page, and settings persistence.
- `/search` now uses a compact panelized layout for high-density screens (`Search criteria` + `Local refinement` panels), paired include/exclude checkbox rows per quality family, and a collapsible keyword-checkbox section.
- `/search` result summaries now render denser filter-impact content (multi-column + scrollable cards) and result-view controls now use grouped sort cards for clearer hierarchy.
- `/search` source context now uses aligned summary cards, and each filter-impact block can be collapsed to reduce vertical noise during iterative tuning.
- Added automated UI-feedback capture tooling for `/search` (`scripts/capture_search_ui.py` plus `scripts/capture_ui.sh` / `scripts/capture_ui.bat`) and documented setup/usage in `README.md`.
- Screenshot capture now defaults to stable non-query `/search` pages and treats live Jackett-query screenshots as opt-in (`--include-live-search`) to avoid routine timeout churn.
- Screenshot capture now detects an already-running local server and skips spawning a second uvicorn process, reducing disruption for multi-shell/WSL workflows.
- Added Playwright to dev dependencies for the screenshot automation flow (`pyproject.toml`).
- `scripts/run_dev.sh` now auto-detects repo-local interpreters and runs `python -m uvicorn`, so WSL/Linux runs no longer require a globally installed `uvicorn` binary.
- Added deterministic phase closeout browser QA automation at `scripts/closeout_browser_qa.py` with wrappers `scripts/closeout_qa.sh` and `scripts/closeout_qa.bat`, using isolated mock qBittorrent/Jackett services plus timestamped JSON/Markdown evidence artifacts.
- Executed automated browser closeout on 2026-03-11 with `9/9` checks passing; artifacts: `logs/qa/phase-closeout-20260311T113931Z/closeout-report.{md,json}`.
- qB connection resolution now handles mixed Windows+WSL topology: in WSL runtime, qB base URLs using `localhost`/`127.0.0.1` are rewritten to `host.docker.internal`, so Windows-hosted qBittorrent remains reachable without per-run env overrides.
- Executed the optional live-provider smoke gate on 2026-03-11 without `QB_RULES_QB_BASE_URL` override; all `4/4` checks passed with artifacts at `logs/qa/live-provider-smoke-20260311T163136Z/result.{md,json}`.
- Completed v0.2.0 release-prep version synchronization (`pyproject.toml`, `app/main.py`, `CHANGELOG.md`, `ROADMAP.md`) and created local annotated tag `v0.2.0` from commit `da37dc8`.

## In progress

- Phase 6 v0.2.0 scope is implemented and release-validated; follow-up polish/scope decisions remain open for v0.2.x.
- Release-process automated checks continue to pass in Linux `.venv-linux` via `./scripts/check.sh` (`ruff`, `mypy`, full pytest).
- The repo-local Windows `.venv` and Linux `.venv-linux` run full tests successfully; unactivated system `python3` still lacks project dependencies by default.
- Linux/WSL screenshot capture still needs host browser libraries (`python -m playwright install-deps chromium` with sudo); capture tooling now fails with explicit remediation messaging.

## Next actions

- Use `docs/plans/phase-6-jackett-active-search.md` `Request Checklist (2026-03-10 refresh)` + `Dated execution checklist (2026-03-10 baseline)` as the source-of-truth tracker.
- Run `./scripts/closeout_qa.sh` (or `scripts\\closeout_qa.bat`) as the default Phase 4/5/6 closeout gate for future UX/search iterations.
- Re-run the optional live-provider smoke gate when endpoint topology or credentials change, using `logs/qa/live-provider-smoke-*` artifacts as release evidence.
- Keep the DB-backed release matrix (`docs/plans/phase-6-release-qa-plan.md`) as the live-data regression pass before final release.
- Decide whether the next phase-6 slice should add persistent Jackett-backed rule sources as a distinct saved source type, still separate from RSS feeds.

## Deferred / future phases

- Phase 6 planning now lives in `docs/plans/phase-6-jackett-active-search.md`; the initial slice is in the repo, with deeper persistence work still deferred.
- Follow-up: decide whether remembered feed defaults should also be editable from `/settings`
- Follow-up: decide whether provider-specific lookup hints or richer search result pickers are needed beyond the current first-match flow

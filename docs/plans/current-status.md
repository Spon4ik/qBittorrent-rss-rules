# Current Status

## Current focus

- Phase 5: media-aware rule form and multi-provider metadata lookup validation
- Phase 6: initial Jackett active-search implementation with explicit RSS-feed separation

## Implemented

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
- The `/search` form now exposes `IMDb ID`, `Release year`, and an explicit `Use IMDb ID only` toggle; when enabled, Jackett requests send only `imdbid` (no `q` or `year`) and skip broad-search fallback so strict IMDb-only testing is possible.
- Jackett search requests now retry transient timeout failures before surfacing an error to the UI.
- Targeted Jackett pytest coverage now passes in the project `.venv` for `tests/test_jackett.py` and `tests/test_routes.py`, including the new Torznab-parameter narrowing path and the fixed keyword-list validator.
- The full pytest suite now passes in the project `.venv` (`95 passed`), including a fix for `RuleBuilder` default category rendering when `AppSettings()` has in-memory `None` template fields.
- Added initial service and route coverage for the Jackett client, search page, and settings persistence.

## In progress

- Phase 5 code is implemented in the current branch, and pytest now passes in the repo `.venv`; manual browser validation is still pending.
- The repo-local Windows `.venv` now has the required test dependencies and can run the full suite, but the default Linux `python3` in this shell still does not have `pytest`.
- Phase 4 validation and closeout are still pending as a separate follow-up even though the Phase 5 code landed.
- Phase 6 is now in an initial implementation state with pytest coverage passing; manual browser checks are still pending.

## Next actions

- Manually verify `/rules/new` and `/rules/{rule_id}` for `series -> music -> audiobook -> other` switching, the warning-and-clear prompt, provider filtering, and IMDb field visibility.
- Manually verify metadata lookup population for OMDb title search plus MusicBrainz, OpenLibrary, and Google Books lookups.
- Manually verify the new Rules-page header `Create Rule` action on desktop and mobile layouts.
- Close out Phase 4 and Phase 5 after environment-level validation, then decide whether any remaining provider-specific UX polish should become a follow-up slice.
- Manually verify `/search` for title-only search, optional-keyword search (`4k, 2160p`), and the `Use In New Rule` handoff.
- Manually verify `/rules/{rule_id}/search` for saved movie/series rules with `IMDb ID` and `Release year` populated and confirm the same search still works while returning more precise Jackett matches.
- Manually verify `/rules/{rule_id}/search` with `Use IMDb ID only` enabled and confirm `Requests used` shows `imdbid` without `q=` for movie/series rules that have saved IMDb IDs.
- Manually verify `/rules/{rule_id}/search` for regex-heavy legacy rules that exceed structured-term limits and confirm the title-only fallback warning renders instead of a server error.
- Manually verify `/rules/{rule_id}/search` for regex-heavy rules that now hit reduced-keyword fallback and confirm the inherited terms remain useful.
- Manually verify `/rules/{rule_id}/search` for imported or legacy rules with unusually long saved titles and confirm the search still runs with a clamped title-only fallback when needed.
- Decide whether the next phase-6 slice should add persistent Jackett-backed rule sources as a distinct saved source type, still separate from RSS feeds.

## Deferred / future phases

- Phase 6 planning now lives in `docs/plans/phase-6-jackett-active-search.md`; the initial slice is in the repo, with deeper persistence work still deferred.
- Follow-up: decide whether remembered feed defaults should also be editable from `/settings`
- Follow-up: decide whether provider-specific lookup hints or richer search result pickers are needed beyond the current first-match flow

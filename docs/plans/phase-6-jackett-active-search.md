# Phase 6: Jackett-Backed Active Search

## Status

- Implementation is in progress in the repo as an initial slice.
- This phase is still scoped for the next release after phase 5 validation closes.
- The current branch now includes separate Jackett app/qB connection settings, a `/search` page, one-click rule-level search launch links, and search-to-rule handoff without mixing Jackett search into RSS feed selection.
- Rule-derived searches now clamp overlong saved titles before validation and can still auto-run a title-only fallback when reduced keyword derivation remains invalid.
- Rule-derived searches now also reuse saved IMDb IDs, release years, and media-type category narrowing when those fields are available, so Jackett can receive richer Torznab parameters than `q` alone.
- IMDb-based Jackett narrowing now sends the full `tt1234567` identifier format that Jackett expects, avoiding `400 Bad Request` responses from the richer Torznab mode.
- Richer Torznab requests now retry `400 Bad Request` responses in stages, preserving `imdbid` where possible before falling back to broad text search only as a last resort.
- The `/search` UI now auto-enforces an IMDb-first path for movie/series lookups whenever an IMDb ID is present, first trying strict `imdbid`, then `q + imdbid`, and if the aggregate `all` indexer rejects both, retrying only direct indexers whose published Jackett capabilities include `imdbid`.
- Jackett Torznab XML error bodies such as `<error code="203" ...>` are now treated as failed requests, so unsupported TV `imdbid` searches trigger the intended retries instead of silently appearing as empty result sets.
- If the configured TV indexers do not advertise input-side `imdbid` support at all, the app now keeps the failed IMDb-first attempts in the primary section and renders a separate broader title-fallback section below instead of pretending the fallback itself was an IMDb-constrained search.
- Jackett timeout failures now include the concrete request label in the surfaced error, so the UI identifies which Torznab query variant timed out.
- Timed-out Jackett variants now degrade at the variant level: the client can retry that same variant's fallback params (for example, dropping `year`) and, if other expanded variants still succeed, return partial results with an inline warning instead of failing the entire search run.
- The project `.venv` now passes targeted phase-6 pytest coverage for `tests/test_jackett.py` and `tests/test_routes.py`.
- The full repo pytest suite now also passes in the project `.venv`; remaining validation is manual browser coverage.
- A repo-local `project-management` skill now exists under `.codex/skills/project-management` so in-progress phase validation sessions can follow a consistent status/plan closeout workflow.
- A repo-local `qa-engineer` skill now exists under `.codex/skills/qa-engineer` so validation sessions can follow a consistent risk-map, evidence capture, and severity-first reporting workflow.
- A repo-local `jackett-api-expert` skill now exists under `.codex/skills/jackett-api-expert` to guide Torznab capability-aware query design, fallback sequencing, and failure triage.
- A repo-local `ui-ux-designer` skill now exists under `.codex/skills/ui-ux-designer` to structure feature UX workflow, accessibility checks, and implementation-ready handoff specs during manual validation/polish passes.
- The goal is to add an on-demand search workflow beside RSS rule authoring, not to replace RSS automation.

## Goal

Add a local active-search workspace that queries Jackett from the app, supports richer keyword logic than qBittorrent's plain-text plugin search box, and lets users hand off a search query into rule authoring.

## Why this phase exists

qBittorrent's built-in search UI is a flat text box. The current app already models optional include keywords and media-aware filters for RSS rules, so it can provide a better front end for Jackett by expanding one structured search into multiple Jackett requests and merging the results locally.

## In scope

- Add optional Jackett connection settings (base URL and API key) alongside the existing qBittorrent settings.
- Keep the source model explicit: RSS feeds remain persistent rule inputs, while Jackett active search remains a separate on-demand source type.
- Support separate Jackett URLs for app-side search calls versus future qBittorrent-consumed rule sources when Docker/network topology differs.
- Add a normalized Jackett search client that can query one or more indexers through the Torznab API.
- Add structured search inputs for title, media type, indexer scope, and optional keyword groups.
- Derive active searches from saved rules using structured title/include/exclude terms instead of passing saved regex text through Jackett's plain-text query field, including multiple preserved any-of groups from saved regex lookaheads when possible.
- If a saved regex expands past the structured search limits, fall back to a title-only search with a visible warning instead of failing the page render.
- Prefer a reduced inherited keyword set before dropping all the way to title-only fallback, so saved-rule searches stay closer to the original rule intent.
- Add app-side query expansion for "any of" terms such as `4k` or `2160p`, then merge and de-duplicate results by infohash, GUID, or normalized title.
- Render an active-search page with result metadata, source indexer, size, age, and search actions.
- Add a search-to-rule handoff so an active search can prefill the rule form with the same title and filter intent.

## Out of scope

- Background saved searches or alerts.
- Auto-downloading or silently sending results to qBittorrent without an explicit follow-up action.
- Replacing the existing RSS rule workflow.
- Non-Jackett search providers in the initial slice.

## Proposed implementation

1. `app/models.py`, `app/schemas.py`, `app/services/settings_service.py`, `app/templates/settings.html`
   - Add optional Jackett settings fields and validation.
2. `app/config.py`
   - Add environment overrides for Jackett base URL and API key, matching the existing local-first secret handling pattern.
3. `app/services/jackett.py`
   - Add a client for Jackett Torznab search requests.
   - Normalize XML results into app-level search result models.
   - Expand structured "any of" keyword groups into multiple requests when Torznab cannot express the logic directly.
   - Keep this as an app-local client instead of importing qBittorrent's Jackett plugin directly, because the plugin depends on qB-specific helper modules, printer hooks, and config-file conventions.
4. `app/routes/pages.py`, `app/routes/api.py`, `app/templates/search.html`, `app/static/app.js`
   - Add a `/search` page and supporting API endpoint for structured active searches.
   - Add query-prefill and "use this in rule form" actions.
5. `tests/test_jackett.py`, `tests/test_routes.py`
   - Cover connection handling, query expansion, result merging, error cases, and page rendering.
6. `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/plans/current-status.md`, `ROADMAP.md`
   - Document the new search workflow and operational constraints.

## Acceptance criteria

- A user can run an active search against Jackett from the app without leaving the local UI.
- A single structured search can represent optional synonym groups such as `4k` or `2160p`.
- Duplicate results from multiple expanded queries or multiple indexers are merged before rendering.
- Search failures return actionable configuration or provider errors.
- Setup, saved-rule, or search-time edge cases degrade into an editable search form with a visible error instead of a 500 page.
- Transient Jackett timeout failures are retried automatically before the UI treats the search as failed.
- A search can prefill the rule form so RSS automation and one-off search share the same filter intent.

## Validation checklist

- Run targeted service and route tests for Jackett client behavior and search page rendering. Current status: passing in the repo `.venv` for `tests/test_jackett.py` and `tests/test_routes.py`.
- Run the full pytest suite through `scripts/test.sh` or `scripts/test.bat`. Current status: passing in the repo `.venv`.
- Manually verify `/search` for:
  - a plain title-only search
  - an expanded keyword search
  - an indexer-limited search
  - the search-to-rule handoff into `/rules/new`
- Manually verify `/rules/{rule_id}/search` for saved movie or series rules with metadata-filled `IMDb ID` / `Release year` fields and confirm Jackett still returns results with the narrower request.
- Manually verify `/rules/{rule_id}/search` for a movie or series rule with `IMDb ID` populated and confirm the page shows an `IMDb-first results` section with strict `imdbid`, aggregate `q + imdbid`, and optional direct-indexer retries, plus a separate `Title fallback` section below when the primary search returns no matches.
- Manually verify `/rules/{rule_id}/search` for imported or legacy rules with unusually long saved titles and confirm the clamped title-only fallback still runs when structured reduction cannot.
- Manually verify graceful errors for missing Jackett config, HTTP failures, and empty result sets.

## Dependencies

- Jackett must be reachable from the local app host and expose Torznab endpoints for the configured indexers.
- Phase 5 validation should close first so the existing rule-form contract is stable before the new search surface is added.

## Roll-forward notes

- If direct "send to qBittorrent" actions are needed later, add them as explicit user-triggered actions on top of the normalized result model.
- If non-Jackett providers are added later, keep the app-level structured search contract provider-agnostic.
- If persistent Jackett-backed rule sources are added later, store them as a distinct source type instead of treating them as plain RSS feed URLs in the app UI.

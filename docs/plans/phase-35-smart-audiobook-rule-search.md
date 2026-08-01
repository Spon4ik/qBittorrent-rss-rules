# Phase 35 - Smart Audiobook Rule Search

## Summary

Phase 35 adds smart audiobook metadata lookup and saved-rule search hints so an ISBN miss from OpenLibrary does not block audiobook rule creation. Audiobook rules now default to a `Smart audiobook` lookup provider that tries Google Books first and OpenLibrary second, returns structured book fields when available, and leaves qB RSS rule generation title-based.

## Scope

- Add `Smart audiobook` as the default audiobook metadata lookup provider.
- Enrich audiobook metadata lookup results with authors, publisher, ISBN, provider source, year, and combined failure messages.
- Add `Rule.search_metadata` as a JSON rule column with SQLite auto-migration.
- Persist audiobook title, author, publisher, genre, and ISBN hints from the rule form.
- Use saved audiobook hints when building `JackettSearchRequest` from a rule.
- Add ISBN to the active Jackett search request/search form.
- Keep Jackett audiobook direct searches capability-aware: direct `t=book` indexer requests only send `isbn` when caps advertise it.
- Use audiobook fallback query variants in this order: `title author`, `title`, final `isbn`.

## Non-Goals

- No paid ISBN APIs, web-search ingestion, scraping, or tracker detail-page enrichment.
- No qB RSS rule regex contract change; qB sync remains title/feed/regex based.
- No hidden inference from arbitrary titles beyond the explicit saved hints.

## Implementation Notes

- Google Books and OpenLibrary remain independently selectable providers; `Smart audiobook` is a provider-aware fallback chain.
- Smart lookup returns the successful provider as the result provider, with prior provider failures in `lookup_warnings`.
- Saved rule search metadata stores only non-empty audiobook hint fields.
- Generic audiobook fallback avoids the old final `t=search` compatibility leg so book-mode query variants stay deterministic.

## Validation Evidence

- Red-first regressions were added for smart audiobook lookup success/failure, provider defaulting, rule metadata persistence, edit-form round trip, saved-rule search payload construction, ISBN capability gating, and audiobook fallback query variants.
- `cmd.exe /c scripts\test.bat tests\test_metadata.py -q` passed (`16 passed`).
- `cmd.exe /c scripts\test.bat tests\test_jackett.py -q` passed (`59 passed`).
- `cmd.exe /c scripts\test.bat tests\test_routes.py -q` passed.
- `cmd.exe /c scripts\test.bat tests\test_static_assets.py -q` passed (`6 passed`).
- `node --check app\static\app.js` passed.
- `.venv\Scripts\ruff.exe check app\schemas.py app\models.py app\db.py app\services\metadata.py app\services\jackett.py app\routes\api.py app\routes\pages.py tests\test_metadata.py tests\test_jackett.py tests\test_routes.py` passed.
- `cmd.exe /c scripts\check.bat` passed (`485 passed`, `302 warnings`).
- Shared Docker Compose rebuild passed with `& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build -d qb-rss-rules`.
- PowerShell `Invoke-WebRequest http://127.0.0.1:8000/health` hit the known local `NullReferenceException`; `curl.exe http://127.0.0.1:8000/health` returned `status=ok`, `app_version=1.2.17`, and the expected backend contract/capabilities.

## Status

- Status: implemented and locally/Docker validated on 2026-06-20.
- Release target: smart audiobook lookup/search follow-up on top of `v1.2.17`.
- Follow-up: consider showing `lookup_warnings` in the UI as non-blocking provider warnings rather than only returning them in JSON.

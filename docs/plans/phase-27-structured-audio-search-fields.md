# Phase 27 - Structured Audio Search Fields

## Summary

Expose the structured Jackett audio fields already supported by the backend request schema on the active search page, so music and audiobook searches can intentionally send native Torznab `artist`, `album`, `track`, `label`, `title`, `author`, `publisher`, and `genre` parameters.

## Scope

- Add active-search form fields for structured music/audiobook metadata.
- Preserve the existing title, quality, local-filter, category, and indexer behavior.
- Route submitted structured fields into `JackettSearchRequest`.
- Keep saved-rule derived searches unchanged unless they already provide structured request fields later.
- Add route coverage proving structured fields survive form round trip and reach `JackettClient.search`.

## Non-Goals

- Do not infer structured fields from arbitrary titles.
- Do not change Jackett service request construction beyond consuming existing schema fields.
- Do not change qB RSS rule payloads, feed persistence, taxonomy behavior, or Stremio sync scope.

## Acceptance

- Manual `/search` requests with music structured fields pass those values to `JackettSearchRequest`. Completed with `tests/test_routes.py::test_search_page_passes_structured_music_fields_to_jackett`.
- Manual `/search` requests with audiobook structured fields pass those values to `JackettSearchRequest`. Completed with `tests/test_routes.py::test_search_page_passes_structured_audiobook_fields_to_jackett`.
- The rendered search form preserves submitted structured field values. Covered by the same route regressions.
- Existing route/Jackett tests remain green.

## Closeout

- Implementation: `/search` now renders a compact structured audio field group and routes submitted music/audiobook metadata into the existing `JackettSearchRequest` schema.
- Versioning: published as patch release `v1.1.5`.
- Validation evidence: targeted structured field regressions passed; `tests/test_routes.py tests/test_jackett.py tests/test_static_assets.py` passed; Ruff passed for touched Python files; `git diff --check` passed; `cmd.exe /c scripts\check.bat` passed with `374 passed`; shared Docker Compose rebuild passed and `/health` reports `app_version=1.1.5`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`; `cmd.exe /c scripts\run_dev.bat desktop-build` passed with `0 Warning(s)` and `0 Error(s)`; browser closeout report `logs/qa/phase-closeout-20260507T152743Z/closeout-report.md` passed all checks.
- GitHub release: `https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.1.5`.
- Discovery review: structured audio now has both direct-indexer scope parity and explicit manual fields. Further audio work should focus on intentional metadata population or provider lookup, not hidden inference in Jackett request construction.

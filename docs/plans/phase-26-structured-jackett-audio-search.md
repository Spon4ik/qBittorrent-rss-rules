# Phase 26 - Structured Jackett Audio Search Scope

## Summary

Tighten the structured Jackett music/audiobook search path so native Torznab `music` / `book` parameters respect the same operator-selected indexer scope as ordinary search. This keeps the post-`v1.1.3` backlog cleanup narrow: prefer capable direct indexers and native structured params where available, without broadening into UI redesign, feed model changes, or new provider behavior.

## Scope

- Keep existing query semantics, local filtering, category enrichment, and result merging unchanged.
- Preserve the current broad fallback behavior when no structured request returns rows.
- Make structured music/audiobook direct-indexer probes honor:
  - an explicit `indexer` value other than `all`;
  - valid `filter_indexers` scope derived from affected feeds or manual search filters.
- Add focused Jackett service regressions for scoped structured music/book search.
- Run focused Jackett tests, broader touched-route/static smoke if needed, Ruff, Docker rebuild, `/health`, qB login, and Jackett discovery.

## Non-Goals

- Do not add new Phase 25 or native Stremio addon behavior.
- Do not remove the manual affected-feed compatibility UI.
- Do not infer artist/album/author fields from arbitrary titles in this slice.
- Do not change qB RSS rule payload semantics or taxonomy persistence behavior.

## Acceptance

- A structured music search scoped to one capable indexer sends the native `t=music` request only to that indexer. Completed with `tests/test_jackett.py::test_jackett_client_structured_music_search_respects_explicit_indexer_scope`.
- A structured audiobook search scoped by `filter_indexers` sends the native `t=book` request only to matching capable indexers. Completed with `tests/test_jackett.py::test_jackett_client_structured_book_search_respects_filter_indexer_scope`.
- If no scoped indexer supports the native mode, the existing broad search fallback remains available.
- Existing Jackett request/fallback tests remain green.

## Discovery Review

- Phase R8 and the P4 browser cleanup confirmed that hidden scope drift is the main risk class for this app. This phase applies the same principle to structured active search: visible/indexer-derived scope must match the direct Jackett requests the app actually sends.

## Closeout

- Implementation: `JackettClient._search_structured_media_first` now filters configured native-mode indexers through the same explicit `indexer` / `filter_indexers` scope used by standard search before issuing direct structured requests.
- Versioning: prepared as patch release `v1.1.4`.
- Validation evidence: scoped structured regressions passed before the broader gate; `tests/test_jackett.py tests/test_routes.py` passed; Ruff passed for touched Python files; `git diff --check` passed; `cmd.exe /c scripts\check.bat` passed with `372 passed`; shared Docker Compose rebuild passed and `/health` reports `app_version=1.1.4`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`; `cmd.exe /c scripts\run_dev.bat desktop-build` passed with `0 Warning(s)` and `0 Error(s)`; browser closeout report `logs/qa/phase-closeout-20260507T151814Z/closeout-report.md` passed all checks.

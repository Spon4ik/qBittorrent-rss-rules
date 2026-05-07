# Phase 28 - Rule/Search Scope Authority

## Summary

Phase 28 makes saved rule active-search scope explicit instead of deriving it from qB RSS feed URLs. The contract is that `feed_urls` remains the passive qB RSS sync scope, while a new persisted `search_indexers` rule field owns Jackett active search and rule-snapshot fetch scope.

## Scope

- Add persisted rule-level `search_indexers` for Jackett active-search scope.
- Preserve `feed_urls` as qB RSS passive sync scope and keep qB rule payload semantics unchanged.
- For language-managed rules, resolve and save both qB RSS feed URLs and Jackett indexer slugs.
- For legacy/manual rules, infer search indexers from existing feed URLs only when the explicit field is absent or empty.
- Update saved-rule search and inline rule search to prefer `search_indexers`, with feed-derived behavior retained as a legacy fallback.
- Add rule-page diagnostics that distinguish passive qB feed scope from active Jackett search scope and name whether active scope is explicit or inferred.
- Keep manual affected-feed UI in place, labelled as passive qB RSS scope.

## Non-Goals

- Do not remove the manual affected-feed UI.
- Do not change qB RSS generated rule semantics, quality taxonomy behavior, or saved feed persistence.
- Do not broaden this into Phase 25, addon work, or a large route/template split.

## Test Plan

- Model/persistence coverage for rules with no explicit `search_indexers`.
- Route tests for language-managed create/update persisting both feed URLs and search indexers.
- Saved-rule search tests proving explicit `search_indexers` takes precedence over feed-url inference.
- qB sync tests proving `affectedFeeds` still comes from `feed_urls`.
- Validation gate:
  - `pytest tests/test_routes.py tests/test_sync_service.py tests/test_rule_builder.py tests/test_jackett.py`
  - `cmd.exe /c scripts\check.bat`
  - Ruff on touched Python files
  - Docker rebuild, `/health`, qB login, Jackett discovery
  - Browser closeout if templates or JS change

## Status

- Status: implemented and release-validated.
- Started: 2026-05-07.
- Release target: `v1.1.6`.

## Closeout Evidence

- Added `Rule.search_indexers` with SQLite column backfill, form-schema normalization, language-managed create/update persistence, saved-rule search precedence, rule-fetch snapshot precedence, qB sync refresh, and rule-page scope diagnostics.
- Preserved qB RSS rule semantics: `RuleBuilder` still builds `affectedFeeds` from `feed_urls`, and focused sync coverage proves `search_indexers` does not enter qB payloads.
- Validation:
  - `pytest tests/test_routes.py tests/test_sync_service.py tests/test_rule_builder.py tests/test_jackett.py` passed (`230 passed`).
  - `pytest tests/test_rule_fetch_ops.py` passed (`6 passed`).
  - Ruff passed on touched Python files.
  - `cmd.exe /c scripts\check.bat` passed (`378 passed`).
  - Browser closeout passed all checks (`logs/qa/phase-closeout-20260507T191237Z/closeout-report.md`).
  - Shared Docker Compose rebuild passed, Docker `/health` returned `app_version=1.1.6`, inside-container qB login returned `qb_test=ok`, and inside-container Jackett discovery returned `jackett_indexers=12`.

## Discovery Review

- The implementation confirmed a second active-search boundary in `rule_fetch_ops`: rules-page/scheduled snapshot fetches had their own feed-scope helper. Phase 28 updated that path too so saved-rule search, inline search, and snapshot fetches follow the same authority order.
- No Phase 25/addon behavior was restarted.

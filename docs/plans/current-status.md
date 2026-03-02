# Current Status

## Current focus

- Phase 4: feed selection UX validation and closeout

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
- Rule form feed UX now uses checkbox-based selection with `Select all` / `Clear all` controls and an opt-in remember-defaults toggle for new rules backed by `AppSettings.default_feed_urls`.
- Feed refresh now preserves currently selected saved-feed entries in the form even if qBittorrent no longer returns them during that edit session.
- `tests/test_routes.py` now posts repeated form values using dict/list payloads so route coverage stays compatible with the current `httpx` test client behavior.
- `scripts/test.sh` and `scripts/test.bat` now refresh `logs/tests/pytest-last.log` and `logs/tests/pytest-last.xml` on every pytest run so test failures leave repo-local artifacts for follow-up debugging.

## In progress

- Phase 4 code is implemented, but full pytest and manual browser validation are still pending in a fully provisioned development environment.

## Next actions

- Install the project test dependencies, then run route and form pytest coverage followed by the full pytest suite in the normal development environment.
- Use `scripts/test.sh` or `scripts/test.bat` for validation runs so the latest pytest transcript is always available under `logs/tests/`.
- Manually verify `/rules/new` feed checkbox rendering, `Select all` / `Clear all`, refresh, and remembered default feed behavior.
- Decide whether remembered defaults should also be editable from `/settings` in a follow-up phase-4 slice.
- Close out Phase 4 after environment-level validation, and keep any remaining taxonomy UI polish from phase 3 as separate follow-up work.

## Deferred / future phases

- Follow-up: decide whether remembered feed defaults should also be editable from `/settings`

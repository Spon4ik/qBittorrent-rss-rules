# Current Status

## Current focus

- Phase 4: feed selection UX improvements

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
- Rule form feed UX now includes `Select all` / `Clear all` controls and an opt-in remember-defaults toggle for new rules backed by `AppSettings.default_feed_urls`.

## In progress

- Phase 4 implementation is started with bulk feed-selection controls and optional remembered defaults on new-rule creation.
- Full pytest and manual validation are still pending in a fully provisioned development environment.

## Next actions

- Run route and form pytest coverage, then the full pytest suite, in the normal development environment.
- Manually verify `/rules/new` feed `Select all` / `Clear all` controls and remembered default feed behavior.
- Decide whether remembered defaults should also be editable from `/settings` in a follow-up phase-4 slice.
- Continue phase-4 refinement and close out any remaining taxonomy UI polish from phase 3 as separate follow-up work.

## Deferred / future phases

- Phase 4: feed UX improvements, including `Select all` and remembered default feed selections

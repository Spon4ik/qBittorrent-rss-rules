# Current Status

## Current focus

- Phase 3: taxonomy management UI

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

## In progress

- Phase 3 is started with a server-rendered edit/validate/apply flow; richer UX refinement is still open.
- Full pytest and manual validation are still pending in a fully provisioned development environment.

## Next actions

- Run the taxonomy service and route pytest coverage, then the full pytest suite, in the normal development environment.
- Manually verify the `/taxonomy` edit, validate, and apply lifecycle, including audit-log behavior and blocking-reference messaging.
- Revisit the `/taxonomy` UX for richer client-side editing feedback if the current server-rendered flow feels too coarse.
- After validation, mark the implemented Phase 3 slice complete and continue with remaining Phase 3 refinement or Phase 4 planning.

## Deferred / future phases

- Phase 4: feed UX improvements, including `Select all` and remembered default feed selections

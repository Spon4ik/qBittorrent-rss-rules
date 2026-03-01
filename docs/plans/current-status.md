# Current Status

## Current focus

- Phase 2: richer taxonomy schema

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

## In progress

- Phase 2 regression validation in a fully provisioned development environment.

## Next actions

- Run the targeted taxonomy pytest coverage and then the full pytest suite in the normal development environment.
- Perform manual UI verification for `/rules/new` and `/settings` to confirm the quality selector still renders and saves unchanged leaf tokens.
- Mark phase 2 complete after validation and activate phase 3 implementation.
- Begin phase 3 work using `docs/plans/phase-3-taxonomy-management-ui.md` as the implementation source of truth.

## Deferred / future phases

- Phase 3: taxonomy management and richer selector UI
- Phase 4: feed UX improvements, including `Select all` and remembered default feed selections

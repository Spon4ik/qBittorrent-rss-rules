# Current Status

## Current focus

- Phase 1: JSON-backed quality taxonomy loader

## Implemented

- Built-in `At Least UHD` filter profile can now be overwritten without duplicating the preset in the profile selector.
- Repo-local resumability instructions now live in `AGENTS.md`.
- Phase planning docs now live under `docs/plans/`.
- `app/data/quality_taxonomy.json` now stores the current quality taxonomy as an editable JSON source of truth.
- `app/services/quality_filters.py` now loads, validates, and caches taxonomy data from JSON while preserving current token behavior.
- `tests/test_quality_filters.py` now covers compatibility behavior, validation failures, and cache reset behavior for the taxonomy loader.
- Initial implementation plans for phases 2-4 now exist under `docs/plans/` to align roadmap intent with implementation-ready scope.

## In progress

- Final validation in a fully provisioned development environment (pytest and application dependencies are not available in the current shell).

## Next actions

- Install project dependencies and run the relevant pytest targets in the normal development environment.
- Perform manual UI verification for `/rules/new` and `/settings` to confirm the quality selector renders unchanged.
- Mark phase 1 complete after validation and activate phase 2 implementation.
- Begin phase 2 work using `docs/plans/phase-2-rich-taxonomy-schema.md` as the implementation source of truth.

## Deferred / future phases

- Phase 2: richer taxonomy schema (bundles, ranks, alias families, expanded groups)
- Phase 3: taxonomy management and richer selector UI
- Phase 4: feed UX improvements, including `Select all` and remembered default feed selections

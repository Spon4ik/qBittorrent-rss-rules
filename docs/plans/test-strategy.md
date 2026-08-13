# Test Strategy for Contract Protection

Last updated: 2026-05-07

## 1) Unit tests

- Quality taxonomy normalization and token resolution.
- Managed vs manual mode resolution logic.
- Preset inheritance math (especially rank-threshold resolutions).
- Rule save normalization idempotency.

## 2) Integration tests (backend)

- Rule create/edit/save/load across mode boundaries.
- Taxonomy add/move/remove/apply impact on existing rules/profiles.
- Preset edits propagate to managed rules only.
- qB/Jackett unavailable scenarios preserve semantic fields.

## 3) UI/component tests

- Rule form mode indicator + explicit convert action behavior.
- Settings preset editor (matrix/tri-state interactions).
- Rules table density/responsive breakpoints.
- Error/empty/loading state actionability.

## 4) Regression suites (must keep)

- Quality filter regressions already in `tests/test_quality_filters.py`.
- Route save/search regressions in `tests/test_routes.py`.
- Jackett payload/filter regressions in `tests/test_jackett.py`.
- Snapshot and rule fetch regressions in `tests/test_rule_fetch_ops.py`.
- qB enforcement parity regressions in `tests/test_rule_builder.py` and `tests/test_sync_service.py`.

## 5) Migration/default handling tests

- Runtime taxonomy seeding and persistence protection.
- Legacy rule rows containing preset + token snapshots.
- Additive schema migrations preserving existing semantics.

## 6) Rule save/load tests

- No-op edit retains all semantic fields.
- Managed mode remains managed after save/reopen.
- Manual mode retains explicit tokens exactly.

## 7) Taxonomy update tests

- Adding tokens updates managed-effective sets when contract says so.
- Removing referenced tokens blocks apply or requires explicit migration path.
- Reordering rank changes threshold-derived includes/excludes deterministically.

## 8) Preset inheritance tests

- Rules linked to `At Least Full HD` and `Ultra HD HDR` retain linkage across taxonomy and preset edits.
- Converted manual rules remain independent from future preset edits.

## 9) qB enforcement parity tests

- Generated qB RSS patterns must reject releases excluded by effective local rule semantics, including runtime-taxonomy resolution additions such as `400p`.
- Sync must persist the exact qB payload sent after successful rule sync.
- Sync-all drift checks must record the stale remote qB payload before repairing qB from local rule semantics.
- Edit-rule diagnostics must expose last synced qB payload and last observed remote drift payload so UI-visible rule state can be compared with qB enforcement state.

## 10) Responsive/layout tests

- Automated browser checks at narrow/medium/wide widths on `/`, `/rules/new`, `/settings`, `/taxonomy`, `/search`.
- Assert no clipped primary actions and no unintended horizontal overflow.

## 11) Suggested first tests to add

1. `test_rule_managed_mode_persists_after_taxonomy_add_value`.
2. `test_rule_managed_mode_persists_after_preset_edit`.
3. `test_rule_save_noop_is_semantically_idempotent`.
4. `test_settings_preset_editor_roundtrip_preserves_tri_state` (after UI redesign).
5. Responsive smoke snapshots for rules/settings widths.

## 12) Queue safety tests

- No-rule Queue requests without an override add paused even when a legacy
  settings row contains `default_add_paused=false`.
- A saved rule with `add_paused=false` remains an explicit rule exception.
- An individual Queue request can explicitly override either effective value.
- The defaults page exposes no global unpaused switch; rule and Queue surfaces
  label the two allowed exception scopes clearly.

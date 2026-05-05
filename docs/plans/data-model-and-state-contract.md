# Data Model and State Contract

Last updated: 2026-05-05

## 1) Canonical object model

- **Rule** (DB): identity, media semantics, matching fields, quality mode + tokens/profile, feed/language scope, qB sync state.
- **AppSettings** (DB): integration endpoints/secrets, default behavior, stored profile rules, sync scheduler state.
- **RuleSearchSnapshot** (DB): persisted search payload/results and release cache metrics.
- **Taxonomy** (runtime JSON): option groups, options, bundles, aliases, ranks, audit trail.

## 2) Source of truth

- Rules/settings/snapshots: SQLite (`app/models.py`).
- Taxonomy definitions: runtime `data/quality_taxonomy.json` (seed from `app/data/quality_taxonomy.json`).
- Built-in profile keys/shape: app quality filter service + settings normalization.

## 3) Taxonomy contract

### Built-in/default values
- Seed taxonomy ships with defaults but must be copied into runtime location and then treated as mutable user-owned data.

### User-added values
- User-added taxonomy options are first-class, persisted, and must survive deploy/rebuild.
- Add/move/remove operations must preserve rank consistency and alias/bundle validity.

### Migration/default handling
- On startup/load, missing runtime taxonomy may be seeded from packaged default.
- Future migrations must merge, never blindly replace runtime user data.

## 4) Managed preset vs manual selection

### Managed preset model
- Persist a stable preset identifier (e.g., key/profile enum) as authority.
- Effective token set is derived at read/use time from current preset definition + taxonomy normalization.
- Optional cached token snapshot is non-authoritative and refreshable.

### Manual selection model
- Persist explicit include/exclude tokens as authoritative values.
- Preset identity is absent or explicitly marked custom/manual.

### Conversion rules
- Managed -> manual requires explicit user action (button/confirm).
- Manual -> managed requires explicit preset selection and conflict notice.
- No background normalization step may auto-convert mode.

## 5) Rule-specific overrides

- Overrides (keywords, must contain/not contain, season/episode floor, language/feed scope) are additive to selected mode.
- Overrides cannot silently nullify managed linkage.

## 6) Taxonomy/preset/rule relationship

1. Taxonomy defines token universe and pattern semantics.
2. Presets define policy subsets over taxonomy tokens.
3. Rules in managed mode reference preset policy.
4. Rules in manual mode reference concrete tokens.

## 7) Exact expected behavior: taxonomy changes

When taxonomy adds tokens:
- Managed rules inherit if preset logic includes/excludes those tokens by design (ex: rank-derived resolution thresholds).
- Manual rules remain unchanged unless user edits them.

When taxonomy removes tokens:
- System must detect affected profiles/rules.
- Apply should block or require explicit migration action; never silently drop referenced tokens.

When taxonomy order/rank changes:
- Managed preset effective sets may update according to threshold/rank semantics.
- Mode must remain unchanged.

## 8) Exact expected behavior: preset definition changes

- Managed rules update effective tokens immediately on next read/render/search/sync.
- Manual rules do not change.
- UI should show that change source is preset update, not rule edit.

## 9) Exact expected behavior: rule save

Save operation must:
1. Validate payload/schema.
2. Resolve intended mode explicitly from UI signal.
3. Persist canonical mode fields.
4. Normalize tokens only within mode boundaries.
5. Preserve unchanged fields exactly.
6. Avoid dependence on transient external availability for semantic fields (degrade with warnings, not destructive rewrites).

## 10) Backward compatibility rules

- Legacy rows with both preset and token snapshots must be interpreted deterministically:
  - If snapshot drift is explainable by taxonomy expansion only, keep managed linkage.
  - If explicit token edits indicate user override, treat as manual.
- Additive fields should default safely and avoid migration-time behavior flips.

## 11) Invalid states (must prevent)

- Rule indicates managed preset but no resolvable preset key.
- Rule marked manual while hidden preset key still mutates behavior.
- Persisted tokens include unknown values without warning/repair path.
- Taxonomy apply removes user-added values due to packaged-file overwrite.

## 12) Prevention controls for accidental managed/manual conversion

- Explicit mode enum persisted per rule (recommended hardening if currently implicit).
- Server-side guardrails in save/update normalization.
- Regression tests for taxonomy/preset updates preserving mode.
- UI affordance showing current mode + last conversion source.

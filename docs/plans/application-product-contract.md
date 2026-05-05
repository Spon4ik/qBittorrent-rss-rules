# Application Product Contract (qBittorrent RSS Rule Manager)

Last updated: 2026-05-05

## 1) Purpose

qBittorrent RSS Rule Manager is a local control-plane for authoring and operating precise qBittorrent RSS rules without direct raw qB JSON editing. The product must preserve user intent over time while taxonomy, preset definitions, feeds, and provider metadata evolve.

Core promise:
- A saved rule’s meaning is stable unless the user explicitly changes it.
- Managed presets remain managed until explicitly converted.
- Taxonomy updates extend capability without silently deleting user decisions.

## 2) Primary users and jobs-to-be-done

Primary user:
- Single-machine power user operating qBittorrent + Jackett + optional Jellyfin/Stremio sync.

Primary jobs:
1. Create an accurate rule quickly from structured fields.
2. Keep many rules readable, sortable, and operational from one workspace.
3. Update taxonomy/presets safely without breaking existing rules.
4. Validate and preview what a rule will match before and after changes.
5. Sync and troubleshoot drift/errors with qB clearly.

## 3) Main user flows

1. **Create rule**: metadata lookup -> choose media/range/filter mode -> choose managed preset or manual tokens -> preview/search -> save -> sync.
2. **Operate rules**: filter/sort list -> run search/snapshots -> queue selected -> bulk/scheduled fetch -> resolve sync errors.
3. **Maintain quality system**: edit taxonomy values + profile definitions -> preview impact -> apply with audit note -> verify inherited behavior on existing rules.
4. **Maintain integrations**: test/save qB/Jackett/Jellyfin/Stremio sync settings -> run sync now -> monitor status.

## 4) Page-by-page intended behavior

## Rules (`/`)
- Primary workspace for monitoring health and next actions.
- Must prioritize: sync state, release state, exact-match confidence, and direct actions.
- Must support table-first density with optional cards.
- Must expose bulk selection + batch fetch + schedule controls without modal churn.

## Rule form (`/rules/new`, `/rules/{id}`)
- Must support two explicit quality modes:
  - **Managed preset mode** (linked to preset key).
  - **Manual selection mode** (explicit include/exclude token sets).
- Mode transitions must be explicit user actions.
- Live preview/search assists editing but must not mutate persisted mode automatically.

## Search (`/search`, `/rules/{id}/search`)
- Must separate exact lane vs broader fallback lane semantics.
- Must provide local filter visibility (active chips + reason why rows are hidden).
- Queue actions must preserve provenance and avoid silent link substitution failures.

## Settings (`/settings`)
- Must separate integration settings from quality system settings.
- “Manage preset quality filters” must be compact and comparison-friendly.
- Saving settings must not rewrite unrelated rule semantics.

## Taxonomy (`/taxonomy`)
- Must support safe add/move/remove and raw JSON edit.
- Must preview impact before apply and block destructive orphaning unless intentionally overridden in a future dedicated flow.
- Must preserve user-added values across code updates and restarts.

## Import (`/import`)
- Must clearly explain import mode semantics and collision handling.

## 5) Lifecycle contracts

## Rule lifecycle
- States: draft -> saved -> synced/unsynced/error -> updated/disabled/deleted.
- Required stable identity: `rule.id`, `rule_name` uniqueness.
- Persisted semantics must survive reload, restart, and taxonomy updates.

## Profile lifecycle
- Built-in profiles are system-defined defaults, user-tunable through settings.
- Custom profiles are user-owned and persist independently.
- Profile edits should propagate to managed rules referencing that profile key.

## Preset lifecycle
- Preset has stable key + mutable token definition.
- Rules linked by key inherit future preset definition changes.
- Explicit conversion to manual snapshots tokens at conversion time.

## Taxonomy lifecycle
- Runtime taxonomy file is source of truth for option/bundle/rank/alias resolution.
- Add/move/remove must be audited and previewed.
- Removal that would orphan persisted tokens is a guarded/destructive path.

## Search/matching lifecycle
- Build query from rule + profile/taxonomy context.
- Fetch results, evaluate exact/fallback semantics, persist snapshot.
- Local filtering visibility reasons must stay explainable.

## Validation lifecycle
- Form validation (schema), semantic validation (taxonomy/profile compatibility), integration validation (qB/Jackett/Jellyfin/Stremio sync).

## Save/load lifecycle
- Every save roundtrip must be idempotent for unchanged fields.
- Hidden/default fields must not unintentionally overwrite user state.

## Persistence/import/export lifecycle
- DB is source of truth for rules/settings/snapshots.
- Runtime taxonomy JSON is source of truth for taxonomy.
- Import must map external JSON to contract fields with explicit normalization rules.

## 6) Error/empty/loading states

- Empty states must include next step CTA.
- Integration failures should expose actionable cause and remediation.
- Background operations must provide last status/time and non-blocking UX.

## 7) Destructive action rules

Must always require explicit confirmation:
- Rule delete (local + remote consequences).
- Taxonomy remove/apply changes that could orphan persisted references.
- Preset/profile deletion (if supported later) with affected-rule counts.

## 8) Allowed vs forbidden silent transitions

Allowed silent transitions:
- Snapshot freshness metadata updates.
- Derived display labels/ordering changes that do not alter rule semantics.

Forbidden silent transitions:
- Managed preset mode -> manual mode.
- Rule include/exclude token changes without explicit user intent.
- Taxonomy apply that drops user-added values due to source reset.
- Language/feed scope erasure when external service is temporarily unavailable.

## 9) Progressive disclosure

Always visible:
- Rule identity, mode, sync status, actionable errors, core filters.

Progressively disclosed:
- Advanced keyword groups, provider-specific search fields, raw JSON editors, deep diagnostics.

## 10) Glossary

- **Managed preset mode**: rule stores preset identity and inherits updates by key.
- **Manual selection mode**: rule stores explicit token lists independent of preset updates.
- **Taxonomy token**: normalized quality/source/codec/etc. value key.
- **Exact lane**: high-confidence match set tied closely to intended content identity.
- **Fallback lane**: broader candidate set for manual review.

# Status and Phase Templates

## Current-Status Update Template

Use this format to keep `docs/plans/current-status.md` resumable.

```md
## Current focus

- <active phase or validation focus>

## Implemented

- <what is complete and landed>

## In progress

- <what is actively underway and not done>

## Next actions

- <next concrete step 1>
- <next concrete step 2>

## Deferred / future phases

- <optional: explicitly deferred items>
```

## Active Phase Plan Update Template

Use this format to keep `docs/plans/phase-<n>-*.md` aligned with reality.

```md
## Status

- <implementation state>
- <what changed since last update>
- <what remains>

## Proposed implementation

1. <slice 1 with paths>
2. <slice 2 with paths>

## Acceptance criteria

- <criterion 1>
- <criterion 2>

## Validation checklist

- [ ] <automated check>
- [ ] <manual validation>
```

## Session Closeout Checklist

- Update `docs/plans/current-status.md`.
- Update the active phase plan(s) touched by the work.
- Update `ROADMAP.md` only if phase scope or sequencing changed.
- Ensure next actions are concrete enough for immediate resume.

# Phase 42 - Paused-by-default queue safety

## Status

Implemented and release-validated for v1.4.14.

PR `#39` is merged, annotated tag `v1.4.14` is pushed, and the GitHub Release is
published.

## Contract

Every qBittorrent Queue action adds paused unless the user explicitly chooses
one of two exception scopes:

1. uncheck pause for this individual Queue action; or
2. save `Add paused` off on a specific rule.

The legacy global `default_add_paused` setting is retained only for storage and
backward compatibility. It is no longer consulted for no-rule queue actions,
is normalized to true on defaults saves, and has no UI control.

## Implementation

- Queue resolution order is request override, saved rule value, then `true`.
- New rules always start paused, independent of legacy settings state.
- Search Queue controls remain checked and clearly identify their one-time scope.
- Rule forms clearly identify the saved per-rule scope.
- Defaults settings no longer offer a global unpaused switch.
- The deterministic browser harness was aligned with the current defaults page
  and settings-hub markup discovered during completion verification.

## Validation

- Focused queue/defaults/UI slice: 15 passed.
- Full gate: Ruff and mypy clean; 545 tests passed.
- WinUI Debug/x64 build: zero warnings and zero errors.
- Shared Docker rebuild: healthy; `/health` reports `v1.4.14`.
- Live HTTP surfaces: new-rule pause is checked and defaults exposes no global
  pause control.

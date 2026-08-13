# Phase 41 - Persistent dark mode

## Status

Implemented and live-validated as the v1.4.13 patch candidate.

## Problem

The web UI has only a light palette. It needs a dark appearance that remains
selected across navigation and reloads without flashing the light theme first.

## Decision

- Add a header theme control available on every web page.
- Support Light, Dark, and System modes; cycle through them from one compact,
  keyboard-accessible button.
- Persist the preference in browser local storage because theme is a per-browser
  presentation preference rather than shared backend configuration.
- Apply the stored preference in the document head before CSS renders and react
  to operating-system theme changes while System mode is selected.
- Define semantic dark palette tokens and explicit overrides for legacy light
  surfaces, tables, dialogs, forms, status panels, and sticky controls.

## Acceptance criteria

- [x] Theme control is present and keyboard accessible on every page.
- [x] Light, Dark, and System modes cycle and persist across navigation/reload.
- [x] Stored dark mode is applied before the main stylesheet loads.
- [x] System mode follows `prefers-color-scheme` changes.
- [x] Forms, tables, cards, navigation, status surfaces, focus indicators, and
      native controls remain readable in dark mode.
- [x] Dark mode has no horizontal overflow at narrow, medium, or wide widths.
- [x] Automated route/source and browser regressions pass.
- [x] Full gate, desktop build, Docker rebuild, and live health pass.
- [ ] Patch release is published.

## Validation evidence

- `cmd.exe /c scripts\\check.bat`: Ruff and mypy clean; `542 passed`.
- Focused defaults/theme route suite: `6 passed`.
- Shared Docker `/health`: `status=ok`, `app_version=1.4.13`.
- `scripts\\run_dev.bat desktop-build`: succeeded with zero warnings/errors.
- Live Playwright on `/settings/defaults`: System follows emulated dark OS;
  Light and Dark persist through local storage and navigation; the page renders
  `Manage preset quality filters` with no qBittorrent provider field; no page
  overflow at 390px, 1180px, or 1720px.
- Rendered screenshot: `logs/qa/phase-41-live-dark.png`.
  Visual inspection confirmed the quality-profile matrix uses dark surfaces and
  readable selected/unselected slider states rather than legacy light colors.

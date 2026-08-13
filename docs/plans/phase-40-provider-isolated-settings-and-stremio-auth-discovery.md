# Phase 40 - Provider-isolated settings and Stremio auth discovery

## Status

Implemented, live-validated, and published as `v1.4.12` on 2026-08-13.

## Problem

The settings page is one large HTML form and provider-specific actions validate
and apply the full `SettingsFormPayload`. Testing or syncing Stremio can therefore
fail because an unrelated Jellyfin, MyJDownloader, metadata, or quality field is
invalid, and save-like provider actions can overwrite unrelated persisted fields
with omitted/default form values.

Current Stremio Desktop WebView2 storage also persists the signed-in auth value in
a Chromium LevelDB record representation rather than the JSON object shape used
by the existing extractor. The live record contains an `auth` key followed by
LevelDB metadata and a quoted base64url-like value, so the app reports that no
signed-in auth key exists even while Stremio is signed in.

## Decisions

- Give each integration its own settings screen and HTML form so the browser
  submits only fields owned by that integration.
- Validate provider actions with provider-specific payload schemas and update
  only provider-owned model attributes. Omitted unrelated fields must always be
  preserved.
- Keep the existing full settings endpoint as a compatibility path while the UI
  moves to isolated screens.
- Recognize both the historical JSON auth object and the current Chromium
  LevelDB auth-record encoding. Keep tokens secret and require a constrained
  token shape before accepting a match.
- Preserve keyboard navigation, visible headings, error/success recovery, and
  usable narrow-screen layout on every settings screen.

## Acceptance criteria

- [x] Stremio Test and Save + Sync validate/update only Stremio fields.
- [x] Jellyfin actions validate/update only Jellyfin fields.
- [x] MyJDownloader actions validate/update only MyJDownloader fields.
- [x] Other integration screens cannot overwrite sibling provider fields.
- [x] Each integration has a distinct settings URL and navigation entry.
- [x] Existing saved secrets remain unchanged when their password/key input is blank.
- [x] Historical JSON and live Chromium LevelDB Stremio auth shapes both pass
      focused extraction tests without exposing token values.
- [x] The live signed-in Stremio storage passes Test Stremio from Docker.
- [x] Browser QA proves provider isolation and useful error/success rendering.
- [x] Full gate, desktop build, Docker rebuild, and `/health` version readback pass.
- [x] Phase/status documentation and the patch release are complete.

## Validation evidence

- Focused Stremio extraction covers historical JSON and live-shaped Chromium
  LevelDB records.
- Route regressions prove unrelated invalid fields do not block Test Stremio and
  Stremio save preserves Jellyfin and encrypted MyJDownloader state.
- Full release gate passes with Ruff/mypy clean and `538 passed`.
- WinUI desktop builds with zero warnings and errors.
- Shared Docker `/health` serves `v1.4.12`.
- Live Docker Stremio readback resolves local-storage authentication and returns
  `520` library items, `318` active.
- Headless browser QA found seven provider screens, exact provider-owned form
  fields on every screen, zero narrow-viewport horizontal overflow, and a live
  Test Stremio success response.
- Live qBittorrent Test returns to the dedicated qBittorrent screen with its
  success message and no Stremio fields. A stale SQLite WAL/SHM state exposed by
  the final overlapping rebuild was moved aside recoverably; `PRAGMA quick_check`
  is `ok`, all `355` rules remain, and Docker health is green.
- PR `#37` is merged; annotated tag `v1.4.12` is pushed; and the GitHub Release
  is published.

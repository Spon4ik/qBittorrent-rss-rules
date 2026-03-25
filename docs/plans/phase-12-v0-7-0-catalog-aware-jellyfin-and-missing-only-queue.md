# Phase 12: v0.7.0 Catalog-Aware Jellyfin Floors and Missing-Only Queue Selection

## Status

- Plan baseline created on 2026-03-25 from the post-`v0.6.1` planning gap plus the new Jellyfin/catalog/qB queue request.
- Phase 12 is now implemented and release-validated as the shipped `v0.7.0` release.
- Final closeout passed on 2026-03-25 via `cmd.exe /c scripts\check.bat` (`227 passed`, `57 warnings`), `cmd.exe /c scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T024210Z/`), and `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`).
- Scope is feature-focused but still compatibility-preserving: extend the current Jellyfin/qB contracts without breaking existing rule storage, existing queue actions, or current OMDb/Jackett defaults.

## Goal

Deliver a backward-compatible `v0.7.0` release that makes Jellyfin-derived series floors catalog-aware across season boundaries, remembers enough prior Jellyfin episode history to keep skipped content skipped after local file cleanup, and makes qB queue actions automatically prefer only the missing/unseen episode files when a queued result is a multi-file series torrent.

## Requested Scope (2026-03-25)

1. Detect when a Jellyfin-derived season floor has reached the real end of the season instead of blindly incrementing to a fake episode like `S01E11`.
2. Use an external episode catalog source to decide when the next floor should jump to the next season and start from episode `0` so `E00` specials are still caught.
3. Keep deleted-yet-already-seen Jellyfin episodes skipped without requiring a separate scrobbling product or manual operator memory.
4. Make `Add to queue` automatically select only missing/unseen episode files in qBittorrent when the queued result is a multi-file series torrent and rule context is available.
5. Close out the release only after targeted regressions plus full repo release gates are green.

## In Scope

- Catalog-aware season-finale detection for Jellyfin-derived series floors.
- OMDb-backed season episode lookup, reusing the existing metadata provider/API-key path when available.
- Persisted rule-side Jellyfin episode memory for prior watched/known episodes so later file deletion does not silently regress floors.
- Episode-`0` support for stored floors, generated patterns, and local/browser filtering parity.
- qB queue post-processing for rule-backed series results so multi-file torrents can be narrowed to missing/unseen episodes when file metadata is available.
- Queue response messaging/tests so selective-file behavior is transparent instead of implicit.
- Version bump, changelog/release docs, and validation evidence for `v0.7.0`.

## Out Of Scope

- Replacing Jellyfin as the watch-history source of truth.
- Full season/series calendar prediction beyond the data available from the configured metadata provider.
- General-purpose torrent file browser UX in the app.
- A new standalone scrobbling service or write-back integration into Jellyfin.
- Unrelated cleanup/module-split work except for small refactors required to land this phase safely.

## Key Decisions

### Decision: `v0.7.0` is a minor release, not a major release

- Date: 2026-03-25
- Context: The requested work adds new behavior and new persisted fields, but existing users can upgrade without mandatory config changes or incompatible route/schema breaks.
- Chosen option: release as `0.7.0`.
- Reasoning: The feature set is materially larger than a patch, but the app remains backward-compatible.
- Consequences: Version touchpoints should move from `0.6.1` to `0.7.0`, with upgrade notes focused on new Jellyfin/qB behavior rather than migration steps.

### Decision: season-boundary detection should reuse OMDb before adding a new provider

- Date: 2026-03-25
- Context: The app already has OMDb metadata plumbing and API-key storage, while the request only needs enough external catalog data to know whether a season has actually ended.
- Chosen option: use OMDb season episode lookups first, and fall back to the current numeric increment logic only when catalog lookup is unavailable.
- Reasoning: This keeps scope narrow, reuses existing operator setup, and avoids introducing a second video metadata dependency in the same release.
- Consequences: Catalog-aware jumps are best-effort unless an OMDb key is configured, and outcome messages/tests must cover the fallback path explicitly.

### Decision: deleted-file skip memory should be persisted inside rule state, not via a new scrobbling subsystem

- Date: 2026-03-25
- Context: The user frequently deletes watched/local episodes after viewing but still expects later searches and queue actions to skip them.
- Chosen option: persist remembered Jellyfin episode history on the rule itself during sync.
- Reasoning: This directly solves the operational problem with the least moving parts and keeps Jellyfin read-only.
- Consequences: The phase must add new persisted episode-memory fields plus sync logic that merges live Jellyfin rows with remembered history instead of trusting only current on-disk files.

### Decision: next-season jumps should start from episode `0`

- Date: 2026-03-25
- Context: Once a season is catalog-confirmed complete, incrementing to `S01E11` creates false season-pack matches and misses `E00` specials for the next season.
- Chosen option: when a season is complete, advance the stored floor to the next season at episode `0`.
- Reasoning: `S02E00` still matches `E01+` releases while also allowing specials and preventing the stale same-season `E11` false-positive path.
- Consequences: Start-episode validation and generated-pattern builders must accept `0` without reopening the previous zero-based range leak.

### Decision: missing/unseen-only qB file selection is automatic for rule-backed series queue actions

- Date: 2026-03-25
- Context: The user asked for queue actions to automatically prefer only the missing/unseen episodes when a queued result contains multiple files.
- Chosen option: when queueing from a saved series rule, automatically attempt per-file selection in qB; if the torrent structure cannot be inspected safely, keep the prior queue behavior and report that limitation clearly.
- Reasoning: The rule already contains the best available missing/unseen contract, so the app should apply it automatically instead of asking the operator to re-select files manually in qB.
- Consequences: The phase needs torrent-metadata/file-priority plumbing plus tests for safe selective cases, no-match cases, and fallback messaging.

## Acceptance Criteria

- Jellyfin sync no longer advances a finished `S01E10` season to a fake same-season floor like `S01E11` when external catalog data says season 1 ended there.
- Catalog-confirmed season boundaries advance the stored rule floor to `S(next)E00`.
- Episode `0` floors work consistently in server regex generation, browser regex generation, and local filtering.
- Rules can remember enough Jellyfin episode history that deleting previously seen files from disk does not regress skip behavior on the next sync.
- Rule-backed multi-file series queue actions can narrow qB downloads to missing/unseen episode files when file metadata is available, and they report when they had to fall back to whole-torrent queueing.
- Targeted Jellyfin, rule-builder, qB client, route, and selective-queue tests pass.
- Repo release gates pass before version closeout.

## Dated Execution Checklist (2026-03-25 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P12-01 | Add catalog-aware Jellyfin floor derivation and remembered episode history. | Codex | 2026-03-25 | completed | Jellyfin sync can keep deleted-yet-known episodes skipped and can jump to `S(next)E00` when a season is externally confirmed complete. | Implemented in `app/services/jellyfin.py`, `app/services/metadata.py`, `app/models.py`, and `app/db.py`; covered by `tests/test_jellyfin.py`, `tests/test_metadata.py`, focused `pytest`/`ruff`/`mypy`, and final `cmd.exe /c scripts\check.bat`. |
| P12-02 | Extend floor/pattern contracts to support episode `0` safely. | Codex | 2026-03-25 | completed | Stored rule payloads, generated regex, and browser local-filter parity all accept episode `0` without reintroducing the zero-based range leak. | Implemented in `app/services/rule_builder.py`, `app/static/app.js`, `app/schemas.py`, `app/templates/rule_form.html`, and related route surfaces; covered by `tests/test_rule_builder.py`, `tests/test_jellyfin.py`, focused `pytest`/`ruff`, and final `cmd.exe /c scripts\check.bat`. |
| P12-03 | Add automatic qB missing/unseen file selection for rule-backed series queue actions. | Codex | 2026-03-26 | completed | Queue actions can set qB file priorities for safe multi-file episode torrents and fall back clearly when file inspection is unavailable. | Implemented in `app/services/qbittorrent.py`, new `app/services/selective_queue.py`, `app/routes/api.py`, and `app/static/app.js`; covered by `tests/test_qbittorrent_client.py`, `tests/test_selective_queue.py`, `tests/test_routes.py`, focused `pytest`/`ruff`/`mypy`, and final `cmd.exe /c scripts\check.bat`. |
| P12-04 | Revalidate repo gates for the new Jellyfin/qB contract. | Codex | 2026-03-26 | completed | Targeted suites plus full release validation pass on the final worktree. | Focused `pytest`/`ruff`/`mypy` passed during implementation; final release validation passed via `cmd.exe /c scripts\check.bat` (`227 passed`, `57 warnings`), `cmd.exe /c scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T024210Z/`), and `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`). |
| P12-05 | Close out docs and release touchpoints for `v0.7.0`. | Codex | 2026-03-26 | completed | Version touchpoints, roadmap/current-status, changelog, and release notes match the shipped behavior. | Updated `pyproject.toml`, `app/main.py`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, `docs/plans/README.md`, and this phase plan for the shipped `0.7.0` release. |

## Risks And Follow-Up

### Risk: OMDb may be unavailable or unconfigured on installs that still want season-boundary jumps

- Trigger: Catalog-aware season completion depends on OMDb responses.
- Impact: Those installs fall back to numeric increment behavior instead of cross-season `E00` jumps.
- Mitigation: Keep the fallback explicit, preserve prior behavior when OMDb cannot help, and document the dependency in release notes.
- Owner: Codex
- Review date: 2026-03-26
- Status: open

### Risk: selective qB file selection is only as good as the torrent file names/metadata

- Trigger: Some results may expose only a magnet or ambiguous file names that do not identify episode numbers safely.
- Impact: The app may have to fall back to whole-torrent queueing or defer selection until metadata is available.
- Mitigation: Implement safe best-effort behavior, avoid silent partial selection when no desired files can be identified, and report fallback clearly.
- Owner: Codex
- Review date: 2026-03-26
- Status: open

## Next Concrete Steps

1. Decide whether installs without OMDb need a second catalog provider or a richer fallback source for season-boundary detection.
2. Decide whether deleted-history persistence should remain rule-local or graduate to a broader watch-history/scrobble-compatible cache.
3. Split the largest Jellyfin/search/queue modules before the next feature-heavy phase continues in this area.

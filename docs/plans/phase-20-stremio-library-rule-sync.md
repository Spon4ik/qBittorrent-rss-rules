# Phase 20: Stremio Library Sync And Native Addon Parity

## Status

- Plan baseline created on 2026-03-27 to open the deferred Stremio source-adapter phase after the shared watch-state foundation from phase 17.
- Phase 20 is now closed and release-validated in `v0.8.0`.
- Implementation landed on 2026-03-27 across the settings/model/service/route/template/test stack for local Stremio discovery, authoritative library sync, Stremio-managed rule creation/linkage, qB push orchestration, and background auto-sync while the app runs.
- A desktop-shell follow-up landed on 2026-03-27 so the WinUI host now rejects same-version backends that do not expose the Stremio capability set and the explicit `Shut Down Engine` action can stop the active loopback backend even when that process was not launched by the current in-memory desktop session.
- Scope expanded on 2026-03-27 to include the first centralized movie-completion watch-state slice, so completed-movie evidence from Jellyfin, Stremio, and future providers can flow into one generic rule auto-disable path instead of each adapter owning its own movie disable logic.
- Scope expanded again on 2026-03-28 to include a first native Stremio addon slice so Stremio search and stream requests can reuse this app's own metadata and Jackett search logic instead of depending on a separate external `jackett-stremio` container with different filtering defaults.
- Focused regression coverage for the library-sync slice is passing, and the first native addon implementation/validation work also landed on 2026-03-28.
- A same-day live-integration follow-up also landed on 2026-03-28 to add Stremio addon CORS headers, surface the exact active-backend manifest URL on `/settings`, require the native-addon capability in the WinUI shell, and make desktop shutdown stop every identified local qB RSS backend in the managed loopback range instead of only the last remembered PID.
- Live Windows inspection on 2026-03-28 confirmed the remaining shutdown bug was an orphaned-worker pattern: backend `/health` listeners survived on `8000` and `8006` through spawned Python worker PIDs even after their recorded parent PIDs were already gone, so the desktop cleanup path now targets both the identified backend port-owner PID and associated `multiprocessing.spawn` workers.
- A same-day addon stream follow-up also landed on 2026-03-28 after live probing showed installed qB RSS addon pages still contributed no streams for `The Beauty`: the addon had been discarding Jackett results that only exposed HTTP `.torrent` download links, so `app/services/stremio_addon.py` now downloads/parses torrent metadata to recover the info-hash, and live verification against `http://127.0.0.1:8000/stremio/stream/series/tt33517752:1:1.json` now returns qB RSS streams from the running backend.
- A second live addon follow-up landed later the same day when route timing turned out to be the next blocker: the native stream route took about `92s` on `The Beauty` because it serially inspected too many Jackett torrent-file links, which is too slow for practical Stremio addon requests; the route now uses a bounded response budget, a short per-torrent timeout, and an early-return target count, bringing the same live route down to about `7.7s` while still returning the top qB RSS streams.
- A third live addon follow-up landed after comparing qB RSS and Torrentio stream payloads for the same episode: qB RSS was still returning season-pack torrents without `fileIdx` / `behaviorHints.filename`, while Torrentio's visible episode streams included both; the addon now picks the requested episode file from parsed torrent contents and returns those fields, so the live qB RSS stream payload now points directly at `The.Beauty.S01E01...` instead of an unspecified largest-file fallback.
- A fourth live addon follow-up landed after comparing qB RSS and Torrentio torrent-source details for the same episode: qB RSS only returned `dht:` in `sources`, while Torrentio also advertised tracker announce URLs; torrent parsing now preserves `announce` / `announce-list` trackers and the addon forwards them as Stremio `tracker:` sources, so the live qB RSS stream payload now looks much closer to the provider shape Stremio already accepts from Torrentio.
- A fifth live addon follow-up landed after comparing `The Beauty` episode 1 and episode 4 responses: the exact-episode Jackett query for later episodes was too narrow and missed season packs that clearly contained the requested file, so the addon now adds a season-level fallback search for episode requests and only keeps broad matches that either title-match the target episode or whose parsed torrent contents actually contain it; the live route for episode 4 now returns the same 4K season pack with the correct `fileIdx` instead of falling back to a single 1080p release.
- A sixth live addon follow-up landed later on 2026-03-28 after request logging proved Stremio was already calling `/stremio/stream/...` from the desktop client but the addon still did not show in the UI: the route was returning too slowly while it chased a second stream through several slow HTTP torrent candidates, so `app/services/stremio_addon.py` now uses a shorter per-torrent timeout, returns a single best candidate, adds an episode text-search fallback (`Title SxxExx`) for Stremio-specific public-magnet parity, and ranks magnet/public-torrent results ahead of private HTTP `.torrent` results; focused validation still passes and the live HTTP route for `tt33517752:1:1` now logs about `2625 ms` with one qB RSS public magnet stream (`1441b5e1...`) rather than about `5203 ms` with slower private-torrent-heavy results.
- A seventh live addon follow-up landed later on 2026-03-28 after stale one-stream JSON captures and missing Stremio UI rows persisted even though the backend response shape was correct: the addon now publishes a fresh addon identity/version (`org.qbrssrules.stremio.local`, `0.8.0+stremio.1`) to force a clean reinstall path, Stremio stream/meta lookups now use short-lived in-memory caches to keep repeated item opens fast, and stream metadata resolution now prefers Cinemeta for IMDb-backed Stremio item pages before falling back to the configured metadata provider so invalid OMDb state does not add avoidable latency.
- Live verification after that seventh follow-up now returns two qB RSS streams again for both `tt33517752:1:1` and `tt33517752:1:4` from the active `:8000` backend, including the public 1080p single-episode magnet plus the 4K season-pack stream with the correct `fileIdx`; the first live hit still takes about `3.1s`, but warm-cache repeats for the same item now fall to about `10-16 ms`.
- An eighth live addon follow-up landed later the same day after the first Stremio-origin request with the new addon identity still logged about `10516 ms`: episode exact IMDb search and Stremio-oriented text search are now collected in parallel with a tighter search-collection budget, so cold episode requests stop waiting on the slowest Jackett path before returning the best available streams. After a clean backend restart, live verification now returns `tt33517752:1:1` in about `3351 ms` while still including both the public 1080p magnet and the 4K season-pack stream.
- A ninth same-day follow-up added `scripts/stremio_addon_smoke.py` so addon regressions can be checked repeatedly without manual browser JSON comparisons: the script exercises the addon in-process and over live HTTP, reports cold/warm timings plus returned hashes/tags for the known regression items, and is now the preferred backend-side acceptance check before asking for another real Stremio UI retest.
- A tenth same-day follow-up added real Stremio desktop automation on 2026-03-28: `scripts/stremio_desktop_smoke.py` now drives the installed Stremio desktop app over WebView2 CDP, reinstalls the requested manifest, opens a real detail page, and records visible stream rows, source-filter options, all `/stream/` provider responses, hash-overlap summaries, and browser console/page errors. The smoke now proves the live qB RSS issue more precisely: on the real `The Beauty` episode page, Stremio requests `http://127.0.0.1:8000/stremio/stream/series/tt33517752%3A1%3A1.json`, receives `2` qB RSS streams with hashes `1441b5e1ef5d61cf6447d06705623a219fb1aaf8` and `1b9e36302ba0f0dd73b9f5ed245ff3a1bd940acf`, and still renders only `Torrentio` plus `IMDb Rating`; the captured overlap summary confirms those qB RSS hashes do not overlap with the `22` Torrentio hashes returned during the same page load.
- An eleventh same-day follow-up added `scripts/stremio_desktop_variant_matrix.py` as a first mock-variant bisect harness for the same real desktop flow; it can stand up a temporary local mock addon and feed payload variants (`jackett_live`, `qbrss_live`, `qbrss_minimal`, `qbrss_first_stream_only`) through the real desktop smoke path without asking the user to reinstall by hand each time, although the first run shows the mock addon still needs an install-path tweak before it reaches the stream-request stage.
- A twelfth same-day follow-up closed the remaining desktop acceptance gap on 2026-03-28: real desktop bisecting showed Stremio would accept the qB RSS streams only when the payload matched a leaner contract, so `app/services/stremio_addon.py` now emits the simplified Stremio-compatible shape that the variant matrix proved viable; the final real desktop smokes against `http://127.0.0.1:18086/stremio/manifest.json` now render `qB RSS Rules 1080p` and `qB RSS Rules 2160p` on `The Beauty` for both `tt33517752:1:1` and `tt33517752:1:4`.
- A thirteenth release-closeout follow-up landed later on 2026-03-28 after the live `:8000` backend briefly reproduced stale empty payloads: `app/services/stremio_addon.py` no longer caches empty stream responses, so transient Jackett misses no longer leave the running addon looking broken until a manual backend restart; focused regression coverage now proves a second request can recover once results are available again.
- Phase closeout is complete with green release gates and no remaining blockers for the delivered `v0.8.0` scope; remaining work is now post-release follow-up rather than part of the phase-20 acceptance path.

## Goal

Deliver the first Stremio integration slice so the app can automatically create qB-backed rules for the user's Stremio library items, keep linked rules synchronized as the library changes, push those local rule changes through the existing qB sync path without requiring manual one-off imports, and expose a native Stremio addon endpoint that reuses this app's search stack for better title discovery and stream parity.

## Requested Scope (2026-03-27)

1. Automatically create a saved rule for every active Stremio library title that does not already have one.
2. Keep those Stremio-linked rules up to date as titles are added to or removed from the Stremio library.
3. Surface manual test/sync controls plus automatic background sync from the app settings page.
4. Reuse the existing qB rule sync path so Stremio-driven local changes are pushed to qB immediately when qBittorrent is configured.
5. Centralize completed-movie rule disablement so provider adapters record watch-state evidence in one shared rule state and one shared arbitration path decides whether the movie rule should stay enabled.
6. Expose a native Stremio addon manifest from this app so Stremio can install the addon directly from the same backend that already powers the RSS-rule workflow.
7. Support Stremio search catalogs for movies and series so titles missing from Stremio's default search can be surfaced through this app's metadata provider path.
8. Support Stremio stream lookups for IMDb-backed movie and episode IDs by reusing this app's Jackett search pipeline and returning Stremio-compatible torrent stream objects ordered for playback relevance.

## In Scope

- Stremio desktop session discovery from the local machine, with an optional override path when auto-discovery is not enough.
- Local extraction of the Stremio auth token from the desktop WebView storage.
- Read-only calls to the official Stremio API (`datastoreGet` / `datastoreMeta`) for authoritative library state.
- Rule create/link/update behavior for Stremio `series` and `movie` library items.
- Tracking fields that distinguish Stremio-managed rules from ordinary/manual rules.
- Automatic disable/re-enable behavior for Stremio-managed rules when a title leaves or returns to the Stremio library.
- Centralized completed-movie watch-state storage on the rule itself so provider adapters can contribute completion evidence without each one owning final enable/disable decisions.
- Jellyfin and Stremio adapter updates that feed the shared completed-movie state for movie rules.
- Settings UI/API, service-layer sync orchestration, and background auto-sync while the app is open.
- Native Stremio addon manifest plus search-only catalog routes for `movie` and `series`.
- Native Stremio stream routes that accept IMDb movie IDs and IMDb-based series video IDs (`tt...:season:episode`).
- OMDb-backed metadata search reuse for catalog results and Jackett-backed stream reuse for torrent results.
- Focused pytest coverage for the Stremio service, route flows, settings normalization, and auto-sync scheduler behavior.

## Out Of Scope

- Stremio watched-progress or continue-watching floor arbitration.
- Writing back to Stremio or modifying the remote library from this app.
- Add-on/catalog/provider expansion beyond what is already present in the user's Stremio library.
- Cross-device Stremio auth flows that do not have a local desktop session or explicit override available.
- Series watched-progress arbitration beyond the already-shipped shared episode-floor helpers from phase 17.
- A custom Stremio `meta` implementation for IMDb-backed items when Cinemeta already owns that responsibility.
- Subtitle resources, addon publishing/distribution beyond the local manifest URL, or a Stremio `/configure` user-settings page.
- Non-IMDb Stremio ID handling beyond safe empty responses for unsupported identifiers.

## Key Decisions

### Decision: use the authoritative Stremio API for library state, not only the local cache

- Date: 2026-03-27
- Context: The desktop WebView storage contains `library_recent`, but Stremio itself fetches the full library through the official API.
- Chosen option: use local storage only to discover auth/session context, then pull the library from `https://api.strem.io/api/datastoreGet`.
- Reasoning: This matches Stremio's own contract and avoids treating the recent-library cache as the full source of truth.
- Consequences: The implementation needs both local discovery logic and an HTTP client path, plus careful error handling when the token is missing or stale.

### Decision: use `datastoreMeta` for change detection and `datastoreGet` for full sync

- Date: 2026-03-27
- Context: Re-fetching the entire Stremio library every poll would work, but the API exposes a lighter metadata endpoint that reports per-item modification times.
- Chosen option: poll `datastoreMeta` to detect remote library changes and only run a full `datastoreGet` sync when the library signature changes or a sync is forced.
- Reasoning: This keeps the background sync efficient while still using the authoritative remote library state.
- Consequences: The auto-sync service must track the last seen remote signature in memory for the current app session.

### Decision: auto-create Stremio-managed rules, but link compatible manual rules instead of duplicating them

- Date: 2026-03-27
- Context: Some library titles may already have local rules created manually or through other workflows.
- Chosen option: match existing rules by Stremio library item ID first, then by IMDb ID, then by normalized title + media type; create a new rule only when no compatible rule exists.
- Reasoning: This avoids duplicate rules while still letting the feature backfill the user's existing library.
- Consequences: The service must preserve user-authored rule settings when linking an existing rule and reserve the stronger automatic behavior for rules the Stremio sync created itself.

### Decision: removed library titles should disable only Stremio-managed rules automatically

- Date: 2026-03-27
- Context: A title leaving the Stremio library should stop auto-managed matching, but linked manual rules should not be silently overridden.
- Chosen option: rules auto-created by this phase are marked as Stremio-managed and can be auto-disabled/re-enabled when the library membership changes; linked pre-existing rules remain user-owned.
- Reasoning: This keeps automatic behavior predictable without taking over rules the user already manages intentionally.
- Consequences: Rule state needs explicit Stremio linkage and management flags.

### Decision: desktop/backend compatibility must include capability checks, not only version checks

- Date: 2026-03-27
- Context: During live use, the WinUI desktop could reconnect to an older `0.7.6` backend that still lacked the new Stremio routes because the shell only validated `app_version` plus the desktop contract date.
- Chosen option: keep the existing version/contract validation, but additionally require the backend to advertise the expected capability list from `/health`, including `stremio_library_sync`.
- Reasoning: This fail-closes the desktop onto stale same-version backends and forces it to start or reconnect to a backend that actually supports the new feature slice.
- Consequences: Desktop follow-up changes are part of the Stremio rollout contract even though the underlying bug manifested in the shell lifecycle layer.

### Decision: completed-movie auto-disable should be centralized across providers

- Date: 2026-03-27
- Context: Jellyfin movie disablement and Stremio watch-state evidence were diverging into provider-specific behavior, while the shared watch-state foundation from phase 17 already established the direction toward source-agnostic arbitration.
- Chosen option: store provider-reported movie completion sources centrally on the rule and let a shared module decide whether the rule should auto-disable or re-enable.
- Reasoning: This matches the product expectation that finishing a movie in any connected platform should affect one shared rule state, and it keeps future providers from duplicating the same movie-completion logic again.
- Consequences: Phase 20 now includes a small cross-provider watch-state extension, plus a behavior change from Jellyfin's earlier movie-library-presence disablement toward real completed-movie evidence.

### Decision: the first native addon slice should implement `catalog` + `stream`, while deferring custom `meta`

- Date: 2026-03-28
- Context: Stremio can already resolve detailed metadata for IMDb-backed movies and series through Cinemeta, while this app mainly needs to improve missing-title discovery and stream parity with the RSS-rule search path.
- Chosen option: expose search-only Stremio catalogs that return IMDb-backed meta previews plus stream routes for IMDb movie IDs and IMDb-based series video IDs, but defer a custom `meta` resource for now.
- Reasoning: This lands the user-visible search/stream improvement with much less implementation risk than owning full series metadata and episode inventories ourselves, and it keeps the addon aligned with Stremio's built-in IMDb metadata model.
- Consequences: The native addon will rely on a metadata provider only for search previews, while detail-page metadata and episode lists continue to come from Cinemeta for IMDb-backed items.

### Decision: addon stream ranking should favor playback-relevant quality ordering instead of raw publish date

- Date: 2026-03-28
- Context: The existing app preserves Jackett results deterministically, but Stremio stream lists should surface the best candidate first rather than simply the newest published item.
- Chosen option: build a Stremio-specific result ranking layer on top of the normalized Jackett results that favors stronger quality markers, then seeders, then recency.
- Reasoning: This better matches how users evaluate playback options inside Stremio and avoids presenting lower-quality but newer uploads ahead of obviously better 2160p/HDR releases.
- Consequences: The native addon will reuse the existing Jackett fetch logic but not the exact ordering semantics used by the browser search UI.

## Acceptance Criteria

- The app can discover the local Stremio desktop session (or honor an explicit override path) well enough to pull the user's Stremio library from the official API.
- A manual Stremio sync creates new rules for missing Stremio `series` and `movie` library items using the app's current default rule settings.
- A manual Stremio sync links compatible existing rules without creating duplicates.
- Stremio-managed rules update their Stremio metadata linkage cleanly and auto-disable when their title is removed from the Stremio library.
- If qBittorrent is configured, changed rules from a Stremio sync are pushed through the existing `SyncService`.
- The settings page exposes Stremio test/sync controls plus automatic background sync status and cadence.
- Focused tests cover settings normalization, local discovery, Stremio sync behavior, route flows, and auto-sync change detection.
- The backend serves a Stremio addon manifest from a stable local route and advertises search-only movie and series catalogs plus stream support for IMDb-backed items.
- Catalog search requests return Stremio-compatible meta previews for matching movie/series titles by reusing the configured metadata provider path.
- Stream requests for IMDb movies and IMDb series episode IDs return Stremio-compatible torrent stream objects sourced from the app's Jackett search pipeline.
- Focused tests cover the addon manifest contract, catalog search behavior, stream route behavior, and graceful empty responses for unsupported or misconfigured cases.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P20-01 | Add Stremio settings/config and rule linkage fields. | Codex | 2026-03-27 | complete | The DB/model/settings/schema layer can persist Stremio sync configuration, background status, and Stremio-linked rule metadata. | Landed in `app/config.py`, `app/models.py`, `app/db.py`, `app/schemas.py`, and `app/services/settings_service.py`. |
| P20-02 | Implement local Stremio auth discovery plus authoritative library fetch. | Codex | 2026-03-27 | complete | The service can resolve the auth token from the local desktop storage, call the official Stremio library endpoints, and report connection/library state. | Landed in `app/services/stremio.py` with local `leveldb` auth discovery plus `datastoreGet` / `datastoreMeta` support and connection-summary reporting. |
| P20-03 | Implement rule create/link/update/disable behavior and qB push orchestration. | Codex | 2026-03-27 | complete | Manual Stremio sync creates or links rules, disables removed managed rules, and pushes changed rules to qB when configured. | Landed in `app/services/stremio.py` and `app/services/stremio_sync_ops.py`; covered by `tests/test_stremio.py` and route sync tests. |
| P20-04 | Wire the settings page/API and background auto-sync service. | Codex | 2026-03-27 | complete | The app exposes `Test Stremio` / `Save + Sync Stremio Now` actions and runs change-detected Stremio sync in the background while open. | Landed in `app/routes/api.py`, `app/templates/settings.html`, `app/main.py`, and `app/services/stremio_auto_sync.py`. |
| P20-05 | Add focused regression coverage and validate the feature slice. | Codex | 2026-03-27 | complete | Targeted pytest coverage passes for the new Stremio path and the changed settings/routes/services. | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_settings_service.py tests\\test_stremio.py tests\\test_stremio_auto_sync.py tests\\test_jellyfin_auto_sync.py tests\\test_routes.py -k "stremio or jellyfin or settings_service"` (`30 passed`, `81 deselected`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\main.py app\\routes\\api.py app\\services\\stremio.py app\\services\\stremio_sync_ops.py app\\services\\stremio_auto_sync.py tests\\conftest.py tests\\test_settings_service.py tests\\test_stremio.py tests\\test_stremio_auto_sync.py tests\\test_routes.py tests\\stremio_test_utils.py` (`All checks passed`). |
| P20-06 | Harden desktop routing compatibility for the Stremio rollout. | Codex | 2026-03-27 | complete | The desktop refuses stale same-version backends that lack the Stremio capability set, and explicit shutdown can stop the active loopback backend instead of only the process tracked in memory. | Landed in `QbRssRulesDesktop/Views/MainPage.xaml.cs`; validated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "health_endpoint or stremio or jellyfin"` (`12 passed`, `80 deselected`) and `dotnet build QbRssRulesDesktop/QbRssRulesDesktop.csproj -p:Platform=x64` (`0 Warning(s)`, `0 Error(s)`). |
| P20-07 | Add centralized movie-completion watch-state storage and arbitration. | Codex | 2026-03-27 | complete | Rule rows store provider-reported completed-movie sources and one shared helper decides the final auto-disable/re-enable state. | Landed in `app/services/watch_state.py`, `app/models.py`, and `app/db.py`; covered by `tests/test_watch_state.py`. |
| P20-08 | Feed centralized movie-completion state from Jellyfin and Stremio, then validate the behavior. | Codex | 2026-03-27 | complete | Finished movies disable the matching rule from either provider, while keep-search still overrides the auto-disable path and tests cover the shared behavior. | Landed in `app/services/jellyfin.py`, `app/services/stremio.py`, `app/routes/pages.py`, and `app/templates/rule_form.html`; validated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_watch_state.py tests\\test_jellyfin.py tests\\test_stremio.py tests\\test_routes.py tests\\test_jellyfin_auto_sync.py tests\\test_stremio_auto_sync.py tests\\test_settings_service.py -k "watch_state or jellyfin or stremio or movie_sync_copy or settings_service"` (`51 passed`, `81 deselected`), `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\watch_state.py app\\services\\jellyfin.py app\\services\\stremio.py app\\models.py app\\db.py app\\routes\\pages.py app\\routes\\api.py tests\\test_watch_state.py tests\\test_jellyfin.py tests\\test_stremio.py tests\\test_routes.py tests\\stremio_test_utils.py` (`All checks passed`), and `.\\.venv\\Scripts\\python.exe -m mypy app\\services\\watch_state.py app\\services\\jellyfin.py app\\services\\stremio.py app\\routes\\pages.py app\\routes\\api.py` (`Success: no issues found in 5 source files`). |
| P20-09 | Add a native Stremio addon service layer and manifest route. | Codex | 2026-03-28 | complete | The backend serves a Stremio manifest that advertises search-only catalogs plus stream support using the app's own backend URL. | Landed in `app/services/stremio_addon.py`, `app/routes/stremio_addon.py`, and `app/main.py` with `/stremio/manifest.json` plus the `stremio_native_addon` backend capability. |
| P20-10 | Add search-only Stremio catalog routes backed by provider metadata search. | Codex | 2026-03-28 | complete | Movie and series catalog search requests return IMDb-backed meta previews suitable for Stremio search surfaces. | Landed in `app/services/metadata.py`, `app/services/stremio_addon.py`, and `app/routes/stremio_addon.py`; covered by `tests/test_metadata.py` and `tests/test_stremio_addon.py`. |
| P20-11 | Add native Stremio stream routes backed by the app's Jackett search pipeline. | Codex | 2026-03-28 | complete | IMDb movie IDs and IMDb episode video IDs resolve to Stremio torrent streams ordered by playback relevance. | Landed in `app/services/stremio_addon.py` and `app/routes/stremio_addon.py`; stream ranking now favors quality markers, then seeders, then peers, then recency. |
| P20-12 | Add focused addon-route regressions and validate the expanded phase slice. | Codex | 2026-03-28 | complete | Pytest, Ruff, and targeted type checks pass for the native addon manifest/catalog/stream implementation. | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_metadata.py tests\\test_stremio_addon.py -q` (`15 passed`), `.\\.venv\\Scripts\\python.exe -m ruff check app\\config.py app\\db.py app\\main.py app\\models.py app\\routes\\stremio_addon.py app\\schemas.py app\\services\\metadata.py app\\services\\settings_service.py app\\services\\stremio_addon.py tests\\conftest.py tests\\test_metadata.py tests\\test_stremio_addon.py tests\\test_routes.py tests\\test_settings_service.py tests\\test_stremio.py tests\\test_stremio_auto_sync.py tests\\test_jellyfin.py` (`All checks passed`), `.\\.venv\\Scripts\\python.exe -m mypy app\\config.py app\\db.py app\\main.py app\\models.py app\\routes\\stremio_addon.py app\\schemas.py app\\services\\metadata.py app\\services\\settings_service.py app\\services\\stremio_addon.py app\\services\\stremio.py app\\services\\stremio_sync_ops.py app\\services\\stremio_auto_sync.py app\\services\\watch_state.py app\\services\\jellyfin.py app\\routes\\api.py app\\routes\\pages.py` (`Success: no issues found in 16 source files`), `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_jellyfin.py tests\\test_watch_state.py tests\\test_stremio.py tests\\test_stremio_addon.py tests\\test_settings_service.py tests\\test_routes.py tests\\test_metadata.py -k "jellyfin or watch_state or stremio or settings_service or metadata or health_endpoint"` (`65 passed`, `78 deselected`), and `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_auto_sync.py tests\\test_jellyfin_auto_sync.py -k "stremio or jellyfin"` (`2 passed`). |
| P20-13 | Close the real desktop addon gap and revalidate the full `v0.8.0` release gates. | Codex | 2026-03-28 | complete | The real Stremio desktop client visibly renders qB RSS rows for the known regression titles, transient empty addon responses no longer linger in cache, and the release gates are green for the final payload shape. | `cmd.exe /c scripts\\check.bat` (`262 passed`, `1 skipped`), `cmd.exe /c scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260328T140235Z\\`), `cmd.exe /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), `.\\.venv\\Scripts\\python.exe scripts\\stremio_addon_smoke.py --mode service --min-streams 2 --require-4k`, `.\\.venv\\Scripts\\python.exe scripts\\stremio_addon_smoke.py --mode http --min-streams 2 --require-4k --base-url http://127.0.0.1:8000`, `.\\.venv\\Scripts\\python.exe scripts\\stremio_desktop_smoke.py --manifest-url http://127.0.0.1:8000/stremio/manifest.json --json` (artifacts under `logs\\qa\\stremio-desktop-smoke-20260328T140625Z\\`), and `.\\.venv\\Scripts\\python.exe scripts\\stremio_desktop_smoke.py --manifest-url http://127.0.0.1:8000/stremio/manifest.json --detail-url https://web.stremio.com/#/detail/series/tt33517752/tt33517752%3A1%3A4 --json` (artifacts under `logs\\qa\\stremio-desktop-smoke-20260328T140706Z\\`). |

## Risks And Follow-Up

### Risk: local WebView storage layout can change between Stremio desktop releases

- Trigger: a future Stremio desktop/WebView update changes where or how the auth profile is stored.
- Impact: automatic local discovery could fail even though the user is signed in.
- Mitigation: support an explicit storage-path override now and keep an environment auth-token override available for recovery.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

### Risk: title-only linkage can still produce ambiguous matches for some libraries

- Trigger: multiple different titles normalize to the same fallback string and lack an IMDb-backed Stremio item ID.
- Impact: the service could link the wrong pre-existing rule or skip a safe create.
- Mitigation: prefer Stremio ID and IMDb matches first, fall back to normalized title only when the candidate set is unambiguous, and otherwise skip with a clear message.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

### Risk: metadata-provider title search will still miss some titles that a richer catalog source could find

- Trigger: OMDb lacks a title entirely, returns the wrong canonical match, or has weaker search coverage than Stremio users expect.
- Impact: the native addon can still improve stream parity while failing to surface some missing titles in Stremio search.
- Mitigation: land the first addon slice on the current metadata provider path now, then evaluate TMDb or richer multi-provider title-search support as the next catalog-focused follow-up if live use shows OMDb gaps.
- Owner: Codex
- Review date: 2026-03-28
- Status: open

### Risk: invalid metadata-provider credentials can still leave the search catalog empty even when stream lookup works

- Trigger: the saved OMDb key is missing, malformed, or entered as the full OMDb URL instead of just the API key value.
- Impact: Stremio detail pages for known IMDb items can still show qB RSS streams through the Cinemeta metadata fallback, but `/stremio/catalog/...` search routes return no metas and the addon appears weaker in title search than on item pages.
- Mitigation: keep the Cinemeta fallback for stream lookup, surface the exact setup error in settings/test flows, and consider a richer non-OMDb catalog fallback in the next addon follow-up if this remains common.
- Owner: Codex
- Review date: 2026-03-28
- Status: open

## Next Concrete Steps

1. Keep `scripts\\stremio_addon_smoke.py` plus `scripts\\stremio_desktop_smoke.py` as the required acceptance pair before changing native addon search/stream behavior again.
2. Repair the mock-addon install path inside `scripts\\stremio_desktop_variant_matrix.py` so the variant matrix can keep bisecting Stremio acceptance rules without manual reinstalls.
3. Run one live `/settings` verification pass against the real signed-in desktop session to confirm `Test Stremio`, `Save + Sync Stremio Now`, and the shared completed-movie disablement path are still clean after the addon closeout.
4. Correct the saved OMDb API key, then recheck `/stremio/catalog/...` search behavior so the addon contributes both search metas and item-page streams from the same backend.
5. Decide whether the next Stremio follow-up should focus on watched-progress arbitration, richer catalog providers, or native addon metadata/configuration expansion.

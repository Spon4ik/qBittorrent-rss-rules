# Roadmap

## Current release state: v1.4.18 published; Phase 44 in implementation

### Validated locally

- Phase 44 acceleration operations console and exact-infohash variant context is implemented and live-smoke-tested; automatic `Ask Codex` heartbeat pickup/status readback remains the final pending end-to-end validation before the phase can close (`docs/plans/phase-44-acceleration-operations-console.md`).
- `v1.4.18` is published with the result-toolbar and left-rail dark-mode follow-up. Live browser measurements confirm aligned result/queue dropdown controls, non-reflowing dropdown overlays, readable dark surfaces, and zero horizontal overflow across the validated desktop viewport matrix.
- Phase 39 hardens the first authenticated Real-Debrid acceleration run by
  bounding and prioritizing scheduler work, falling back from rejected public
  metainfo to a tracker-free magnet, committing web-seed mappings before
  attachment, and bounding overlong provider range streams
  (`docs/plans/phase-39-real-debrid-live-acceleration-hardening.md`).
- Phase 36 is implemented and published in `v1.4.0`: official Real-Debrid Device OAuth, personal torrent-cloud/download-history search, qBittorrent HTTP web-seed acceleration, encrypted integration secrets, and a MyJDownloader fallback only when qBittorrent cannot obtain metadata (`docs/plans/phase-36-real-debrid-search-and-qbittorrent-http-acceleration.md`).

- Phase 35 is implemented and locally/Docker validated as the smart audiobook lookup/search slice: audiobook rules default to a provider-aware Google Books/OpenLibrary lookup chain, persist structured search hints, and use those hints for capability-aware Jackett `t=book` searches without changing qB RSS rule generation (`docs/plans/phase-35-smart-audiobook-rule-search.md`).
- Phase 31 is implemented and locally/Docker validated as the shared operation progress slice: a process-local operation registry, `/api/operations/status`, qB/Jackett/Jellyfin/Stremio producer instrumentation, and a global polling progress bar in the base layout (`docs/plans/phase-31-shared-operation-progress-bar.md`).
- Phase 30 is implemented and locally/Docker validated as the post-Phase 29 precision hardening slice: IMDb-backed Jackett movie/series rows now share one strict identity classifier across live search filtering and saved snapshot replay, so broad token-only fallback rows for short/common titles such as `You` and `Ghosts` stay hidden/debug-only (`docs/plans/phase-30-imdb-backed-jackett-precision.md`).
- Phase 29 is implemented and locally validated as the post-`v1.1.6` rules operations workbench: fast local rule saves with background qB sync, main-page batch quality assignment/filtering, backend-derived release signal, missing/oldest-first parallel snapshot fetching, compact data-grid UI, version visibility, compact icon row actions, and snapshot-summary render optimization (`docs/plans/phase-29-rules-operations-workbench.md`).
- Phase 28 is published as the `v1.1.6` patch slice: persisted Jackett active-search indexers now own saved-rule search/snapshot scope while `feed_urls` remains qB RSS passive sync scope (`docs/plans/phase-28-rule-search-scope-authority.md`).
- Phase 26 is published as the `v1.1.4` patch slice: structured Jackett music/audiobook direct searches now respect explicit indexer scope before later cleanup considers larger search-form or metadata-field work.
- Phase 27 is published as the `v1.1.5` structured-audio cleanup: expose the backend-supported music/audiobook metadata fields on the active search page so native Jackett audio params can be driven deliberately.
- Phase 25 is now closed and published in `v1.1.3`: qBittorrent RSS Rules no longer hosts the native Stremio addon surface and keeps only Stremio library/watch-progress synchronization, because addon hosting moved to `jackett-stremio-fork`.
- The `v1.1.3` release published the post-`v1.1.2` contract-roadmap guardrails and qB enforcement-parity diagnostics after the existing `v1.1.2` taxonomy/profile tag.
- Phase 23 is now closed and release-validated in `v0.9.0` as the Stremio cross-addon aggregation slice, including persisted provider manifests, live Torrentio-compatible provider ingestion inside the local addon, exact-first desktop/result-contract precursors, and real desktop smoke proof for merged provider ordering.
- Phase 24 remains closed and release-validated in `v0.8.3` as the hotfix for long-running series like `Death in Paradise` and related qB-side search/visibility precursors.
- Phase 22 is now closed and release-validated in `v0.8.2` as the Stremio patch slice covering full qB RSS variant retention, global quality-first ordering, and exact-variant local playback marking after the `v0.8.1` release still suppressed rows too aggressively.
- Phase 21 is now closed and release-validated in `v0.8.1` as the Stremio playback follow-up slice covering qB RSS stream ordering and qB-backed local playback acceleration so predownloaded torrents materially improve Stremio playback.
- Phase 20 is now closed and release-validated in `v0.8.0` as the Stremio library sync and native addon parity slice, including real desktop proof that qB RSS rows render in Stremio for known items such as `The Beauty`.
- Phase 19 is now closed and release-validated as the filter-profile live-apply, request-time asset versioning, and managed-engine lifecycle hardening patch slice.
- Phase 18 is now closed and release-validated as the rule-form filter-profile live-update patch slice.
- Phase 17 remains closed and release-validated as the shared watch-state arbitration foundation slice, with Stremio sync intentionally deferred to a later phase.
- Keep future Stremio work in this repo scoped to sync/watch-state integration unless roadmap ownership changes again.
- Keep the explicit music/audiobook structured Jackett search follow-up active as Phase 26, starting with direct capable indexer scope parity before any broader search-form cleanup.
- Keep deterministic browser QA, static checks, full pytest, WinUI desktop builds, and live sync validation as release gates for the next feature phase.

### Current phase track

- Phase 44: acceleration operations console and variant context (in implementation; functional/UI validation passes, automatic `Ask Codex` heartbeat pickup/status readback still pending; `docs/plans/phase-44-acceleration-operations-console.md`)
- Phase 45: central authoritative backend and multi-PC access (planned only; implementation starts after `experiment/codex-token-efficiency` is merged into `main` and the planning branch is rebased; `docs/plans/phase-45-central-authoritative-backend-multi-pc.md`)
- Phase 39: Real-Debrid live acceleration hardening (published in `v1.4.11`;
  `docs/plans/phase-39-real-debrid-live-acceleration-hardening.md`)
- Phase 36: Real-Debrid search and qBittorrent HTTP acceleration (published in `v1.4.0`; authenticated account smoke remains a post-connection check; `docs/plans/phase-36-real-debrid-search-and-qbittorrent-http-acceleration.md`)
- Phase 35: smart audiobook rule search (implemented and locally/Docker validated; `docs/plans/phase-35-smart-audiobook-rule-search.md`)
- Phase 31: shared operation progress bar (implemented and locally/Docker validated; `docs/plans/phase-31-shared-operation-progress-bar.md`)
- Phase 30: IMDb-backed Jackett precision hardening (implemented and locally/Docker validated; `docs/plans/phase-30-imdb-backed-jackett-precision.md`)
- Phase 29: rules operations workbench (implemented and locally validated; `docs/plans/phase-29-rules-operations-workbench.md`)
- Phase 28: rule/search scope authority (published in `v1.1.6`; `docs/plans/phase-28-rule-search-scope-authority.md`)
- Phase 27: structured audio search fields (published in `v1.1.5`; `docs/plans/phase-27-structured-audio-search-fields.md`)
- Phase 26: structured Jackett audio search scope (published in `v1.1.4`; `docs/plans/phase-26-structured-jackett-audio-search.md`)
- Phase 25: native Stremio addon removal and sync retention (published in `v1.1.3`; `docs/plans/phase-25-stremio-addon-removal-and-sync-retention.md`)
- Phase 24: Stremio long-running series year hotfix (implemented and release-validated in `v0.8.3`; `docs/plans/phase-24-stremio-long-running-series-year-hotfix.md`)
- Phase 23: global cross-addon stream ordering (implemented and release-validated in `v0.9.0`; `docs/plans/phase-23-global-cross-addon-stream-ordering.md`)
- Phase 22: Stremio variant parity and local playback marking (implemented and release-validated in `v0.8.2`; `docs/plans/phase-22-stremio-variant-parity-and-local-marking.md`)
- Phase 21: Stremio stream ordering and qB-backed local playback acceleration (implemented and release-validated in `v0.8.1`; `docs/plans/phase-21-stremio-stream-ordering-and-local-playback.md`)
- Phase 20: Stremio library sync and native addon parity (implemented and release-validated in `v0.8.0`; `docs/plans/phase-20-stremio-library-rule-sync.md`)
- Phase 19: filter-profile live-apply, request-time asset versioning, desktop freshness polling, and managed engine lifecycle hardening (implemented and release-validated in `v0.7.6`; `docs/plans/phase-19-filter-profile-live-apply-and-managed-engine-lifecycle-hardening.md`)
- Phase 18: rule-form filter-profile live recompute and patch release (implemented and release-validated in `v0.7.5`; `docs/plans/phase-18-rule-form-filter-profile-live-recompute-and-patch-release.md`)
- Phase 17: shared watch-state arbitration foundation (implemented and release-validated in `v0.7.4`; `docs/plans/phase-17-shared-watch-state-arbitration-foundation.md`)
- Phase 16: desktop build portability and NuGet source cleanup (implemented and release-validated; `docs/plans/phase-16-desktop-build-portability-and-nuget-source-cleanup.md`)
- Phase 15: repo-local backend startup portability maintenance (implemented and manually validated; `docs/plans/phase-15-repo-local-backend-startup-portability.md`)
- Phase 14: `v0.7.2` template warning cleanup and release push (implemented and release-validated; `docs/plans/phase-14-v0-7-2-template-warning-cleanup-and-release-push.md`)
- Phase 13: `v0.7.1` desktop freshness and engine shutdown controls (implemented and release-validated; `docs/plans/phase-13-v0-7-1-desktop-freshness-and-shutdown.md`)
- Phase 12: `v0.7.0` catalog-aware Jellyfin floors and missing-only queue selection (implemented and release-validated; `docs/plans/phase-12-v0-7-0-catalog-aware-jellyfin-and-missing-only-queue.md`)
- Phase 11: `v0.6.1` stabilization and desktop hardening (implemented and release-validated; `docs/plans/phase-11-v0-6-1-stabilization-and-desktop-hardening.md`)
- Phase 10: WinUI desktop bootstrap baseline + next-version planning (implemented and release-validated in `v0.6.0`)
- Phase 9: rules main-page release-aware operations + Jackett fetch orchestration (implemented and release-validated in v0.5.0)
- Phase 8: persistent rule-search snapshots and unified results workspace UX (implemented and release-validated in v0.4.0)
- Phase 7: cached-refinement responsiveness and category-catalog integrity (implemented and release-validated in v0.3.0)
- Phase 6: Jackett-backed active search workspace (implemented and release-validated in v0.2.0; follow-up polish completed, deeper persistence still deferred)
- Phase 4: feed selection UX improvements (implemented, automated closeout validated)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, automated closeout validated)

### Near-term engineering improvements (after Phase 44 closeout)

Do not bypass the remaining Phase 44 acceptance work to start these. First prove the real automatic `Ask Codex` heartbeat pickup/status-readback path end to end, then take the following improvements one at a time in priority order.

#### 1. Automatic UI invariants

Turn recurring visual/layout checks into deterministic browser assertions so geometry regressions fail locally without requiring a human or an LLM to inspect screenshots.

Implementation direction:

- Build reusable Playwright helpers for element geometry and layout invariants using `getBoundingClientRect()`, computed styles, visibility/state, `scrollWidth/clientWidth`, and before/after measurements.
- Start with the `v1.4.18` result toolbar because its intended behavior is already known and manually/live measured:
  - controls that share a row must have the same top coordinate within a small tolerance;
  - controls intended to share a height must remain equal-height within tolerance;
  - opening indexer/category/queue dropdowns must not change toolbar height;
  - opening an overlay must not move the following content block;
  - no affected viewport may gain horizontal page overflow.
- Run the invariant set across the relevant responsive matrix. Desktop row-alignment assertions should apply only where the responsive layout is expected to remain a row; mobile/wrapped layouts should have their own invariants rather than forcing desktop geometry.
- On failure, save a compact JSON metrics artifact plus a screenshot and, where useful, a crop of the affected region.
- Use Pillow/OpenCV or pixel-diff checks only for properties that DOM geometry/state cannot prove reliably, such as unexpected color/theme rendering, clipping artifacts, or image-level regressions. Do not use computer vision as the primary alignment detector when browser geometry is authoritative.
- Integrate the reusable assertions into the existing browser QA tooling rather than creating a parallel screenshot framework.
- Update `docs/testing.md` when the invariant layer becomes a maintained release gate.

Acceptance criteria:

- the `v1.4.18` toolbar/dropdown behavior has permanent regression coverage;
- a deliberate 2-3 px alignment/reflow regression fails deterministically without image interpretation;
- failures produce bounded machine-readable metrics and useful visual evidence;
- the same assertion helpers can be reused by later UI fixes without copying large blocks of Playwright code.

#### 2. Modularize `closeout_browser_qa.py`

Reduce maintenance and model-context cost by splitting the existing large browser closeout harness along stable responsibilities while preserving its current behavior, CLI entry point, reports, and artifacts.

Implementation direction:

- Keep `scripts/closeout_browser_qa.py` as a thin compatibility entry point while extracting reusable modules incrementally; do not rewrite the whole harness at once.
- Prefer a structure equivalent to:
  - runner/reporting orchestration;
  - reusable assertions (`geometry`, `overflow`, `overlays`, later selective visual checks);
  - service fixtures/mocks for qBittorrent and Jackett;
  - page/workspace helpers for rules, search, acceleration, and shared navigation;
  - scenario modules for cohesive workflows such as result-toolbar layout, dark mode, hover overlays, and search-to-rule handoff.
- Extract code when it is touched by new work so each step stays small and reviewable.
- Preserve deterministic IDs, exit semantics, report JSON/Markdown shape, and existing failure artifacts unless a deliberate migration is planned.
- Add focused tests for extracted helpers where a pure/unit-level contract is possible, especially geometry comparison, tolerance handling, artifact naming, and report aggregation.
- Avoid building a generic test framework beyond the project's needs; the goal is reusable project QA, not abstraction for its own sake.

Acceptance criteria:

- the existing closeout command remains backward compatible;
- the main script becomes primarily orchestration rather than containing all fixtures, assertions, and scenarios inline;
- new UI regression coverage can normally be added through a small scenario plus reusable assertions;
- browser QA failures remain easy to locate from the report without reading the entire harness or raw logs.

#### 3. Structured evidence for the automatic debugger / `Ask Codex`

Move recurring diagnostic reduction into deterministic application/tooling code so Codex receives a compact evidence bundle instead of spending model context rediscovering basic facts from raw logs.

Implementation direction:

- Define a versioned structured evidence schema for maintenance requests. Include only fields that materially help diagnosis, such as failure class, component/operation, app version, relevant entity identity, expected vs observed state, bounded recent events, deterministic probe results, suggested reproduction/tests, and redaction metadata.
- Run cheap deterministic probes before dispatch whenever possible: provider reachability, persisted job state, mapping existence, qB/webseed state, recent operation status, relevant configuration presence, and other failure-class-specific checks.
- Keep full logs as referenced artifacts when needed, but send bounded excerpts or normalized events by default rather than bulk log text.
- Preserve Phase 44's existing redaction, deduplication, and exact-scope safety contracts. Use a stable failure fingerprint so repeated equivalent failures can deduplicate without collapsing materially different incidents.
- Add explicit payload-size budgets and tests that secrets/credentials/private payloads cannot leak into the evidence bundle.
- Store the generated evidence in a form that can be inspected independently of the LLM request so a developer can reproduce what Codex actually received.
- Measure whether recurring incidents can be diagnosed from the bundle without reading broad application logs; escalate to additional evidence only when the compact bundle is insufficient.

Acceptance criteria:

- equivalent recurring failures generate bounded, stable, redacted evidence bundles;
- no credential or private provider payload is included in normal dispatch evidence;
- common incidents reach Codex with enough deterministic state to start at hypothesis/fix work rather than log triage;
- raw-log reading becomes an escalation path rather than the default debugging input.

### Further engineering improvements

After the three priorities above are established, evaluate these at a higher level rather than starting them all at once:

- **Tiered/affected validation:** map changed areas to fast targeted checks, then retain the full release gate for closeout; avoid running expensive browser/provider coverage when a deterministic smaller gate is sufficient.
- **Selective visual regression:** add stable pixel/image baselines only for genuinely visual surfaces such as dark-theme colors, clipping, and rendering artifacts; mask dynamic content and keep tolerances explicit.
- **QA artifact index:** generate one compact machine-readable summary linking failed assertions, metrics, screenshots, logs, videos, and runtime/version metadata so both humans and agents can navigate evidence without scanning directories.
- **Performance budgets:** add bounded timing/size budgets for high-cost browser flows, snapshot rendering, provider calls, and background operations to catch regressions before they become behavioral complaints.
- **Property/fuzz coverage for matching rules:** use generated inputs for title normalization, episode/range parsing, quality taxonomy aliases, and pattern generation where combinatorial edge cases are more valuable than additional hand-written examples.
- **Documentation/context hygiene:** keep active status and phase handoffs compact, move durable architectural invariants into ADRs/contracts, and avoid forcing future agents to reread long release history to understand current work.

### Planned Phase 45 - Central authoritative backend and multi-PC access

Keep code in the public repository but make the always-on NUC/Docker backend the single authority for private rules, SQLite state, schedulers, and provider operations. Other PCs connect as clients over the backend API/Web UI instead of synchronizing `qb_rules.db` or its WAL/SHM files.

Sequencing and branch discipline:

- Do not implement this inside `experiment/codex-token-efficiency`; that branch remains scoped to the current experiment and Phase 44 closeout.
- The dedicated planning branch `roadmap/central-backend-multi-pc` is intentionally stacked on the experiment because that branch contains the current roadmap. After the experiment is merged, rebase the planning branch onto the updated `main` before starting implementation.
- Preserve current local-managed-backend behavior as the default/supported single-PC mode; remote-authoritative mode is opt-in.

Implementation direction:

- Promote the already-supported `QB_RSS_DESKTOP_URL` HTTP/HTTPS override into a first-class desktop connection mode with desktop-local persisted endpoint configuration.
- Separate **local managed backend** and **remote authoritative backend** lifecycle semantics. When a configured remote backend is unreachable, fail closed and report the remote failure; never try to launch a local Python process using the remote hostname.
- In remote mode, disable local source-freshness watching and local Start/Restart/Shut Down Engine actions. Provider synchronization, schedulers, acceleration, snapshots, and all writes remain owned by the authoritative host.
- Keep `/health` contract/version/capability validation before the WinUI WebView loads so stale/incompatible clients cannot silently attach to an incompatible server.
- Use a private network/overlay such as Tailscale or WireGuard, or equivalent firewall-restricted transport, for the initial deployment. Do not make unauthenticated public Internet exposure or router port-forwarding a supported default.
- Treat server filesystem paths as paths on the authoritative host; remote clients must not imply that client-local Stremio/Jellyfin paths are readable by the server.
- Keep backup separate from live access. If cloud/NAS/Resilio/Syncthing backup is added, generate a consistent SQLite snapshot first and sync only completed backup artifacts, never the live database files.
- A later private-Git logical rules/config export may be useful for versioned portability, but it is not the live synchronization mechanism and secrets must stay out of plaintext Git history.

Acceptance criteria:

- PC/client A can create/edit/delete a test rule and PC/client B observes the same persisted authoritative state through ordinary backend requests with no file-copy step;
- only the NUC/backend owns `qb_rules.db`, provider schedulers, and background operations; remote clients neither create a local database nor duplicate backend jobs;
- simultaneous client reads and representative writes remain safe because SQLite concurrency stays inside one backend host;
- a remote outage/reconnect cannot fork state and cannot trigger a local-backend fallback;
- incompatible backend contract/version/capability checks still fail closed;
- no credentials or private provider payloads are exposed through client diagnostics;
- the recommended deployment is not reachable from unintended public interfaces;
- existing local-managed mode and its startup/shutdown/reconnect behavior remain regression-tested;
- full backend, WinUI, browser, and live Docker validation gates pass.

Detailed design, safety contract, implementation slices, non-goals, and deterministic validation are tracked in `docs/plans/phase-45-central-authoritative-backend-multi-pc.md`.

Phase 44 detail pointer:
- Current implementation status, safety contract, UI/API decisions, and the remaining automatic heartbeat acceptance proof are tracked in `docs/plans/phase-44-acceleration-operations-console.md`.

Phase 24 detail pointer:
- Dated checklist, regression evidence, and scope for the active `v0.8.3` long-running series hotfix live in `docs/plans/phase-24-stremio-long-running-series-year-hotfix.md`.

Phase 23 detail pointer:
- Dated checklist, release validation evidence, and follow-up notes for the delivered `v0.9.0` cross-addon ordering slice live in `docs/plans/phase-23-global-cross-addon-stream-ordering.md`.

Phase 22 detail pointer:
- Dated checklist, variant-retention decisions, and validation evidence for the completed `v0.8.2` Stremio patch slice live in `docs/plans/phase-22-stremio-variant-parity-and-local-marking.md`.

Phase 21 detail pointer:
- Dated checklist, ranking/local-playback decisions, and validation evidence for the current Stremio follow-up slice live in `docs/plans/phase-21-stremio-stream-ordering-and-local-playback.md`.

Phase 20 detail pointer:
- Dated checklist, discovery decisions, Stremio-managed rule contract, native addon decisions, and validation evidence are tracked in `docs/plans/phase-20-stremio-library-rule-sync.md`.

Phase 15 detail pointer:
- Dated checklist, repo-local `.venv` portability decisions, and manual backend health validation are tracked in `docs/plans/phase-15-repo-local-backend-startup-portability.md`.

Phase 16 detail pointer:
- Dated checklist, machine-specific NuGet source cleanup, desktop build portability validation, and `v0.7.3` release publication notes are tracked in `docs/plans/phase-16-desktop-build-portability-and-nuget-source-cleanup.md`.

Phase 17 detail pointer:
- Dated checklist, shared watch-state arbitration decisions, Jellyfin parity validation, and the later Stremio split are tracked in `docs/plans/phase-17-shared-watch-state-arbitration-foundation.md`.

Phase 18 detail pointer:
- Dated checklist, filter-profile live-update bug fix decisions, browser regression coverage, and patch-release publication notes are tracked in `docs/plans/phase-18-rule-form-filter-profile-live-recompute-and-patch-release.md`.

Phase 14 detail pointer:
- Dated checklist, warning-cleanup validation evidence, and release publication notes are tracked in `docs/plans/phase-14-v0-7-2-template-warning-cleanup-and-release-push.md`.

Phase 13 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for WinUI desktop freshness watching, fail-closed backend refresh/reconnect behavior, and in-app managed-backend shutdown/exit controls are tracked in `docs/plans/phase-13-v0-7-1-desktop-freshness-and-engine-shutdown.md`.

Phase 12 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for OMDb-backed season-finale detection, remembered Jellyfin episode history after local file cleanup, episode-`0` floor support, and qB missing/unseen file selection are tracked in `docs/plans/phase-12-v0-7-0-catalog-aware-jellyfin-and-missing-only-queue.md`.

Phase 11 detail pointer:
- Dated checklist, Jellyfin sync contract decisions, zero-based range leak closeout, and final `v0.6.1` release validation are tracked in `docs/plans/phase-11-v0-6-1-stabilization-and-desktop-hardening.md`.

Phase 10 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for WinUI desktop phase-10 work (`QbRssRulesDesktop` scaffold, dev-loop hardening, WebView-shell baseline, and retained companion-process direction) are tracked in `docs/plans/phase-10-winui-desktop-bootstrap.md`.

Phase 9 detail pointer:
- Detailed checklist and dated execution tracker for the table-first rules page UX, poster hover/cards behavior, on-demand/scheduled Jackett rule fetch orchestration, and rule sorting by post-filter release availability is tracked in `docs/plans/phase-9-rules-main-page-release-ops.md`.

Phase 8 detail pointer:
- Detailed checklist and dated execution tracker for persistent per-rule snapshots, unified IMDb-first/title-fallback results, and compact rule-page UX is tracked in `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md` under `Dated execution checklist (2026-03-14 baseline)`.

Phase 7 detail pointer:
- Detailed checklist and dated execution tracker for immediate cached filtering responsiveness and normalized category mapping is tracked in `docs/plans/phase-7-cached-refinement-and-category-catalog.md` under `Dated execution checklist (2026-03-12 baseline)`.

Phase 6 detail pointer:
- Detailed checklist and dated execution tracker for the latest search/rules UX hardening request is tracked in `docs/plans/phase-6-jackett-active-search.md` under `Request Checklist` and `Dated execution checklist (2026-03-10 baseline)`.

### Post-release focus

- Execute Phase 36 in resumable slices, keeping qBittorrent primary whenever metadata exists and using MyJDownloader only for the documented no-metadata fallback.
- Keep bidirectional watch-progress write-back as a dedicated follow-up after Phase 31; it needs a canonical progress store, source timestamps, and opt-in safe write-back paths for Jellyfin/Stremio rather than a simple UI progress addition.
- Track the Phase 30 long-term exactness path separately: upstream/custom Jackett definition improvements for trackers that expose IMDb links without Torznab `imdbid` support, and a later opt-in detail-page enrichment fallback that is disabled by default, allowlisted per indexer, bounded, cached, and never promotes a row without confirming the requested IMDb ID.
- Decide whether the next catalog/search step should expand beyond OMDb-backed title search into richer provider support or more explicit release-calendar reasoning.
- Decide whether the next Stremio follow-up should stay sync-focused or retire the remaining legacy addon-era schema fields.
- Continue broadening the structured taxonomy editor beyond common value add/remove/reorder flows into bundle, rank, and alias editing; built-in video filter profiles now already inherit resolution-rank changes from runtime taxonomy.
- Decide whether deleted-history persistence should stay rule-local or graduate to a broader watch-history/scrobble-compatible cache.
- Reduce context and maintenance cost by splitting the largest rule/search/Jellyfin files along real domain boundaries.
- Keep deterministic browser QA and route/service regressions as release gates for every workflow change.

## Release-validated: v0.9.0 (2026-04-11)

- Shipped the phase-23 Stremio aggregation release so the local addon can merge qB RSS rows with Torrentio-compatible provider manifests into one globally ranked stream response instead of relying on Stremio's per-addon grouping.
- Persisted provider manifest configuration in `/settings`, fixed comma-safe parsing for real provider URLs, URL-encoded episode item ids for provider stream URLs, and switched external provider fetches to a browser-like request profile that survives the current Torrentio edge protection.
- Improved qB-authored episode rows so resolved season-pack results show the selected file size first, keep pack size as secondary context, and emit `behaviorHints.videoSize` alongside filename and `fileIdx`.
- Revalidated the release with `scripts\\check.bat` (`337 passed`), `scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260410T222806Z\\`), `scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), fresh HTTP addon smoke on `http://127.0.0.1:8002`, and real desktop smoke artifacts under `logs\\qa\\stremio-desktop-smoke-20260410T223201Z\\`.

## Release-validated: v0.8.3 (2026-04-02)

- Shipped the phase-24 hotfix so long-running series like `Death in Paradise` no longer hide episode streams due to outdated start-year constraints in Stremio lookup queries.
- Shipped early phase-23 precursors: improved Stremio addon variant visibility (quality markers, size, attribution) and added episode-floor precision to the main app Jackett IMDb-first series fallback path.
- Revalidated the patch with focused pytest/typing/lint checks, realtime direct route probes, and desktop smoke reruns for the corrected `Death in Paradise` and `The Beauty` request payloads.

## Release-validated: v0.8.4 (2026-04-02)

- Shipped a maintenance hotfix so season-finale series rules that advance to next-season `E00` no longer lose `start_episode=0` when opened and re-saved from the edit form.
- Added focused route regression coverage and deterministic browser closeout coverage for the `E00` edit-form flow so the stored episode floor remains visible and stable across UI round trips.

## Release-validated: v0.8.5 (2026-04-03)

- Shipped a phase-23 maintenance follow-up so the `bluray` quality token no longer over-matches `BDRip/BRRip`, which was hiding otherwise valid exact 4K HDR results in the main qB RSS search path.
- Hardened the deterministic browser-closeout and smoke layers so the rules-page exact-filter memory check no longer depends on a flaky same-page submit transition, direct `scripts\stremio_addon_smoke.py` execution delegates to the module path, and cold live HTTP addon requests no longer fall back to a misleading local-only row for `The Beauty` episode 1.
- Added targeted taxonomy and Jackett regressions plus a deterministic browser-closeout check that proves exact movie rules keep `BDRip` rows visible when only `bluray` and `bdremux` are excluded.
- Revalidated the patch with `scripts\check.bat`, `scripts\closeout_browser_qa.py`, `scripts\run_dev.bat desktop-build`, and sequential Stremio addon service/http smoke runs.

## Release-validated: v0.8.2 (2026-03-28)

- Shipped the phase-22 Stremio variant-parity follow-up so qB RSS now keeps the broader viable variant set instead of collapsing back to a tiny local-first subset.
- qB RSS stream rows now sort by quality first and seeds second while exact locally available variants are upgraded in-place to fast local-playback rows instead of hiding the broader fallback set.
- Revalidated the patch with `scripts\check.bat` (`270 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T163220Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), addon service/http smokes, and real desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T162948Z/` and `logs/qa/stremio-desktop-smoke-20260328T163111Z/`).

## Release-validated: v0.8.1 (2026-03-28)

- Shipped the phase-21 Stremio playback follow-up so qB RSS addon rows now rank best-playable-first, keeping the strongest available qB variant ahead of weaker fallbacks in the addon payload and the real desktop client.
- Added qB-backed direct local playback for completed media files via `/stremio/local-playback/{token}`, including qB torrent/file inspection helpers, deterministic local-file resolution, and inventory fallback so already-downloaded content can play directly from disk instead of buffering like an ordinary remote torrent.
- Revalidated the patch with `scripts\check.bat` (`269 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T154314Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), `.\.venv\Scripts\python.exe scripts\stremio_addon_smoke.py --mode service --min-streams 2 --require-4k --json`, `.\.venv\Scripts\python.exe scripts\stremio_addon_smoke.py --mode http --min-streams 2 --require-4k --base-url http://127.0.0.1:8013 --json`, and real desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T154722Z/` and `logs/qa/stremio-desktop-smoke-20260328T154802Z/`.
- Verified the local playback transport directly with a ranged probe against the generated `/stremio/local-playback/...` URL, receiving `206 Partial Content`, `1,048,576` bytes, and about `9.7 ms` response time from the local backend.

## Release-validated: v0.8.0 (2026-03-28)

- Shipped the phase-20 Stremio slice with local desktop auth discovery, authoritative library sync, Stremio-managed rule creation/linkage, background auto-sync, and centralized completed-movie auto-disable shared across providers.
- Added a native qB RSS Stremio addon served from the local backend, including manifest delivery, movie/series search catalogs, and IMDb-backed stream lookups powered by the app's own metadata and Jackett search stack.
- Fixed the final desktop-only addon acceptance issue by simplifying qB RSS stream payloads to the Stremio-compatible contract proven by the real desktop smoke harness, so qB RSS rows now render in the Stremio desktop client for episodes such as `tt33517752:1:1` and `tt33517752:1:4`.
- Hardened the live addon path by avoiding long-lived caching of empty stream responses, so transient Jackett misses no longer leave the running backend looking broken until a manual restart.
- Revalidated the slice with `scripts\check.bat` (`262 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T140235Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), addon HTTP/service smokes, and real Stremio desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T140625Z/` and `logs/qa/stremio-desktop-smoke-20260328T140706Z/`

## Recently released: v0.7.4 (2026-03-27)

- Shipped the phase-17 shared watch-state arbitration foundation slice so episode-key normalization, merging, sorting, and floor selection now live in a reusable shared module.
- Jellyfin sync now routes through the shared arbitration layer without changing existing floor or history behavior, while Stremio sync remains a later follow-up phase.
- Revalidated the patch with `scripts\check.bat` (`229 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`15/15` browser checks passed), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.4` tag to `origin`.

## Recently released: v0.7.6 (2026-03-27)

- Shipped the phase-19 patch so rule-form filter-profile changes apply immediately, repo-local frontend edits refresh with a request-time asset version token, and managed backend shutdown/restart controls actually stop the process tree when confirmed.
- Added regression coverage for the live profile-selection path, the request-time asset-version refresh, and the release closeout QA flow.
- Revalidated the patch with `scripts\check.bat` (`231 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`all browser closeout checks passed`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.6` tag to `origin`.

## Recently released: v0.7.5 (2026-03-27)

- Shipped the phase-18 rule-form patch so choosing a filter profile now immediately applies the selected minimum-quality state and regenerates the derived pattern preview without waiting for another field edit.
- Added a dedicated regression check for the immediate profile-application path in both the pytest source assertions and the live browser closeout QA flow.
- Revalidated the patch with `scripts\check.bat` (`230 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`all browser closeout checks passed`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)` after clearing a stale locked desktop process).
- Published `main` and the `v0.7.5` tag to `origin`.

## Recently released: v0.7.3 (2026-03-27)

- Shipped the phase-16 build-portability slice so the repo no longer depends on the missing Visual Studio offline NuGet source path and the WinUI build can restore cleanly from a fresh machine.
- Removed the hardcoded `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\` source from `NuGet.config`, leaving `nuget.org` as the sole configured restore source for the project.
- Hardened `scripts\run_dev.bat` so copied repo-local `.venv` launchers fail fast with concrete recreate commands instead of a stale `No Python at ...` error.
- Revalidated the patch with `scripts\check.bat` (`226 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260327T093517Z/`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.3` tag to `origin`.

## Previously released: v0.7.2 (2026-03-25)

- Shipped the phase-14 patch so the remaining Starlette `TemplateResponse` request-second call sites are now updated to the request-first signature and no longer emit the repeated deprecation warnings during route/rendering tests.
- Synchronized the patch release touchpoints to `0.7.2` across the FastAPI app, the WinUI desktop backend-version guard, and the `/health` route regression contract.
- Revalidated the patch with `scripts\check.bat` (`227 passed`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T133040Z/`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.2` tag to `origin`.

## Previously released: v0.7.1 (2026-03-25)

- Shipped the phase-13 desktop patch so the WinUI shell now watches local app changes in repo/dev-checkout mode, reloads the WebView when current scripts/templates change, and fails closed into the offline state during required refreshes that cannot reach a compatible backend.
- Tightened desktop backend compatibility checks so the `0.7.1` desktop shell rejects stale `0.7.0` backends even when they still expose the older desktop contract, and instead starts a managed fallback backend on a fresh loopback port when needed.
- Added explicit `Shut Down Engine` and `Exit Desktop` controls so stopping the desktop-managed Python backend no longer requires Task Manager.
- Revalidated the patch with `scripts\check.bat`, `scripts\closeout_qa.bat`, `scripts\run_dev.bat desktop-build`, and live WinUI launch verification against a managed `0.7.1` backend at `http://127.0.0.1:8001/`.

## Previously released: v0.7.0 (2026-03-25)

- Shipped the phase-12 catalog-aware Jellyfin/qB slice with OMDb-backed season-boundary checks, remembered skip history for deleted local episodes, and automatic missing/unseen qB file selection for saved series rules.
- Jellyfin sync now detects real season finales, advances to `S(next)E00`, and avoids false same-season floors such as `S01E11` when the current season is already complete in the external catalog.
- Saved rules now retain remembered Jellyfin known/watched episode history so deleting watched or already-known local files does not re-open them for later searches, while keeping Jellyfin read-only and avoiding a separate scrobbling subsystem.
- `Add to queue` now narrows multi-file series torrents to only missing/unseen episode files when torrent metadata is safe enough to parse, with explicit fallback or deferred messaging when it is not.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.6.1 (2026-03-25)

- Shipped the phase-11 stabilization slice with single-instance WinUI desktop enforcement, deferred poster backfill on the base rules page, fresh live WebView hover evidence, and a portable Windows bundle/install flow.
- Added read-only Jellyfin startup/background sync, explicit Settings sync controls, persisted next-missing series floors, and default movie auto-disable when a matching local Jellyfin item already exists.
- Fixed generated-pattern parity for season/episode minima so zero-based range titles such as `S3E00-07` are rejected consistently in saved rules, server-side local filtering, and browser-side local filtering while still allowing ranges that include the requested next episode.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.6.0 (2026-03-23)

- Shipped the phase-10 WinUI `QbRssRulesDesktop` WebView shell with repo-local build/run flow, shortcut refresh, and hidden companion-backend startup.
- Added stale-backend contract validation plus managed fallback-port startup so the desktop no longer reuses incompatible local servers already listening on `:8000`.
- Added desktop freshness protections (`--reload`, launch cache-buster query, orphaned managed-backend cleanup) and `/health` compatibility metadata.
- Added hidden fetched-row diagnostics and visibility reasons across `/search` and inline rule results.
- Hardened rules main-page performance with persisted release-cache columns, filtered snapshot loading, and bounded poster backfill retries.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.5.0 (2026-03-15)

- Shipped the phase-9 rules main-page workspace redesign with table-first defaults, cards fallback mode, and row-hover poster previews.
- Added poster metadata plumbing to persisted rules and metadata lookup flows, with graceful no-poster fallbacks in table/cards surfaces.
- Added on-demand Jackett fetch orchestration from the rules page (`Fetch Selected` and `Fetch All`) with centralized snapshot persistence for each run.
- Added schedule controls and runtime execution for recurring rule fetches, including persisted cadence/scope/last-run status in app settings.
- Added release-availability sorting and status chips derived from centralized `RuleSearchSnapshot` data (`Matches found`/`No matches`/`No snapshot`).
- Extended deterministic browser closeout automation with a phase-9 rules-workspace check (`P9-01`) plus compatibility updates for the table-only result controls.

## Earlier release: v0.4.0 (2026-03-15)

- Phase-8 persistent per-rule snapshot workflow shipped, including centralized replay/refresh behavior for inline rule results.
- Unified IMDb-first/title-fallback rendering shipped as a single source-keyed table with compact empty-state diagnostics and no standalone filter-impact panel.
- Rule-page workspace modernization shipped (sticky split rail/results layout, header-driven sorting, compact queue controls, and active local-filter chips).
- Inline affected-feed scope now applies both to rule RSS listener configuration and immediate indexer visibility in cached unified results.

## Earlier release: v0.3.0 (2026-03-13)

- Phase-7 cached-refinement/category-catalog slice shipped, including persisted indexer category mapping and scoped category option diagnostics.
- Saved-rule `Run Search` now renders inline rule-page results with feed-aware scope handling, queue actions, and table-first sort/view parity.
- Rule model and generated-pattern behavior now include episode-progress floor fields plus stricter grouped quality include semantics.
- Deterministic browser closeout automation now covers phase-7 inline local recompute, queue paused semantics, table/sort parity, and stale-category scope warnings.

## Earlier release: v0.2.0 (2026-03-11)

- Phase-6 Jackett active search shipped with IMDb-first and title-fallback split workflows
- `/search` UX density pass shipped (wider layout, compact criteria/filter-impact composition, refined result-view controls)
- Deterministic browser closeout automation + optional live-provider smoke evidence adopted for release gating
- WSL qBittorrent localhost rewrite shipped for mixed Windows/WSL topology

## Initial release: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.7.0

- Bulk rule creation from list or CSV
- Rule clone/duplicate flows
- Improved feed grouping UX
- Dry-run sync preview
- Manual drift resolution UX
- Rule export back to normalized JSON
- Basic DB backup and restore
- Better category template editor
- Richer Jellyfin sync controls (per-rule preview/selection beyond the initial bulk sync path)

## Future / North Star

- Rule templates and preset libraries
- Sample feed simulation before save
- Desktop packaging for Windows
- Optional LAN-safe auth
- Background health checks
- Snapshot rollback
- Expanded browser automation coverage (live-provider smoke + CI gating)
- Release automation and compatibility matrix

## Explicit non-goals for v0.1.0

- Multi-user access
- Cloud deployment
- Remote hosting defaults
- Background workers
- Advanced auth and RBAC
- Raw qBittorrent JSON editing UI

## Deferred items

- Strong secret storage: deferred until a concrete platform-specific strategy is selected
- Automatic drift healing: deferred to avoid surprising overwrites in early releases
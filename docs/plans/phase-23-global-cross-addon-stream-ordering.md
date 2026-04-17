# Phase 23: Global Cross-Addon Stream Ordering

## Status

- Plan created on 2026-03-28 immediately after the `v0.8.2` phase-22 release closeout.
- Phase 23 is the next planned minor release target for `v0.9.0`.
- Implementation started on 2026-03-30 after a user-reported follow-up confirmed three linked gaps: Stremio still groups Torrentio, IMDb info, and qB RSS into separate blocks; qB-authored stream rows are less descriptive than Torrentio rows; and the main qB RSS app still falls back too quickly on ambiguous series because it does not carry the rule episode-floor context into the Jackett IMDb-first path.
- The qB-side precursor implementation landed locally on 2026-03-30 in `app/services/jackett.py`, `app/routes/pages.py`, `app/services/stremio_addon.py`, `app/schemas.py`, and focused route/service tests.
- A follow-up regression fix landed on 2026-04-02 so season-finale rules that advance to `S(next)E00` no longer render `start_episode=0` as a blank edit-form field, which had been dropping the episode floor on re-save and broadening later rule searches.
- A second follow-up precision fix landed on 2026-04-02 so IMDb-first qB RSS searches no longer skip straight to title fallback when Jackett's aggregate `all` endpoint returns an empty success for `imdbid`; the app now probes direct configured IMDb-capable indexers before broadening.
- A third qB-side precision follow-up landed on 2026-04-03 so IMDb-first primary results no longer inherit fallback-only regex/manual text filters; exact runs now keep quality and structural narrowing while broad text refinement remains on fallback rows.
- A fourth follow-up QA/visibility pass landed later on 2026-04-03 so the rules page exposes exact-result counts/filters with remembered selections, the closeout harness exercises multiple movie/series exact-vs-fallback rules end-to-end, and the deterministic browser environment now disables background schedulers that were mutating seeded QA floors during closeout.
- A fifth qB-side filtering follow-up landed on 2026-04-03 so the quality taxonomy no longer lets `bluray` over-match `BDRip/BRRip`; exact disc-rip rows now stay visible unless a rule explicitly excludes `bdrip`.
- A sixth release-validation follow-up landed later on 2026-04-03 so the deterministic browser closeout loads the exact-filter URL directly instead of depending on a flaky same-page submit transition, the direct Stremio smoke script now delegates to module mode for stable imports, and the live HTTP addon path gets enough collection budget to keep the full exact stream set on cold episode requests.
- A seventh runtime-hardening follow-up landed on 2026-04-11 so OMDb settings now normalize either a clean API key or a pasted OMDb URL down to the raw API key, previously saved URL-shaped OMDb secrets are auto-healed on load, and the repo-local backend/desktop version touchpoints are synchronized to the active `0.9.0` phase target so the desktop shell no longer rejects a rebuilt local backend as `expected app version 0.9.0, got 0.8.5`.
- An eighth runtime-hardening follow-up landed later on 2026-04-11 after live OMDb `Request limit reached!` evidence showed hidden quota drain: background Stremio/Jellyfin auto-sync no longer makes OMDb-backed metadata requests, and the default rules-page load no longer performs automatic OMDb poster backfill.
- A ninth exploratory follow-up landed on 2026-04-12 during the AIOStreams replacement evaluation: the local AIOStreams stack proved install/config viability, but live playback still degraded to `0 kbps`, Torrentio rows resolved while the wrapped qB RSS addon returned `0` rows for the same request, and the repo now includes a native `/api/stremio/queue` bridge so an exact Stremio-selected variant can be converted into a magnet and queued to qBittorrent without manual title re-search.
- A tenth planning follow-up landed on 2026-04-17 after live Jackett inspection confirmed the configured instance exposes complete per-indexer language metadata (`12` `ru-RU`, `3` `en-US`, `1` `he-IL`, `0` missing) and accepts `lang:<code>` filter-indexer expressions, making rule-level preferred-language routing a viable qB-side precision slice before manual affected-feed selection is retired.
- True cross-addon/global ordering is still pending because the app does not yet ingest Torrentio-compatible streams into the local addon surface.

## Goal

Present Torrentio-derived and qB RSS-derived streams as one combined list ordered globally by quality first and seeds second, while preserving local-playback acceleration and provider attribution.

## Context

- Phase 22 fixed qB RSS visibility and internal ordering inside the qB RSS addon rows, but the Stremio desktop client still renders separate provider/addon groups in the final UI.
- The user wants the best stream overall to appear first even when it comes from qB RSS and Torrentio is installed, which the current per-addon rendering model does not provide.
- Achieving that experience likely requires aggregation into one addon/provider surface instead of expecting the Stremio client to interleave rows from separate addons.
- The same user feedback also shows that qB RSS rows are harder to compare because their visible labels collapse too much variant detail compared with Torrentio.
- The same user feedback also shows that saved-rule/main-app Jackett searches still behave less precisely than the Stremio addon for long-running or ambiguous series because the rule search contract does not carry start-season/start-episode context into the IMDb-first Jackett path before broad title fallback.

## Requested Scope (2026-03-28)

1. Merge qB RSS and Torrentio-compatible stream inputs into one ranked stream set.
2. Sort the merged set globally by quality first and seeds second.
3. Preserve local playback as a row-level upgrade so locally available variants stay fast without hiding remote fallbacks.
4. Keep enough provider attribution in the row text so the source remains understandable after merging.
5. Revalidate with backend smoke plus real desktop smoke against the merged ordering contract.

## Scope Expansion (2026-03-30 user follow-up)

6. Increase qB-authored stream-row detail so variant differences stay visible even before full cross-addon aggregation lands.
7. Carry series episode-floor context into the main qB RSS Jackett IMDb-first path so saved-rule searches can stay precise before title fallback is used.

## Scope Expansion (2026-04-17 user follow-up)

8. Add rule-level preferred-language routing for Jackett so a rule can prefer `ru` results while allowing ordered fallback to `he` and/or `en`.
9. Use Jackett filter-indexer expressions (`lang:<code>`, optionally combined with `test:passed` / type filters later) to choose the remote indexer pool automatically instead of relying on manually maintained affected-feed lists for most rules.
10. Add diagnostics that prove the configured Jackett instance exposes enough language metadata coverage to make language-aware routing trustworthy before any feed-selection deprecation is considered.
11. Start release/versioning automation so patch/minor follow-ups can move through synchronized version bumps, changelog prep, branch naming, push, and PR publication with less manual drift.

## In Scope

- Addon/provider aggregation design for Stremio stream delivery.
- Ranking and dedupe logic for merged provider rows.
- Row text/metadata changes needed to preserve provider attribution after aggregation.
- qB-authored row-title/detail improvements needed to keep variants distinguishable in the native addon.
- Series episode-floor request-contract improvements needed for qB RSS main-app IMDb-first search parity with the addon path.
- Rule-level Jackett language preferences, language-aware indexer-pool selection, and diagnostics for language metadata coverage.
- Release/versioning automation needed to carry future patch/minor follow-ups through consistent branch/version/changelog prep.
- Focused regressions and smoke updates for merged ordering behavior.

## Out Of Scope

- Replacing qB RSS variant retention or local playback behavior already delivered in phase 22.
- Stremio watch-state synchronization changes.
- Catalog/provider expansion beyond what is needed to support merged stream ordering.
- Release automation beyond the normal repo validation/push flow.

## Key Decisions To Make

### Decision: choose the aggregation architecture

- Open question: whether to ingest Torrentio-compatible stream responses into the local addon and emit one merged qB RSS-owned stream list, or to build a broader provider abstraction that can later handle more than Torrentio.
- Why it matters: the Stremio UI groups by addon, so global ordering across separate addons is not under our control.

### Decision: define the merged-row attribution format

- Open question: how much source detail to keep in the visible row text once multiple providers are emitted from one addon.
- Why it matters: merged ordering is only useful if the user can still tell whether a row came from qB RSS, Torrentio, or a future provider.

### Decision: how much qB-side search precision should land before cross-addon aggregation

- Open question: whether the phase should wait for full provider aggregation first, or first tighten the qB RSS Jackett search contract so ambiguous series/rule searches use season/episode floor context before broad title fallback.
- Why it matters: a globally sorted merged surface is less trustworthy if the qB-side candidate set is still broader and noisier than the addon path it is meant to complement.

### Decision: land qB precision/attribution precursors before full aggregation

- Date: 2026-03-30
- Context: the 2026-03-30 user follow-up showed that two concrete qB-side issues were independently harming trust in the Stremio experience: qB rows were too visually collapsed compared with Torrentio, and saved-rule/main-app searches were still broader than the addon path for series floors.
- Chosen option: land those qB-side improvements first while keeping the full Torrentio-compatible aggregation step separate.
- Reasoning: this fixes user-visible ambiguity immediately, improves the quality of the qB candidate set that future aggregation will consume, and avoids pretending the grouped-addon Stremio limitation can be solved by another qB-only sort tweak.
- Consequences: phase 23 now has one completed precursor slice plus one remaining provider-aggregation slice.

## Acceptance Criteria

- The Stremio desktop UI shows one merged addon block for the relevant streams instead of a separate qB RSS block beneath Torrentio.
- The best overall quality row appears first in the merged set, regardless of whether it came from qB RSS or Torrentio.
- Locally available exact variants remain upgraded to local playback without removing remote fallbacks.
- qB-authored rows expose enough visible detail that users can distinguish variants without opening raw JSON.
- Saved-rule/main-app IMDb-first series searches preserve episode-floor precision before broad title fallback, reducing ambiguous-title regressions for remakes such as `Ghosts`.
- Focused pytest plus addon/desktop smoke checks pass for the merged ordering behavior.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P23-01 | Decide the provider aggregation architecture for global ordering. | Codex | 2026-03-30 | in progress | The phase records the chosen merge strategy, the Stremio grouping constraint, and which precursor fixes can land before full aggregation. | 2026-03-30 user follow-up confirms the grouped-addon limitation remains visible in the desktop client and that row-attribution plus qB search-precision work should land as immediate precursors. |
| P23-02 | Implement qB-side row-attribution and series-precision precursors. | Codex | 2026-03-30 | completed | qB rows are more descriptive, the main qB RSS Jackett path carries series episode-floor precision before broad fallback, season-finale `S(next)E00` floors survive edit-form round trips, aggregate-empty IMDb searches still probe direct IMDb-capable indexers before title fallback, primary IMDb-first local filtering keeps quality/structural narrowing separate from fallback-only text regex refinement, the rules page surfaces remembered exact-result summary/filter state for saved rules, `bluray` exclusions no longer hide `BDRip/BRRip` exact rows, and the live Stremio HTTP addon keeps the full cold exact stream set for `The Beauty` episode probes. | Landed in `app/services/jackett.py`, `app/routes/pages.py`, `app/services/stremio_addon.py`, `app/schemas.py`, `app/services/rule_fetch_ops.py`, `app/services/rule_search_snapshots.py`, `app/services/settings_service.py`, `app/models.py`, `app/db.py`, `app/templates/index.html`, `app/static/app.js`, `scripts/closeout_browser_qa.py`, and `scripts/stremio_addon_smoke.py`; 2026-04-02 follow-ups fixed `start_episode=0` edit-form rendering in `app/routes/pages.py`, added route/browser QA regression coverage in `tests/test_routes.py` and `scripts/closeout_browser_qa.py`, and added direct-indexer IMDb-empty regression coverage in `tests/test_jackett.py`; the 2026-04-03 follow-up added dedicated primary-filter keyword fields, route wiring for quality-only primary payloads, multiple movie/series precise-vs-fallback regressions in `tests/test_jackett.py` and `tests/test_routes.py`, a `bluray` versus `BDRip/BRRip` taxonomy split plus focused regressions in `tests/test_quality_filters.py` and `tests/test_jackett.py`, a stable direct-execution path for `scripts/stremio_addon_smoke.py`, a slightly larger `STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS` in `app/services/stremio_addon.py`, and a deterministic closeout matrix that now passes in `logs/qa/phase-closeout-20260403T093533Z/closeout-report.md`. |
| P23-02A | Add an exact-variant Stremio-to-qB fallback bridge while global aggregation remains pending. | Codex | 2026-04-12 | completed | The repo can accept a Stremio-selected `infoHash`/tracker payload, build a magnet, queue it to qB, optionally prioritize the exact `fileIdx` variant after qB metadata loads, and expose a practical UI surface for pasting AIOStreams/Stremio stream JSON into that flow. | Landed in `app/services/selective_queue.py`, `app/routes/api.py`, `app/schemas.py`, `app/templates/search.html`, `app/static/app.js`, `tests/test_selective_queue.py`, and `tests/test_routes.py`; validated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_routes.py -k "stremio_queue or queue_search_result or queue_stremio_stream or build_magnet_link"` (`8 passed`), `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "search_page_renders_jackett_as_separate_source or search_page_js_supports_stremio_variant_queue_bridge or queue_stremio_stream"` (`4 passed`), and focused Ruff checks on the touched Python files (`All checks passed`). |
| P23-02B | Add rule-level Jackett preferred-language routing and safety diagnostics. | Codex | 2026-04-18 | pending | Rules can declare ordered language preferences (`ru`, `he`, `en`), the Jackett request layer converts them into filter-indexer expressions when language metadata coverage is safe, and the UI/settings layer reports coverage + fallback behavior clearly. | Pending. |
| P23-02C | Add release/versioning automation for synchronized sub-version prep. | Codex | 2026-04-18 | in progress | The repo has a repeatable tool/script path for SemVer bump selection, synchronized version touchpoints, changelog scaffolding, and review-ready release branch/PR metadata. | `app/services/release_versioning.py`, `scripts/release_prep.py`, and `tests/test_release_versioning.py` added on 2026-04-17 as the initial release-prep automation slice. |
| P23-03 | Implement merged stream collection, ranking, and dedupe. | Codex | 2026-03-31 | pending | The addon can emit one globally ordered stream list across qB RSS and Torrentio-compatible inputs. | Pending. |
| P23-04 | Revalidate merged ordering in backend and real desktop smoke. | Codex | 2026-03-31 | pending | The merged ordering contract is green in both automated layers. | Pending. |

## Risks And Follow-Up

### Risk: third-party provider integration could be brittle or rate-limited

- Trigger: relying on external addon/provider responses may introduce schema drift, latency spikes, or availability failures.
- Impact: the merged addon could become less reliable than the current qB RSS-only path.
- Mitigation: isolate provider adapters, cache carefully, and keep qB RSS-only fallback behavior explicit.
- Owner: Codex
- Review date: 2026-03-29
- Status: open

### Risk: merged ordering may blur provider identity

- Trigger: combining sources into one addon block can hide where a stream came from.
- Impact: users may lose confidence in why one result outranks another.
- Mitigation: include provider attribution in row titles/descriptions and cover that in smoke assertions.
- Owner: Codex
- Review date: 2026-03-29
- Status: open

## Next Concrete Steps

1. Prove the Stremio grouping limitation with one focused design note tied to the existing desktop smoke evidence and the current lack of a Torrentio-compatible provider adapter in the repo.
2. Investigate why the wrapped qB RSS addon returns `0` streams through AIOStreams for `tt33517752:1:1` while Torrentio resolves many valid rows under the same AIO profile.
3. Choose the merge strategy for Torrentio plus qB RSS without regressing local playback.
4. Decide whether the completed qB precision/attribution precursors and the new exact-variant queue bridge should ship ahead of the full provider-aggregation slice or roll into the same release.
5. Keep the deterministic browser-closeout matrix for one series exact rule, one `E00` special rule, multiple movie exact rules, and the `bluray` versus `BDRip` taxonomy split in sync with the precise-vs-fallback request contract now that it is part of the acceptance surface.
6. Implement rule-level preferred-language fields and a Jackett diagnostics pass that proves language metadata coverage on the active instance before automatic feed-selection deprecation starts.
7. Extend the Jackett request layer to prefer `lang:<code>` filtered pools in user-specified order (`ru` first, then `he`/`en` fallback) while retaining a controlled escape hatch for explicit manual feeds.
8. Expand the new release-prep tooling from synchronized version bump + changelog scaffolding into the full review/publish workflow: branch naming, stale-version verification, push guidance, and PR checklist output.

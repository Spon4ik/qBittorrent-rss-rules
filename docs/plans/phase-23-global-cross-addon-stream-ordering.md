# Phase 23: Global Cross-Addon Stream Ordering

## Status

- Plan created on 2026-03-28 immediately after the `v0.8.2` phase-22 release closeout.
- Phase 23 is now closed and release-validated in `v0.9.0`.
- Implementation started on 2026-03-30 after a user-reported follow-up confirmed three linked gaps: Stremio still groups Torrentio, IMDb info, and qB RSS into separate blocks; qB-authored stream rows are less descriptive than Torrentio rows; and the main qB RSS app still falls back too quickly on ambiguous series because it does not carry the rule episode-floor context into the Jackett IMDb-first path.
- The qB-side precursor implementation landed locally on 2026-03-30 in `app/services/jackett.py`, `app/routes/pages.py`, `app/services/stremio_addon.py`, `app/schemas.py`, and focused route/service tests.
- A follow-up regression fix landed on 2026-04-02 so season-finale rules that advance to `S(next)E00` no longer render `start_episode=0` as a blank edit-form field, which had been dropping the episode floor on re-save and broadening later rule searches.
- A second follow-up precision fix landed on 2026-04-02 so IMDb-first qB RSS searches no longer skip straight to title fallback when Jackett's aggregate `all` endpoint returns an empty success for `imdbid`; the app now probes direct configured IMDb-capable indexers before broadening.
- A third qB-side precision follow-up landed on 2026-04-03 so IMDb-first primary results no longer inherit fallback-only regex/manual text filters; exact runs now keep quality and structural narrowing while broad text refinement remains on fallback rows.
- A fourth follow-up QA/visibility pass landed later on 2026-04-03 so the rules page exposes exact-result counts/filters with remembered selections, the closeout harness exercises multiple movie/series exact-vs-fallback rules end-to-end, and the deterministic browser environment now disables background schedulers that were mutating seeded QA floors during closeout.
- A fifth qB-side filtering follow-up landed on 2026-04-03 so the quality taxonomy no longer lets `bluray` over-match `BDRip/BRRip`; exact disc-rip rows now stay visible unless a rule explicitly excludes `bdrip`.
- A sixth release-validation follow-up landed later on 2026-04-03 so the deterministic browser closeout loads the exact-filter URL directly instead of depending on a flaky same-page submit transition, the direct Stremio smoke script now delegates to module mode for stable imports, and the live HTTP addon path gets enough collection budget to keep the full exact stream set on cold episode requests.
- A seventh qB-side trust/debug follow-up landed on 2026-04-07 so the desktop unified search workspace keeps exact rows above fallback rows, same-infohash duplicates are grouped instead of discarded, grouped queue actions can merge missing trackers into an existing qB torrent, and Stremio qB rows expose clearer provenance/source hints for choosing between near-duplicate variants.
- An eighth parity follow-up landed later on 2026-04-07 after a real user repro (`The Rookie S08E13`) showed the desktop qB search path still lagged the addon path: desktop manual `/search` requests with IMDb context now auto-derive `season_number` / `episode_number` from episode-style query text (`S08E13`, `14x01`) before enabling IMDb-first search, and they now clear `release_year` for those episode-style series searches so a stale or over-specific year cannot suppress valid matches the addon would still show.
- Provider-aggregation implementation started on 2026-04-07 by adding an env-configured external Stremio manifest adapter surface, merged candidate ranking/dedupe inside the local addon stream response, and focused addon regressions that prove Torrentio-compatible rows can interleave with qB RSS rows inside one returned stream block.
- A `tt22074164` follow-up landed later on 2026-04-07 after a user-reported mismatch showed that both the desktop app and the addon still lagged Torrentio on subtitle-style titles: IMDb-first Jackett searches now generate broader title-surface variants and still run the broad title fallback lane when exact/precise title probes return nothing, Stremio catalog title search now falls back to Cinemeta when OMDb search is empty so `Jury Duty Presents: Company Retreat` remains discoverable before stream lookup, empty-success Jackett searches now continue into category-relaxed fallback params instead of stopping at the first `200` response, and Stremio episode lookup now prefers the subtitle-tail query surface (`Company Retreat`) for colon titles so the live addon returns real streams for `tt22074164:1:1` and `tt22074164:1:2` inside the desktop smoke flow.
- A second `tt22074164` parity follow-up landed later the same day after the user showed that one 720p row was still far short of Torrentio parity and that the visible Stremio list still hid tracker names: the addon now opens one unstructured subtitle-title Jackett probe when the structured IMDb/season path is too thin, the visible qB row name now includes the source/indexer, and IMDb-backed series searches now clear stale `release_year` even when the episode floor is already explicit in the desktop payload.
- A third `tt22074164` parity follow-up landed later the same day after the next user pass showed that the left-column format had regressed and a non-video RuTracker false positive could still leak through broad subtitle fallback: the qB row name is now back to `addon + quality` only, tracker/source remains visible in the main row detail line, and parsed torrent payloads whose selected episode file is not a video file are now rejected before stream emission.
- A fourth `tt22074164` parity follow-up landed on 2026-04-08 after live probing showed the desired Torrentio hash was actually reachable through Jackett season-pack results but our addon was stopping too early on subtitle-tail TPB episode rows: episode fallback now tries a short series-title variant ladder, episode requests can keep valid season-pack rows instead of demanding an explicit `SxxExx` title token, and a new env-backed preferred-language filter (`QB_RULES_STREMIO_PREFERRED_LANGUAGES`) keeps matching language variants when available so the addon can surface the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` row under `ru` preference during live smoke.
- A fifth `tt22074164` parity follow-up landed later the same day so the new language preference is no longer launch-only: the repo now persists `stremio_preferred_languages` through `/settings`, env override still wins when present, and episode HTTP torrent parsing no longer accepts arbitrary single-file movie torrents when no file path matches the requested episode, which removed the briefly reintroduced `1995 Jury Duty` false positive during the saved-setting smoke.
- A sixth `tt22074164` parity follow-up landed on 2026-04-08 around the desktop/addon engine split:
  - updated `app/routes/pages.py` so IMDb-backed movie/series desktop searches now use the addon-enriched collector as their primary result set and only add a separate Jackett search as supplemental fallback, which matches the intended product shape more closely than the earlier "desktop first, addon merge later" contract;
  - synced the rendered `/search` form back to the post-auto-IMDb payload so stale year floors cleared by episode detection no longer stay visible in the HTML and silently re-hide rows on the client;
  - added focused route regressions proving the addon-baseline desktop contract and the cleared-year form rendering;
  - after replacing the addon broad subtitle fallback with direct configured Jackett `search` indexers instead of the aggregate `all` endpoint, fresh live smoke on `http://127.0.0.1:8027` again returned the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` row in both the addon and desktop `/search`, but the cold-path latency remains too high for release closeout (`~34s` addon, `~36s` desktop).
- A seventh phase-23 stabilization follow-up landed later on 2026-04-08 while continuing implementation against the same desktop/addon split:
  - updated `app/services/stremio_addon.py` so the addon-side unstructured direct-title fallback no longer fails the entire stream lookup when the configured-indexer capability probe errors; it now records the probe failure as a warning and degrades cleanly;
  - realigned `tests/test_jackett.py` with the now-intended live-safe request sequence, covering the extra cat/no-cat retries, direct-indexer IMDb probes, and `t=search` broad-title fallbacks added by the recent `tt22074164` fixes;
  - reran the focused phase-23 pytest/ruff/mypy slice and returned the in-flight worktree to a green automated state before continuing on latency reduction.
- An eighth phase-23 latency follow-up landed later on 2026-04-08 to trim the broad subtitle fallback fan-out before another live pass:
  - updated `app/services/stremio_addon.py` so addon-only unstructured `t=search` fallback now sorts configured direct-search indexers by a small known-good priority ladder, caps fan-out to a short shortlist, and records the chosen shortlist in warning text for live profiling;
  - added focused regression coverage in `tests/test_stremio_addon.py` proving the shortlist is deterministic and capped before direct search work is submitted;
  - reran the focused phase-23 pytest/ruff/mypy slice so the worktree stays green while the remaining latency proof moves back to live smoke.
- A ninth phase-23 latency follow-up landed later the same day after live profiling showed the first shortlist trim still spent too much time on low-value fallbacks:
  - updated `app/services/stremio_addon.py` so the direct `t=search` fallback now keeps only explicitly preferred video indexers once enough of them are available, drops `thepiratebay` from the preferred ladder for this path, and stops the broad title-variant loop as soon as a preferred-language episode match has already been found;
  - added focused regressions in `tests/test_stremio_addon.py` for the preferred-only shortlist and for the preferred-language early-stop behavior, then reran `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` plus `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py`;
  - fresh live profiling with `QB_RULES_STREMIO_PREFERRED_LANGUAGES=ru` shows `collect_enriched_search_run(...)` for `tt22074164` episode 1 down to about `11.5s`, and `stream_lookup(...)` still returns the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` hash for episodes 1 and 2 while trimming the cold path to about `20.4s` / `19.5s`, so the remaining latency cost is now beyond the first shortlist gate.
- A tenth phase-23 search-contract follow-up landed later on 2026-04-08 after the user showed precise IMDb-backed rows being hidden by the desktop app even though the structured lookup had found the right season-pack results:
  - updated `app/static/app.js` so precise primary rows in the IMDb-backed lane no longer have to pass client-side free-text title matching or exact-title-identity checks after they have already reached the precise result set;
  - fallback/non-precise rows still keep the broader query/pattern filtering path, preserving the trust/debug split while stopping false negatives for translated or season-pack exact rows such as `Jury Duty [S01]` that do not literally contain `Jury Duty Presents: Company Retreat`;
  - updated the static assertions in `tests/test_routes.py` and revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -q`.
- An eleventh phase-23 latency follow-up landed on 2026-04-09 after profiling showed the remaining stream-path cost was still dominated by opening obviously wrong-season HTTP torrents:
  - updated `app/services/stremio_addon.py` so episode requests now reject rows that already advertise a conflicting explicit season before HTTP torrent inspection, while still allowing truly ambiguous HTTP rows through to payload-level episode detection;
  - added focused regression coverage in `tests/test_stremio_addon.py` proving `S02` HTTP rows are skipped for `S01E01` while matching `S01` and subtitle-ambiguous rows still remain eligible;
  - reran `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` plus `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py`;
  - fresh in-process profiling with `QB_RULES_STREMIO_PREFERRED_LANGUAGES=ru` now shows the `tt22074164` stream path down to about `11.9s` for episode 1 and `11.5s` for episode 2, with HTTP torrent fetches on episode 1 reduced from 9 to 6 and the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` row still preserved.
- A twelfth phase-23 search-collection follow-up landed later on 2026-04-09 to cut low-value broad fallback queries earlier in the `tt22074164` path:
  - updated `app/services/stremio_addon.py` so colon-style episode broad fallback now tries the stripped base series title immediately after the subtitle-tail query, ahead of the noisier full subtitle text and raw prefix variants;
  - added a focused unit regression in `tests/test_stremio_addon.py` that locks the new variant order, and updated the non-video broad-fallback regression to reflect the earlier base-series probe;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` (`25 passed`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py` (`All checks passed`);
  - live timing proof is still pending, but the expected next check is now narrower: confirm the earlier base-series probe reduces the remaining search-collection cost while preserving the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` row.
- A fourteenth phase-23 search-collection follow-up landed later on 2026-04-09 to trim the remaining exact-versus-text episode wait:
  - updated `app/services/stremio_addon.py` so the episode collector now stops waiting on the slower text `SxxExx` Jackett lane once the exact IMDb episode run has already produced enough requested-episode matches, while still requiring a preferred-language hit when that preference is configured;
  - relaxed the older stream-route regression in `tests/test_stremio_addon.py` so it accepts the new smarter behavior where the text lane may be skipped entirely when the exact lane wins the race, and added a new direct regression proving `collect_enriched_search_run(...)` returns before a deliberately blocked text worker finishes once the exact lane is already sufficient;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` (`26 passed`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py` (`All checks passed`);
  - fresh live timing proof is still pending, but the next `tt22074164` profiling run should now show whether the remaining search-collection cost was materially coming from the no-longer-needed text lane.
- A fifteenth phase-23 stream-path follow-up landed later on 2026-04-09 after live instrumentation showed episode 1 still downloading two bogus `Jury Duty (1995)` movie torrents:
  - updated `app/services/stremio_addon.py` so episode requests now reject HTTP fallback rows that expose a standalone explicit year but still lack any requested episode or season-pack signal, instead of sending those plain movie titles through torrent inspection just because they are HTTP links;
  - widened the focused episode-match regression in `tests/test_stremio_addon.py` to lock out the `Jury Duty (1995)` style false positive while keeping matching season-pack rows and genuinely ambiguous subtitle rows eligible;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` (`26 passed`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py` (`All checks passed`);
  - fresh live instrumentation with `QB_RULES_STREMIO_PREFERRED_LANGUAGES=ru` now shows the `tt22074164:1:1` stream path down to about `7.5s`, with broad fallback still limited to the `Company Retreat` and `Jury Duty` probes but HTTP torrent downloads reduced from `3` to `1` while preserving the wanted `14544b87fe01a84ffb8a3b75c5c9094180029fd9` row; the non-instrumented service smoke now lands at roughly `7.8s` for episode 1 and `8.4s` for episode 2.
- A sixteenth phase-23 playback-integrity follow-up landed later on 2026-04-09 after the user reported qB-backed Stremio episode playback opening the wrong file from a season pack:
  - traced the root cause to episode file selection matching tokens against the entire path instead of preferring the basename, so a parent folder like `S08E01-E14/.../S08E10.mkv` could make the addon treat `E10` as a valid match for an `E12` request and then emit the wrong `fileIdx`;
  - updated `app/services/selective_queue.py` so `find_episode_file_entry(...)` now ranks basename episode matches ahead of parent-folder season-pack ranges, and updated `app/services/local_playback.py` so qB local-playback inventory uses the same basename-first episode ranking instead of the older whole-path first-match behavior;
  - added focused regressions in `tests/test_selective_queue.py`, `tests/test_local_playback.py`, and `tests/test_stremio_addon.py` that lock the exact failure shape: a season-pack parent folder with `E10` and `E12` child files must select and emit `E12` for an `S08E12` request;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_local_playback.py tests\\test_stremio_addon.py -q` (`40 passed`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\selective_queue.py app\\services\\local_playback.py app\\services\\stremio_addon.py tests\\test_selective_queue.py tests\\test_local_playback.py tests\\test_stremio_addon.py` (`All checks passed`).
- A thirteenth phase-23 queue-hardening follow-up landed later on 2026-04-09 after the user hit qB add failures on Jackett-hosted `http://localhost:9117/dl/...` URLs:
  - traced the issue to the queue path passing raw Jackett HTTP download links directly into qB's `add_torrent_url(...)`, which is brittle whenever qB does not share the app host's loopback view and unnecessary for `.torrent` results that the app can already fetch itself;
  - updated `app/services/selective_queue.py` so non-magnet HTTP torrent links now prefer app-side download plus `add_torrent_file(...)` upload into qB, with fallback to the older remote URL path only when the app cannot fetch or validate the torrent bytes;
  - added focused regressions in `tests/test_selective_queue.py` and `tests/test_routes.py` that lock the new behavior for Jackett `localhost:9117` download URLs and prove the queue API no longer asks qB to fetch those links remotely when file upload is available;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_routes.py -k "queue_search_result_api_uploads_http_torrent_file_to_qb_instead_of_remote_url_fetch or queue_result_with_optional_file_selection_uploads_http_torrent_file_without_rule or queue_search_result_api_uses_settings_default_pause_when_no_rule or queue_search_result_api_applies_rule_defaults" -q` plus `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\selective_queue.py tests\\test_selective_queue.py tests\\test_routes.py`.
- A seventeenth phase-23 queue-hardening follow-up landed later on 2026-04-09 after the next live repro showed qB desktop "Add torrent failed" notifications still repeating for broken `http://127.0.0.1:9117/dl/...` links:
  - updated `app/services/selective_queue.py` so loopback/private HTTP torrent URLs now require successful app-side download plus torrent validation before the app will queue them, instead of falling back to qB remote URL fetch after the local Jackett-style fetch has already failed;
  - this intentionally keeps the error inside the app/API path for local/private Jackett URLs, because asking qB to retry those broken loopback links remotely is what produced the noisy desktop notification loop;
  - added focused regressions in `tests/test_selective_queue.py` and `tests/test_routes.py` that lock the new "fail once locally, do not remote-fetch" behavior for broken `127.0.0.1:9117/dl/...` results, then revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_routes.py -k "broken_local_jackett_url or uploads_http_torrent_file" -q` and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\selective_queue.py tests\\test_selective_queue.py tests\\test_routes.py`.
- An eighteenth phase-23 queue-hardening follow-up landed on 2026-04-10 for mixed app/qB Jackett host setups:
  - updated `app/services/selective_queue.py` and `app/routes/api.py` so queue-time app-side torrent fetch rewrites Jackett-style `dl/...` result URLs from the qB-facing Jackett base (`jackett_qb_url`) back to the app-facing Jackett base (`jackett_api_url`) before download and validation, which fixes valid local uploads when qB and the app intentionally reach Jackett through different hostnames;
  - kept the earlier loopback/private-host guard intact, so genuinely broken local Jackett downloads still stop in the app instead of falling through to qB remote URL fetch;
  - added focused regressions in `tests/test_selective_queue.py` and `tests/test_routes.py` proving qB-facing Jackett result URLs are normalized back to the app-side host during queue upload while the broken-local-URL rejection behavior stays locked;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_routes.py -k "jackett_qb_url_for_app_fetch or broken_local_jackett_url or uploads_http_torrent_file" -q` (`6 passed`) and `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\selective_queue.py app\\routes\\api.py tests\\test_selective_queue.py tests\\test_routes.py` (`All checks passed`).
- A nineteenth phase-23 search-collection follow-up landed on 2026-04-10 to stop paying qB breadth costs the merged provider surface can already cover:
  - updated `app/services/stremio_addon.py` so when external provider manifests are configured and the exact IMDb episode lane already yields at least one usable requested-episode match, the collector now skips the extra qB season and broad-title fallback ladder instead of spending more cold-path budget synthesizing additional qB breadth;
  - kept qB-only behavior unchanged, so the broader season/title fallback ladder still runs when no external provider block is available to contribute the extra rows;
  - added focused regressions in `tests/test_stremio_addon.py` proving provider-backed collection no longer opens broad-title fallback after an exact usable hit, while the exact-lane early-return test stays locked;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` (`28 passed`), `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\stremio_addon.py tests\\test_stremio_addon.py` (`All checks passed`), and `.\\.venv\\Scripts\\python.exe -m mypy app\\services\\stremio_addon.py` (`Success: no issues found in 1 source file`).
- A twentieth phase-23 stabilization follow-up landed later on 2026-04-10 to restore the desktop exact-versus-fallback split after the addon-baseline work started collapsing broad recovery rows back into the precise lane:
  - updated `app/services/stremio_addon.py` so `collect_enriched_search_run(...)` now preserves broad episode/title recovery rows in `fallback_results` rather than returning every recovered row inside `results`, which keeps addon-enriched desktop baselines aligned with the intended precise-vs-fallback contract;
  - updated `app/static/app.js` so local unified-result filtering, source counters, and title sorting now use an effective source classification: precise IMDb-backed rows that retain the exact IMDb hit or exact title identity stay primary, while non-exact primary rows are demoted into the fallback lane for local filtering/counting without re-hiding translated or season-pack exact matches;
  - updated `scripts/closeout_browser_qa.py` so the title-sort closeout assertions follow the intended exact-first-then-title ordering contract instead of assuming a flat pure-title sort across mixed primary/fallback rows;
  - added focused regressions in `tests/test_stremio_addon.py` for the restored precise/fallback split and refreshed the static route assertions in `tests/test_routes.py`;
  - revalidated with `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py tests\\test_stremio_addon.py -q`, `cmd /c scripts\\closeout_qa.bat` (all browser closeout checks passed under `logs\\qa\\phase-closeout-20260410T200153Z\\`), `cmd /c scripts\\check.bat` (`329 passed`), and `cmd /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
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

## Scope Expansion (2026-04-07 qB-side trust/debug split)

8. Keep one combined desktop results workspace, but make exact-vs-fallback ordering explicit while still showing hidden fetched rows and blocker reasons for debugging.
9. Group same-infohash result rows instead of dropping later duplicates, preserve grouped provenance/indexers/links/trackers for queue/debug actions, and let grouped queue actions fan out to all same-hash variants while merging missing trackers into qB.
10. Enrich qB-authored Stremio stream labels so provenance, size, peer/leech/grab context, source-count hints, and filename hints remain visible without opening raw JSON.
11. Record music/audiobook precise search as the next Jackett cleanup/backlog slice: add structured request fields now, but keep the broader direct-indexer and regex-reduction cleanup separate from the active provider-aggregation work.

## In Scope

- Addon/provider aggregation design for Stremio stream delivery.
- Ranking and dedupe logic for merged provider rows.
- Row text/metadata changes needed to preserve provider attribution after aggregation.
- qB-authored row-title/detail improvements needed to keep variants distinguishable in the native addon.
- Series episode-floor request-contract improvements needed for qB RSS main-app IMDb-first search parity with the addon path.
- Desktop unified-result ordering/debug improvements, grouped same-hash queue metadata, and qB tracker-merge helpers needed to make the pre-aggregation qB result set trustworthy.
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
- Desktop unified search keeps exact/primary rows ahead of fallback rows while still exposing hidden fetched rows and grouped same-hash metadata for debugging/queue actions.
- Focused pytest plus addon/desktop smoke checks pass for the merged ordering behavior.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P23-01 | Decide the provider aggregation architecture for global ordering. | Codex | 2026-03-30 | in progress | The phase records the chosen merge strategy, the Stremio grouping constraint, and which precursor fixes can land before full aggregation. | 2026-03-30 user follow-up confirms the grouped-addon limitation remains visible in the desktop client and that row-attribution plus qB search-precision work should land as immediate precursors. |
| P23-02 | Implement qB-side row-attribution and series-precision precursors. | Codex | 2026-03-30 | completed | qB rows are more descriptive, the main qB RSS Jackett path carries series episode-floor precision before broad fallback, season-finale `S(next)E00` floors survive edit-form round trips, aggregate-empty IMDb searches still probe direct IMDb-capable indexers before title fallback, primary IMDb-first local filtering keeps quality/structural narrowing separate from fallback-only text regex refinement, the rules page surfaces remembered exact-result summary/filter state for saved rules, `bluray` exclusions no longer hide `BDRip/BRRip` exact rows, the desktop unified search keeps exact rows above fallback rows with grouped same-hash queue/debug metadata, grouped queue actions can merge missing trackers into qB, manual desktop episode queries with IMDb context auto-derive the same episode-floor targeting signal the addon uses and drop the over-constraining year floor, and the live Stremio HTTP addon keeps the full cold exact stream set for `The Beauty` episode probes. | Landed in `app/services/jackett.py`, `app/routes/pages.py`, `app/routes/api.py`, `app/services/stremio_addon.py`, `app/services/selective_queue.py`, `app/services/qbittorrent.py`, `app/schemas.py`, `app/services/rule_fetch_ops.py`, `app/services/rule_search_snapshots.py`, `app/services/settings_service.py`, `app/models.py`, `app/db.py`, `app/templates/index.html`, `app/templates/search.html`, `app/templates/rule_form.html`, `app/static/app.js`, `scripts/closeout_browser_qa.py`, and `scripts/stremio_addon_smoke.py`; 2026-04-02 follow-ups fixed `start_episode=0` edit-form rendering in `app/routes/pages.py`, added route/browser QA regression coverage in `tests/test_routes.py` and `scripts/closeout_browser_qa.py`, and added direct-indexer IMDb-empty regression coverage in `tests/test_jackett.py`; the 2026-04-03 follow-up added dedicated primary-filter keyword fields, route wiring for quality-only primary payloads, multiple movie/series precise-vs-fallback regressions in `tests/test_jackett.py` and `tests/test_routes.py`, a `bluray` versus `BDRip/BRRip` taxonomy split plus focused regressions in `tests/test_quality_filters.py` and `tests/test_jackett.py`, a stable direct-execution path for `scripts/stremio_addon_smoke.py`, a slightly larger `STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS` in `app/services/stremio_addon.py`, and a deterministic closeout matrix that now passes in `logs/qa/phase-closeout-20260403T093533Z/closeout-report.md`; the 2026-04-07 follow-ups added grouped same-hash result metadata and queue tracker merge support plus focused regressions in `tests/test_qbittorrent_client.py`, `tests/test_selective_queue.py`, `tests/test_jackett.py`, `tests/test_routes.py`, and `tests/test_stremio_addon.py`, then tightened desktop IMDb-first parity with new route regressions for manual episode queries such as `The Rookie S08E13` and `Death in Paradise 14x01`, including automatic year-floor removal for episode-style series queries. |
| P23-03 | Implement merged stream collection, ranking, and dedupe. | Codex | 2026-03-31 | completed | The addon can emit one globally ordered stream list across qB RSS and Torrentio-compatible inputs. | 2026-04-07 local implementation adds env-configured external manifest adapters via `QB_RULES_STREMIO_STREAM_PROVIDER_MANIFESTS`, merges provider rows into the addon stream candidate pool, ranks/dedupes by shared quality-first keys, preserves provider attribution in merged row text, keeps the existing local-playback upgrade path on the merged candidate set, and fixes the `tt22074164` subtitle-title miss by broadening IMDb-first desktop/manual title variants plus adding a Cinemeta catalog fallback when OMDb title search is empty; the 2026-04-11 closeout persists provider manifests in `/settings`, fixes comma-safe manifest parsing, quotes episode ids in provider URLs, and hardens external fetches with browser-like headers so live provider ingestion now works from the local addon as well. |
| P23-04 | Revalidate merged ordering in backend and real desktop smoke. | Codex | 2026-03-31 | completed | The merged ordering contract is green in both automated layers. | Final release validation on 2026-04-11 includes `cmd /c scripts\\check.bat` (`337 passed`), `cmd /c scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260410T222004Z\\`), `cmd /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), fresh HTTP addon smoke on `http://127.0.0.1:8001` showing merged `Torrentio` plus `qB RSS Rules` rows for `tt22074164`, and real desktop smoke artifacts under `logs\\qa\\stremio-desktop-smoke-20260410T221925Z\\` proving the visible merged-provider local-addon surface in the Stremio client. |

- 2026-04-11 follow-up: qB-authored HTTP-torrent and season-pack rows now preserve the selected file's own byte size instead of showing only the enclosing torrent size, which brings the stream detail line closer to Torrentio's file-specific metadata behavior.
  - `app/services/selective_queue.py` now preserves optional per-file sizes for parsed `.torrent` files and normalized qB file inventories.
  - `app/services/stremio_addon.py` now carries selected file size through target resolution, renders that file size first in the `💾` detail, keeps `Pack ...` as secondary context when the selected file came from a larger torrent, and exposes `behaviorHints.videoSize` beside filename and `fileIdx`.
  - Focused regressions landed in `tests/test_stremio_addon.py`, and the additive parser change stayed green across `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_selective_queue.py tests\\test_local_playback.py tests\\test_stremio_addon.py -q` (`44 passed`), Ruff, and mypy.
- 2026-04-11 release closeout: the remaining provider-ingestion blockers were removed and the merged addon surface was proven end-to-end.
  - `app/models.py`, `app/db.py`, `app/schemas.py`, `app/routes/api.py`, `app/services/settings_service.py`, and `app/templates/settings.html` now persist `stremio_stream_provider_manifests` through `/settings`, normalize manifest entries safely even when real provider URLs contain commas inside option payloads, and keep env override precedence explicit.
  - `app/services/stremio_addon.py` now URL-encodes Stremio episode item ids in provider stream URLs and uses browser-like request headers for external provider fetches, which restored live Torrentio-compatible ingestion instead of receiving Cloudflare-blocked HTML.
  - Focused regressions landed in `tests/test_settings_service.py`, `tests/test_routes.py`, and `tests/test_stremio_addon.py` for persisted provider manifests, comma-safe parsing, quoted episode ids, and browser-header provider fetches.
  - Fresh validation now includes `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_settings_service.py tests\\test_routes.py tests\\test_stremio_addon.py -q`, `cmd /c scripts\\check.bat` (`337 passed`), `cmd /c scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260410T222806Z\\`), `cmd /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), fresh HTTP addon smoke on `http://127.0.0.1:8002`, and real desktop smoke under `logs\\qa\\stremio-desktop-smoke-20260410T223201Z\\` showing visible `Torrentio` plus `qB RSS Rules` rows from the local merged addon response.

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

1. Decide which post-`v0.9.0` Stremio/catalog follow-up becomes the next planned phase.
2. Keep the persisted external-provider manifest path, comma-safe parsing contract, and browser-header provider fetch path in the focused settings/addon regression set whenever provider wiring changes again.
3. Keep `tt22074164` (`Jury Duty Presents: Company Retreat`) in the focused desktop `/search`, addon smoke, and real desktop smoke set as the standing regression title for subtitle-tail recovery and merged provider ordering.
4. Keep the selected-file metadata contract intact: when playback resolves a concrete episode file from a larger torrent pack, the row should render the selected file size first, keep pack size only as secondary context, and preserve `behaviorHints.videoSize` / filename / `fileIdx` together.
5. Keep the older `tests/test_jackett.py` fallback-contract assertions aligned with the live-safe production ladder (`imdbid` no-cat retries, empty-success category relaxation, broader title-primary retries) whenever the broad fallback sequencing changes again.

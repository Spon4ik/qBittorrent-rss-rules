# Phase 21: Stremio Stream Ordering And Local Playback

## Status

- Plan baseline created on 2026-03-28 immediately after the `v0.8.0` phase-20 closeout.
- Implementation landed on 2026-03-28 and phase 21 is now closed and release-validated in `v0.8.1`.
- The real desktop client now renders qB RSS local/direct playback rows with the strongest playable variant first, and completed qB media files can be streamed directly from the local backend instead of only via torrent metadata.

## Goal

Improve the live Stremio addon experience now that qB RSS rows render in the desktop client by making the best qB RSS variant rank first and by turning already-downloaded qB content into materially better local playback instead of just another remote torrent candidate.

## Requested Scope (2026-03-28)

1. Make qB RSS stream ordering prefer the strongest playback variant first, especially when 4K and 1080p variants are both present.
2. Improve playback when the requested torrent content is already complete in the local qBittorrent session, so pre-downloaded content provides noticeably better Stremio playback instead of remote-like buffering.
3. Keep the implementation generic enough that future providers can reuse the same centralized playback-routing decisions instead of duplicating Stremio- or qB-specific heuristics in multiple places.
4. Keep the real Stremio desktop smoke and backend addon smoke as the acceptance pair for the slice.

## In Scope

- qB RSS addon result ranking changes in `app/services/stremio_addon.py`.
- Any new qBittorrent client methods needed to inspect live torrent state and file paths for playback acceleration.
- A local backend route/service path that can safely expose completed qB-backed media files to Stremio for direct local playback when appropriate.
- Addon stream payload changes needed to surface direct local playback streams ahead of torrent-only streams.
- Focused pytest coverage for ranking, qB playback resolution, and the new addon payload/route behavior.
- Smoke validation with `scripts/stremio_addon_smoke.py` and `scripts/stremio_desktop_smoke.py`.

## Out Of Scope

- General-purpose remote streaming for users who do not have local qB content already downloaded.
- Non-qB local media libraries outside the already configured qBittorrent session.
- A full Stremio addon configuration UI or published remote addon hosting.
- Broader provider-ranking redesign outside the Stremio qB RSS addon path.
- Jellyfin/Stremio watched-progress arbitration changes unrelated to playback selection.

## Key Decisions

### Decision: phase 21 should optimize for best-playable-first, not compatibility-first

- Date: 2026-03-28
- Context: The current addon intentionally mixes a compatibility-first pass with a quality-first pass, which can leave `2160p` below `1080p` even when both rows are shown and even when the user filters down to qB RSS only.
- Chosen option: treat the strongest viable variant as the default first stream and demote compatibility fallbacks behind it.
- Reasoning: Once qB RSS rows visibly render in Stremio, the next UX expectation is that the best candidate appears first, not that the safest torrent transport always wins the top slot.
- Consequences: Ranking logic and tests must be updated together, and any local-direct playback stream should outrank torrent-only fallbacks when available.

### Decision: use qB-completed local files to accelerate playback instead of relying only on torrent swarm behavior

- Date: 2026-03-28
- Context: If the requested content is already fully downloaded in qB, returning only torrent metadata still leaves Stremio dependent on the torrent client path and swarm/tracker behavior, which wastes the user's deliberate pre-download.
- Chosen option: resolve matching completed qB torrents/files and expose a direct local playback path from this backend so Stremio can use the already-available local file.
- Reasoning: This is the only reliable way to make pre-downloaded content feel materially faster than an ordinary torrent stream inside Stremio.
- Consequences: The backend needs a safe local-file streaming contract, qB API inspection helpers, and acceptance coverage for local-playback preference.

### Decision: a direct local playback row can satisfy the Stremio playback goal even when a weaker torrent fallback is not also visible

- Date: 2026-03-28
- Context: Once local direct playback was introduced, some real desktop runs still showed only the strongest local `2160p` row for an episode even though earlier backend JSON checks had also included a `1080p` torrent fallback.
- Chosen option: treat the presence of the strongest direct local playback row as the primary success condition; keep torrent fallbacks when available, but do not require the UI to always surface an additional weaker row.
- Reasoning: The user goal for phase 21 is better ordering and materially better playback from pre-downloaded content, not preserving a lower-value fallback row at all costs when the local direct stream is already the best option.
- Consequences: Acceptance evidence should prioritize real desktop rendering plus direct ranged local playback proof over assuming every live episode page will always show multiple qB rows.

## Acceptance Criteria

- The qB RSS addon returns the strongest playback candidate first for mixed-quality episode/movie result sets, with focused coverage proving `2160p` outranks weaker variants when it is otherwise viable.
- If qB already has the requested media file downloaded locally, the addon returns a Stremio-usable direct local playback stream ahead of torrent-only fallbacks, and that local stream is enough to satisfy the playback goal even when a weaker fallback row is not surfaced in the real desktop UI.
- qB-only playback acceleration is safe, local-first, and does not regress ordinary torrent-based fallback behavior when no completed local file is available.
- Focused pytest coverage passes for the ranking and local-playback changes.
- `scripts/stremio_addon_smoke.py` passes for the known Stremio regression items.
- `scripts/stremio_desktop_smoke.py` remains green while validating the updated addon behavior against the real desktop client.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P21-01 | Re-rank qB RSS streams so best-playable quality comes first. | Codex | 2026-03-28 | complete | Mixed-quality qB RSS results rank the strongest viable stream first, and tests cover the ordering contract. | `app/services/stremio_addon.py` now sorts quality-first, `tests/test_stremio_addon.py` covers `2160p` ahead of `1080p`, `.\\.venv\\Scripts\\python.exe scripts\\stremio_addon_smoke.py --mode service --min-streams 2 --require-4k --json` passed. |
| P21-02 | Add qB live-torrent inspection helpers needed for local playback acceleration. | Codex | 2026-03-28 | complete | The backend can resolve completed qB torrents/files for a requested Stremio item without manual user intervention. | Added `get_torrent(...)` / `get_torrents(...)` in `app/services/qbittorrent.py`, shared qB local playback matching in `app/services/local_playback.py`, and focused coverage in `tests/test_qbittorrent_client.py` plus `tests/test_local_playback.py`. |
| P21-03 | Expose a local playback path for completed qB-backed files and prefer it in addon streams. | Codex | 2026-03-28 | complete | Stremio can receive a direct local playback stream when the requested file already exists locally in qB, with torrent fallback retained when live results are available. | Added `/stremio/local-playback/{token}` in `app/routes/stremio_addon.py`; real desktop smoke artifacts `logs/qa/stremio-desktop-smoke-20260328T154722Z/` and `logs/qa/stremio-desktop-smoke-20260328T154802Z/` show visible `qB RSS Rules Local 2160p` rows; ranged local playback probe returned `206`, `1,048,576` bytes, and about `9.7 ms`. |
| P21-04 | Add focused regressions and rerun addon/desktop smoke acceptance. | Codex | 2026-03-28 | complete | Pytest plus the addon/desktop smoke pair are green for the phase-21 slice. | `cmd.exe /c scripts\\check.bat` (`269 passed`, `1 skipped`), `cmd.exe /c scripts\\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T154314Z/`), `cmd.exe /c scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), `.\\.venv\\Scripts\\python.exe scripts\\stremio_addon_smoke.py --mode http --min-streams 2 --require-4k --base-url http://127.0.0.1:8013 --json`, and the two real desktop smoke runs above. |

## Risks And Follow-Up

### Risk: Stremio may treat local direct-file streams differently than torrent streams

- Trigger: the desktop client may require a stricter HTTP response shape or headers for reliable playback/seek behavior.
- Impact: the local-playback path could exist but still fail to deliver the expected buffering improvement.
- Mitigation: validate with the real desktop smoke harness and add route-level range/seek coverage if the first implementation reveals a transport mismatch.
- Owner: Codex
- Review date: 2026-03-28
- Status: mitigated by real desktop smoke plus ranged local playback probe

### Risk: qB torrent/file metadata may not uniquely map every result to a completed local file

- Trigger: multiple similar torrents or renamed content could make local file resolution ambiguous.
- Impact: the backend could fail to use local playback for some eligible items or pick the wrong file if matching is too loose.
- Mitigation: prefer deterministic identifiers first (`infoHash`, resolved file index, parsed torrent file names), and fall back to torrent-only streams when a safe local mapping is not available.
- Owner: Codex
- Review date: 2026-03-28
- Status: mitigated for the known regression titles by deterministic info-hash/file-index matching plus qB inventory fallback

## Next Concrete Steps

1. Decide whether the next Stremio follow-up should target richer catalog/provider coverage, watched-progress arbitration, or addon metadata/configuration expansion.
2. Correct or replace the currently invalid OMDb key on this machine so Stremio catalog search can match the now-green item-page playback path.
3. Keep `scripts/stremio_addon_smoke.py` and `scripts/stremio_desktop_smoke.py` as the standing regression pair before changing native addon behavior again.

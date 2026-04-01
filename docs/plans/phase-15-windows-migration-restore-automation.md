# Phase 15: Windows Migration Restore Automation

## Status

- Plan baseline created on 2026-03-26 for the operator migration from the current source PC to `192.168.1.52`.
- Phase 15 delivered the active implementation track for target-machine restore automation and migration resumability.
- Source-side backup capture remains staged in `C:\Users\user\OneDrive\Migration-192.168.1.52\backup-20260326T012542`, and live target-machine validation completed on 2026-03-27 from the synced bundle path `C:\Users\nucc\OneDrive\Migration-192.168.1.52\`.

## Goal

Deliver a Windows-target restore script that installs the required local apps via `winget`, clones the rules project from Git at the matching release ref, restores Jellyfin/qBittorrent/Jackett state from the OneDrive migration bundle, and rehydrates the runtime rules-app data with minimal manual steps.

## Requested Scope (2026-03-26)

1. Prepare a single script file to run on the new PC.
2. Include `winget`-driven installation of the required apps.
3. Restore the migrated configs/state from the existing OneDrive backup bundle.
4. Keep manual steps minimal.

## In Scope

- A target-side standalone PowerShell restore script plus a simple `.cmd` wrapper for easy launch from the migration bundle itself.
- Automated install for Docker Desktop, Jellyfin Server, qBittorrent, and Python 3.12.
- Optional install/build support for the WinUI desktop prerequisites.
- Restore automation for:
  - Jellyfin server state under `C:\ProgramData\Jellyfin\Server`
  - Jackett Docker volumes and recreated Docker containers
  - qBittorrent roaming config and `BT_backup` session state
  - repo-local rules app `data\` plus Python virtual environment hydration
- Default handling for the already-decided migration constraint that `C:\Torrent` payload files are not copied through OneDrive.

## Out Of Scope

- Copying the full `C:\Torrent` media/download payload to the new PC.
- Non-Windows target automation.
- Live target-machine validation beyond local syntax/command verification on the source machine.

## Key Decisions

### Decision: keep the operator entrypoint in the migration bundle, not in the repo

- Date: 2026-03-26
- Context: The operator expects to clone the app repo from Git and does not want migration-only tooling to require syncing the whole working tree through OneDrive.
- Chosen option: ship `C:\Users\user\OneDrive\Migration-192.168.1.52\restore_new_pc_from_bundle.ps1` and a `.cmd` wrapper directly in the migration bundle root.
- Reasoning: the migration bundle should be self-contained, while the app code itself can come from Git and the runtime DB/data can be restored afterward.
- Consequences: repo docs should point at the standalone bundle entrypoint, and the restore flow must clone the matching release ref before restoring `data\`.

### Decision: clone the rules project from Git at the matching release ref before restoring runtime data

- Date: 2026-03-26
- Context: The operator expects a Git clone on the new PC, but the live rules DB is not tracked in Git because `data/` is ignored.
- Chosen option: the standalone restore script clones `https://github.com/Spon4ik/qBittorrent-rss-rules.git` and checks out commit `37a33345bd462e34926d7e67b67e4d45b697c59c` (`v0.7.2`) before restoring the backed-up `data\` tree.
- Reasoning: this keeps the code path clean and reproducible while preserving the operator's real runtime state from backup.
- Consequences: the migration bundle no longer needs a full repo sync, but the script must install Git and manage repo checkout itself.

### Decision: default the restored runtime clone to `%USERPROFILE%\Documents`

- Date: 2026-03-27
- Context: on the live target machine, `MyDocuments` resolved into `C:\Users\nucc\OneDrive\Document`, which already held the active development workspace used during migration support.
- Chosen option: the standalone restore script now defaults the restored runtime checkout to `%USERPROFILE%\Documents\qBittorrent rss rules`, while still allowing `-RepoRoot` overrides.
- Reasoning: this keeps the operator-facing runtime clone isolated from the OneDrive-backed development workspace and avoids checking out the release ref over an active worktree on redirected-documents setups.
- Consequences: reruns on redirected-documents systems remain safe by default, and live restore notes should mention the separate runtime clone path when relevant.

### Decision: keep OneDrive migration scope to config/state, not the full qB payload

- Date: 2026-03-26
- Context: `C:\Torrent` on the source machine is about `270.762 GB`, and the operator explicitly chose not to migrate it through OneDrive.
- Chosen option: restore qBittorrent session/config state but exclude the content payload from the automated restore bundle.
- Reasoning: this keeps the migration storage sane while preserving qB's torrent/session knowledge so the new machine can redownload as needed.
- Consequences: the restore script must create the local target folder structure and warn that payload re-download is expected.

### Decision: default `jackett-stremio` to `host.docker.internal` for local Jackett reachability

- Date: 2026-03-26
- Context: the source container used a hardcoded host IP (`192.168.1.51`) for Jackett access, but the target host should not depend on a fixed LAN IP inside the container.
- Chosen option: recreate `jackett-stremio` with `JACKETT_HOSTS=http://host.docker.internal:9117` by default.
- Reasoning: this is more robust across host IP changes on Docker Desktop while still reaching the local Jackett port published on the Windows host.
- Consequences: the script should allow override but should not preserve the old host IP by default.

## Acceptance Criteria

- The new script installs the required Windows packages with `winget`, unless the operator opts to skip install.
- The script restores the OneDrive backup bundle into the expected Windows paths for Jellyfin, Docker/Jackett, qBittorrent, and the rules app.
- The script is syntactically valid PowerShell and uses the repo's existing scripting patterns (`robocopy`, explicit exit checking, simple wrapper commands).
- The repo docs and status files clearly record the backup location, the restore entrypoint, and the completed live validation outcome on the target machine.

## Dated Execution Checklist (2026-03-26 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P15-01 | Capture source backup bundle into OneDrive. | Codex | 2026-03-26 | completed | Jellyfin, Docker state, qB config/session state, and rules app data are staged in OneDrive. | Backup root `C:\Users\user\OneDrive\Migration-192.168.1.52\backup-20260326T012542` with `docker/`, `jellyfin/`, `qbittorrent/`, `qb-rules-app/`, and `meta/`. |
| P15-02 | Implement target restore automation script. | Codex | 2026-03-26 | completed | Standalone target-side script exists with install + Git clone + restore flow and minimal manual steps. | `C:\Users\user\OneDrive\Migration-192.168.1.52\restore_new_pc_from_bundle.ps1` and `C:\Users\user\OneDrive\Migration-192.168.1.52\restore_new_pc_from_bundle.cmd`. |
| P15-03 | Synchronize docs/status for migration automation. | Codex | 2026-03-26 | completed | Roadmap, plans index, current status, and user-facing docs describe the automation and pending target validation. | Updated `ROADMAP.md`, `docs/plans/README.md`, `docs/plans/current-status.md`, `README.md`, and this phase plan. |
| P15-04 | Validate restore automation on the actual target machine. | Operator + Codex | 2026-03-27 | completed | The script runs successfully on `192.168.1.52` and restores the expected services/state. | Successful rerun log `C:\Users\nucc\OneDrive\Migration-192.168.1.52\restore-run-20260327T012213-resume3.log`; live checks: Jellyfin `/health` `200`, qB WebUI API `200` / `v5.1.4`, Jackett `200`, FlareSolverr `200`, `jackett-stremio` `/manifest.json` `200`, rules app `/health` `200`. |

## Risks And Follow-Up

### Risk: target Docker Desktop initialization may still require one interactive first launch

- Trigger: fresh Docker Desktop installs can require backend initialization before `docker version` succeeds.
- Impact: the script may need to be rerun after Docker Desktop finishes its first-run setup.
- Mitigation: the script waits for Docker readiness and fails with a concrete rerun instruction instead of silently skipping Docker restore.
- Owner: Codex
- Review date: 2026-03-27
- Status: mitigated during live validation after the operator enabled BIOS virtualization and completed Docker Desktop first-run initialization.

### Risk: Jellyfin restore succeeds before any media payload is present on the target

- Trigger: the operator intentionally excluded `C:\Torrent` payload migration from OneDrive.
- Impact: Jellyfin metadata and config restore cleanly, but actual library files remain unavailable until the target machine has media content or equivalent path exposure.
- Mitigation: the script creates the local folder skeleton and prints an explicit warning at the end of the restore.
- Owner: Codex
- Review date: 2026-03-26
- Status: open

### Follow-up: `jackett-stremio` validation should probe `/manifest.json`

- Trigger: the standalone validation summary currently checks `http://127.0.0.1:7000/`, but `jackett-stremio` exposes a healthy `200` manifest on `http://127.0.0.1:7000/manifest.json` and returns `404` at the root path.
- Impact: the restore summary underreports `jackett-stremio` health even when the add-on is working.
- Mitigation: switch the validation probe to `/manifest.json` or treat root `404` as expected for this service.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

## Next Concrete Steps

1. Decide whether the migration script should stay as a one-off operator tool or graduate into a more formal documented install/migration flow.
2. Optionally update the standalone validation summary so `jackett-stremio` is checked on `/manifest.json`.
3. If Jellyfin should serve real content on the new PC, expose/copy the actual media payload and let qBittorrent recheck/redownload into `C:\Torrent` as needed.

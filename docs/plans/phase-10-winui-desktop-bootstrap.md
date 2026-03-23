# Phase 10: WinUI Desktop Bootstrap

## Status

- Plan baseline created on 2026-03-17 from a user-requested WinUI desktop app bootstrap.
- Phase implementation is completed and release-validated on 2026-03-23 as `v0.6.0`.
- The retained desktop direction for this release is the WinUI WebView-shell + companion-process lifecycle baseline.
- Bootstrap implementation is completed for the initial spike and immediate dev-loop hardening (`P10-01`..`P10-06`).
- First WebView-shell integration slice is completed (`P10-07`) and initial backend lifecycle strategy plus launcher convenience follow-ups are now implemented (`P10-08`..`P10-10`).
- Desktop freshness follow-up is completed on 2026-03-22: desktop-managed backend launches now enforce uvicorn `--reload`, WebView navigations carry a launch cache-buster, and orphaned managed backend processes are cleaned up on the next launch.
- Desktop stale-backend compatibility guard is completed on 2026-03-22: the WinUI shell now validates a required desktop backend contract via `/health` and falls back to a fresh managed loopback port when the default local port is occupied by an incompatible stale backend.
- Post-release rules-page performance hardening is completed on 2026-03-22 and included in the `v0.6.0` release: persisted snapshot release-cache columns now keep local main-page filtering/sorting off the giant inline-search JSON path, and poster backfill no longer blocks routine filtered requests.

## Goal

Establish a verified WinUI 3 desktop scaffold in the repo so desktop packaging work can move from roadmap intent to implementation-ready follow-up.

## Requested scope (2026-03-17)

1. Create a new WinUI desktop app in the repository workspace.
2. Run prerequisite/setup validation using the `winui-app` skill workflow.
3. Build and launch-verify the generated desktop app.

## In scope

- Environment/bootstrap execution via `winget configure` from the skill bundle.
- Template availability verification for `dotnet new winui`.
- New scaffold creation under repository root (`QbRssRulesDesktop`).
- Build verification and objective launch verification with a real top-level window.
- Documentation updates for resumability and planning alignment.
- Initial desktop integration shell:
  - host the existing local web app at `http://127.0.0.1:8000` inside WinUI via `WebView2`,
  - surface friendly startup/failure guidance when backend is unavailable,
  - provide local retry action without requiring app restart.
- Initial backend lifecycle baseline:
  - attach-first behavior for an already-running local API,
  - in-app backend start action with reconnect loop,
  - script-level companion launch flow (`scripts/run_dev.bat full`).

## Out of scope

- Deep route/service rewrite for native desktop parity.
- Replacing existing web UX with desktop UX.
- Installer/distribution pipeline design.
- Production release readiness for desktop packaging.

## Key decisions

- App name: `QbRssRulesDesktop`.
- Packaging model for this spike: **unpackaged** (`WindowsPackageType=None`) to support repeatable CLI launch verification in this environment.
- Build target for verification: `Debug + x64`.
- NuGet source handling for this repository now uses a committed `NuGet.config` with both `nuget.org` and the Visual Studio offline source, so desktop build scripts do not need per-command `--source` overrides.
- Backend lifecycle baseline for this phase:
  - desktop tries existing backend first (`QB_RSS_DESKTOP_URL` override supported),
  - desktop UI can start backend (`scripts/run_dev.bat api`) and auto-retry in-app,
  - `scripts/run_dev.bat full` starts API + desktop in one command for local dev.
- Successful desktop builds should also refresh a human-friendly `.lnk` surface in both the repo root and the user's Windows Desktop so future launches do not require navigating the WinUI build output tree.
- Windows-side network probes (`Test-NetConnection`) are the authoritative backend reachability check in this WSL-hosted workspace.

## Dated execution checklist (2026-03-17 baseline)

| ID | Step | Owner | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- |
| P10-01 | Run bundled WinUI bootstrap config. | Codex | completed | `winget configure` finishes and reports success/partial status. | `winget.exe configure -f config.yaml --accept-configuration-agreements --disable-interactivity` (`Configuration successfully applied`). |
| P10-02 | Verify `winui` template availability for dotnet CLI. | Codex | completed | `dotnet new list winui` lists at least one `winui` template. | Installed template package via `dotnet new install VijayAnand.WinUITemplates@5.0.0 --nuget-source https://api.nuget.org/v3/index.json`; `dotnet new list winui` now lists `WinUI 3 App (winui)`. |
| P10-03 | Scaffold new desktop app in workspace. | Codex | completed | New project folder and `.csproj` are created at expected path. | `dotnet new winui -o QbRssRulesDesktop`; project files created in repo root. |
| P10-04 | Build scaffold successfully from CLI path. | Codex | completed | `dotnet build` succeeds with zero errors on generated `.csproj`. | `dotnet build QbRssRulesDesktop/QbRssRulesDesktop.csproj -c Debug --no-restore -p:Platform=x64` (`Build succeeded`). |
| P10-05 | Launch-verify desktop app with objective startup signal. | Codex | completed | Running process has a non-zero main window handle and expected UI title. | PowerShell probe after `Start-Process` showed `ProcessName=QbRssRulesDesktop`, `HasExited=False`, `MainWindowHandle=2690580`, `MainWindowTitle=qB RSS Rules Desktop`; final verified instance left running. |
| P10-06 | Add stable local desktop dev-loop commands. | Codex | completed | One-command desktop build/run flow exists and succeeds without ad hoc source flags. | Added `NuGet.config`; expanded `scripts/run_dev.bat` modes (`desktop-build`, `desktop-run`, `desktop`, `full`); validation via `cmd.exe /c "scripts\run_dev.bat help"`, `desktop-build`, `desktop-run` with running window verification. |
| P10-07 | Implement first WebView desktop integration slice. | Codex | completed | Desktop app opens local web UI in `WebView2`; unavailable-backend state is actionable and recoverable in-app. | Implemented WebView shell + retry/open-browser fallback in `QbRssRulesDesktop/Views/MainPage.xaml` + `MainPage.xaml.cs`; window title updated in `QbRssRulesDesktop/App.xaml.cs`; validation: `cmd.exe /c "scripts\run_dev.bat desktop-build"` (`Build succeeded`), `cmd.exe /c "scripts\run_dev.bat desktop-run"` (launch succeeds), `curl -I http://127.0.0.1:8000` connection failure while app remains alive with top-level window (`MainWindowTitle=qB RSS Rules Desktop`). |
| P10-08 | Define and implement initial backend lifecycle strategy. | Codex | completed | Desktop/API startup path is defined, implemented, and validated with objective checks. | `MainPage.xaml.cs` now probes configured URI and offers in-app backend start + reconnect; `scripts/run_dev.bat` hardened for error propagation and `full` companion launch; validation: `cmd.exe /v:on /c "scripts\run_dev.bat full & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`), `powershell.exe -NoProfile -Command "Start-Sleep -Seconds 3; (Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue).TcpTestSucceeded"` (`True`), and desktop process probe with title `qB RSS Rules Desktop`. |
| P10-09 | Desktop-managed backend auto-start + hidden companion flow. | Codex | completed | Desktop launch automatically starts/stops the FastAPI backend with no extra console windows, and docs call out the exe path + fallback commands. | `QbRssRulesDesktop/Views/MainPage.xaml.cs` now launches managed backends via hidden `python.exe` with `--reload`, writes/removes a managed-backend marker, cleans up orphaned managed backend processes on later launches, and adds a per-navigation cache-buster so the WebView does not reuse stale HTML; `scripts/run_dev.bat full` now hides `python.exe` instead of relying on `pythonw`; `README.md` adds a "WinUI desktop quick start" section with the exact `.exe` path and fallback commands. Validation: `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`) plus a custom launch on `http://127.0.0.1:8023` confirmed backend command line `... --reload` and backend shutdown after closing the desktop window. |
| P10-10 | Add short-path launcher shortcuts for the WinUI shell. | Codex | completed | Users can launch the desktop app from a short `.lnk` path with the app icon, without browsing the deep build-output directory. | Added `scripts/refresh_winui_shortcuts.ps1`; `scripts/run_dev.bat desktop-build` now refreshes `qB RSS Rules Desktop.lnk` in the repo root and Windows Desktop, and `desktop-shortcuts` can recreate them without rebuilding. Validation: `cmd.exe /c "scripts\run_dev.bat desktop-shortcuts"` (`Updated shortcut ...`, exit `0`). |
| P10-11 | Reject stale/incompatible local backends before WinUI attachment. | Codex | completed | Desktop shell only attaches to `/health` responses advertising the current desktop backend contract, and managed startup can bypass an incompatible stale listener on the default loopback port. | Added desktop compatibility metadata to `/health` in `app/main.py` + `app/routes/pages.py`; `QbRssRulesDesktop/Views/MainPage.xaml.cs` now probes `/health`, requires contract `2026-03-22`, and picks a free fallback loopback port for managed uvicorn if the default local port is already occupied by an incompatible backend. Validation: `dotnet build QbRssRulesDesktop/QbRssRulesDesktop.csproj -p:Platform=x64` (`Build succeeded`) and `.\.venv\Scripts\python.exe -m pytest tests/test_routes.py -k "health_endpoint or debug_hover_telemetry_api_records_filters_and_clears_events"` (`2 passed`). |
| P10-12 | Close out docs and release validation for `v0.6.0`. | Codex | completed | Version touchpoints, release docs, and gates are synchronized for the phase-10 delivery. | Updated `pyproject.toml`, `app/main.py`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, and `docs/plans/README.md`; validation: `cmd.exe /c "scripts\check.bat"` (`All checks passed`; `190 passed`, `52 warnings`), `cmd.exe /c "scripts\closeout_qa.bat"` (`All browser closeout checks passed`), `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`). |

## Release validation (2026-03-23)

- `cmd.exe /c "scripts\check.bat"` (`All checks passed`; `190 passed`, `52 warnings`; artifacts: `logs/tests/pytest-last.log`, `logs/tests/pytest-last.xml`).
- `cmd.exe /c "scripts\closeout_qa.bat"` (`All browser closeout checks passed`; artifacts: `logs/qa/phase-closeout-20260323T210528Z/closeout-report.{md,json}`).
- `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`Build succeeded`, `EXITCODE:0`).

## Risks and follow-up

- Repository-local source policy is now standardized, but user- or machine-level NuGet config precedence can still vary across environments and should be verified on additional Windows profiles.
- Packaged launch flow in this environment was not verified end-to-end; prior packaged scaffold attempt hit runtime activation failure (`REGDB_E_CLASSNOTREG`) when launched directly from CLI.
- Current integration is WebView-shell only; native desktop workflows beyond WebView are still undefined.
- Repeated `desktop-run`/`full` executions can create multiple desktop/API processes; no single-instance guard is implemented yet.
- WSL-side `curl 127.0.0.1:8000` is not a reliable signal for Windows-launched backend availability in this environment.
- Real WebView hover regressions are now easiest to validate via `scripts/capture_live_hover_overlay.py --desktop-relaunch`, which launches the desktop against a hover-debug URL and records live desktop/browser evidence without manual mouse driving.
- A rebuilt released desktop run still needs to be re-captured on another Windows profile or machine to confirm the user-visible poster-overlay issue stays resolved outside the current release-gate environment.
- Rules-page filter/sort latency is now dominated by optional poster backfill on plain unfiltered `/` loads; if users still report the base page feeling slow after the new two-candidate limit and retry cooldown, the next step is to move poster completion fully off the request path.

## Next concrete steps

1. Validate `NuGet.config` + `scripts/run_dev.bat` desktop/full workflow on at least one additional Windows machine/profile.
2. Re-run `scripts/capture_live_hover_overlay.py --desktop-relaunch` against the released desktop shell on another profile or machine to verify the user-facing hover overlay remains fixed in real WebView runs.
3. Define single-instance policy for desktop + backend companion processes (reuse existing, prompt user, or enforce one-instance lock).
4. Decide whether any post-release performance follow-up should move poster completion fully off the request path for the base rules page.

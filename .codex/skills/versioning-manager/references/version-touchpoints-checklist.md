# Version Touchpoints Checklist

## Authoritative Version Sources

- `pyproject.toml` (`[project].version`)
- `app/main.py` (`FastAPI(..., version="…")`) — must match `pyproject.toml`
- `QbRssRulesDesktop/Views/MainPage.xaml.cs` (`RequiredDesktopBackendAppVersion`) — WinUI shell refuses backends whose `/health` `app_version` differs from this literal
- `tests/test_routes.py` (`test_health_endpoint` asserts `app_version`) — locks the `/health` contract the desktop consumes
- `tests/test_stremio_addon.py` (manifest `version` assert, `{semver}+stremio.1`) — Stremio manifest version tracks the app semver
- Runtime constants (`__version__`, API version fields) when present

## Desktop compatibility (not SemVer bumps, but must stay paired)

When the desktop API contract changes, update **both** sides together:

- `app/main.py`: `DESKTOP_BACKEND_CONTRACT` and `DESKTOP_BACKEND_CAPABILITIES`
- `QbRssRulesDesktop/Views/MainPage.xaml.cs`: `RequiredDesktopBackendContract`, `RequiredDesktopBackendCapabilities` (same date string and same capability list/order as the backend)

After any change to `RequiredDesktopBackendAppVersion` (or a fresh checkout), **rebuild the WinUI app** (`scripts\run_dev.bat desktop-build` or `desktop`) so the running `QbRssRulesDesktop.exe` embeds the new constants; an older built EXE will keep rejecting a newer backend.

## Derived Mentions

- `CHANGELOG.md` release heading and notes
- `ROADMAP.md` current/next release target lines
- `README.md` and docs that mention pinned release numbers
- Release docs under `docs/` (upgrade notes, release process references)

## Update Sequence

1. Decide target version and record bump rationale.
2. Prefer `python scripts/release_prep.py <patch|minor|major> --apply` (repo root, active `.venv`) to bump `pyproject.toml`, `app/main.py`, WinUI `RequiredDesktopBackendAppVersion`, and the health/manifest regression asserts in one step; then edit `CHANGELOG.md` body and planning docs as needed.
3. If you edit versions by hand, touch every authoritative source in the list above before merging.
4. Update changelog and release/upgrade notes.
5. Update roadmap and planning docs if release scope or ordering changed.
6. Re-scan and verify all version mentions are consistent; run `scripts\run_dev.bat desktop-build` so local desktop binaries match.

## Verification Commands

```bash
rg -n "version\\s*=|__version__|v[0-9]+\\.[0-9]+\\.[0-9]+" pyproject.toml README.md CHANGELOG.md ROADMAP.md docs app
rg -n "RequiredDesktopBackendAppVersion|RequiredDesktopBackendContract|DESKTOP_BACKEND_CONTRACT" app/main.py QbRssRulesDesktop/Views/MainPage.xaml.cs
git diff --stat
git diff
```

## Repo-Local Reminder

- Keep `docs/plans/current-status.md` and the active phase plan aligned when version planning changes release assumptions.
- Update `ROADMAP.md` only when phase ordering or long-term direction changes.

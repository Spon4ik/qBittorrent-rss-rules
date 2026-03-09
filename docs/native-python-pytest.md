# Native `python3 -m pytest` Setup (WSL/Linux)

This guide enables native test runs from a Linux shell (for example WSL) using:

```bash
python3 -m pytest
```

## Why this is needed

- This repo already has a Windows-style `.venv` (`.venv/Scripts/...`) for Windows `cmd.exe`/PowerShell flows.
- In Linux shells, `/usr/bin/python3` may exist without `pip`/`pytest` support.
- A Linux-native virtual environment keeps shell-native testing stable without changing the Windows setup.

## One-time host prerequisites (Ubuntu/Debian)

Run these outside any virtual environment:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev build-essential
```

If your distro asks for a versioned package (for example `python3.12-venv`), install that exact package.

Sanity check:

```bash
python3 -m pip --version
```

## Project bootstrap (repo-local, Linux-native)

From the repository root:

```bash
python3 -m venv .venv-linux
source .venv-linux/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

## Verify native toolchain

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 -m mypy app
```

If these pass, native Linux `python3` is ready for Codex and local development.

If pytest exits with a capture teardown error (`FileNotFoundError` in `_pytest/capture.py`) in this WSL path, use:

```bash
python3 -m pytest -q -s
```

For wrapper scripts, `scripts/test.sh` now defaults to `--capture=sys` for better WSL compatibility. If needed, you can still force no capture:

```bash
./scripts/test.sh -s
```

## Resume in a new shell

From repository root:

```bash
source .venv-linux/bin/activate
python3 -m pytest -q
```

No reinstall is needed unless dependencies change.

The bash test wrapper also auto-detects `.venv-linux/bin/python`, so this works without activation:

```bash
./scripts/test.sh
```

## Fast fallback (no activation)

If activation is not convenient:

```bash
.venv-linux/bin/python -m pytest -q
```

## Notes for mixed Windows + WSL usage

- Keep the existing `.venv` for Windows scripts (`scripts\\test.bat`, `scripts\\check.bat`).
- Use `.venv-linux` for WSL/Linux native commands.
- Do not share one virtual environment between Windows and Linux interpreters.

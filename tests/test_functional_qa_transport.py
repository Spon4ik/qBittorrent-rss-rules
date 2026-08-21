from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import functional_qa  # noqa: E402


def test_fetch_json_normalizes_timeout_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(functional_qa, "urlopen", timeout)

    with pytest.raises(RuntimeError, match=r"Timed out reading .* after 5s"):
        functional_qa._fetch_json("http://127.0.0.1:8000/api/diagnostics/runtime", timeout_seconds=5)

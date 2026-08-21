from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import runtime_status  # noqa: E402


def test_upstream_state_distinguishes_synced_unpushed_and_local_changes() -> None:
    assert (
        runtime_status.classify_upstream_state(
            dirty=False,
            upstream="origin/experiment/codex-token-efficiency",
            ahead=0,
            behind=0,
        )
        == "synced"
    )
    assert (
        runtime_status.classify_upstream_state(
            dirty=False,
            upstream="origin/experiment/codex-token-efficiency",
            ahead=2,
            behind=0,
        )
        == "unpushed"
    )
    assert (
        runtime_status.classify_upstream_state(
            dirty=True,
            upstream="origin/experiment/codex-token-efficiency",
            ahead=0,
            behind=0,
        )
        == "local_changes"
    )


def test_upstream_state_reports_diverged_and_missing_tracking() -> None:
    assert (
        runtime_status.classify_upstream_state(
            dirty=False,
            upstream="origin/main",
            ahead=1,
            behind=1,
        )
        == "diverged"
    )
    assert (
        runtime_status.classify_upstream_state(
            dirty=False,
            upstream=None,
            ahead=None,
            behind=None,
        )
        == "no_upstream"
    )


def test_runtime_state_detects_stale_deployment_version() -> None:
    assert (
        runtime_status.classify_runtime_state(
            checkout_version="1.4.20",
            reachable=True,
            app_version="1.4.19",
        )
        == "stale_version"
    )
    assert (
        runtime_status.classify_runtime_state(
            checkout_version="1.4.20",
            reachable=True,
            app_version="1.4.20",
        )
        == "current_version"
    )


def test_runtime_state_distinguishes_unreachable_and_missing_version() -> None:
    assert (
        runtime_status.classify_runtime_state(
            checkout_version="1.4.20",
            reachable=False,
            app_version="",
        )
        == "unreachable"
    )
    assert (
        runtime_status.classify_runtime_state(
            checkout_version="1.4.20",
            reachable=True,
            app_version="",
        )
        == "unknown_version"
    )


def test_checkout_version_is_read_from_project_metadata(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "qa-fixture"\nversion = "9.8.7"\n',
        encoding="utf-8",
    )

    assert runtime_status.read_checkout_version(tmp_path) == "9.8.7"


def test_backend_finalizer_reports_not_attempted_and_requires_current_runtime() -> None:
    finalizer = (PROJECT_DIR / "Finalize Backend.cmd").read_text(encoding="utf-8")

    assert "Docker deployment was NOT ATTEMPTED" in finalizer
    assert 'call "scripts\\runtime_state.bat"' in finalizer
    assert "--require-runtime-current" in finalizer
    assert "deployed runtime is current and healthy" in finalizer


def test_docker_wrapper_requires_runtime_freshness_before_success() -> None:
    wrapper = (PROJECT_DIR / "Update Docker.cmd").read_text(encoding="utf-8")

    assert "EnableDelayedExpansion" in wrapper
    assert "--require-runtime-current" in wrapper
    assert "deployed runtime matches the checkout version" in wrapper
    assert "Docker update failed or the deployed runtime is stale" in wrapper

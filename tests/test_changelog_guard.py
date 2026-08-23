from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from changelog_guard import GuardEvidence, RELEVANT_PATHS, evaluate_guard  # noqa: E402


def _evidence(
    *,
    relevant_dirty: bool = False,
    changelog_dirty: bool = False,
    relevant_commit: str | None = "relevant",
    changelog_commit: str | None = "changelog",
    covered: bool | None = True,
) -> GuardEvidence:
    return GuardEvidence(
        relevant_worktree_dirty=relevant_dirty,
        changelog_worktree_dirty=changelog_dirty,
        latest_relevant_commit=relevant_commit,
        latest_changelog_commit=changelog_commit,
        relevant_commit_covered_by_changelog=covered,
    )


def test_dirty_relevant_worktree_requires_changelog_update() -> None:
    decision = evaluate_guard(_evidence(relevant_dirty=True, changelog_dirty=False))

    assert decision.status == "fail"
    assert "CHANGELOG.md is unchanged" in decision.reason


def test_dirty_changelog_covers_current_worktree_changes() -> None:
    decision = evaluate_guard(_evidence(relevant_dirty=True, changelog_dirty=True))

    assert decision.status == "pass"
    assert "current worktree" in decision.reason


def test_clean_history_passes_when_relevant_commit_is_covered() -> None:
    decision = evaluate_guard(_evidence(covered=True))

    assert decision.status == "pass"
    assert "covered" in decision.reason


def test_clean_history_fails_when_relevant_commit_is_newer_than_changelog() -> None:
    decision = evaluate_guard(_evidence(covered=False))

    assert decision.status == "fail"
    assert "older than" in decision.reason


def test_missing_changelog_commit_fails_when_relevant_history_exists() -> None:
    decision = evaluate_guard(_evidence(changelog_commit=None, covered=None))

    assert decision.status == "fail"
    assert "has no commit" in decision.reason


def test_no_relevant_history_is_safe() -> None:
    decision = evaluate_guard(
        _evidence(relevant_commit=None, changelog_commit=None, covered=None)
    )

    assert decision.status == "pass"


def test_guard_scope_includes_product_runtime_and_maintained_qa_tooling() -> None:
    assert "app" in RELEVANT_PATHS
    assert "scripts" in RELEVANT_PATHS
    assert "QbRssRulesDesktop" in RELEVANT_PATHS
    assert "Finalize-Backend.cmd" in RELEVANT_PATHS
    assert "Update-Docker.cmd" in RELEVANT_PATHS

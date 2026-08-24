#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_DIR / "logs" / "qa" / "changelog-guard.json"
CHANGELOG_PATH = "CHANGELOG.md"

# These paths represent product/runtime/operational tooling changes that are
# notable enough to require an Unreleased changelog update. Pure test and plan
# edits are intentionally excluded; changes to maintained QA/runtime scripts are
# included because they change the project's operator/developer workflow.
RELEVANT_PATHS: tuple[str, ...] = (
    "app",
    "scripts",
    "QbRssRulesDesktop",
    "alembic",
    "pyproject.toml",
    "Dockerfile",
    "Finalize Backend.cmd",
    "Finalize-Backend.cmd",
    "Update Docker.cmd",
    "Update-Docker.cmd",
)


@dataclass(frozen=True, slots=True)
class GuardEvidence:
    relevant_worktree_dirty: bool
    changelog_worktree_dirty: bool
    latest_relevant_commit: str | None
    latest_changelog_commit: str | None
    relevant_commit_covered_by_changelog: bool | None


@dataclass(frozen=True, slots=True)
class GuardDecision:
    status: str
    reason: str


def evaluate_guard(evidence: GuardEvidence) -> GuardDecision:
    """Return a deterministic changelog freshness decision from git evidence."""

    if evidence.changelog_worktree_dirty:
        return GuardDecision(
            "pass",
            "CHANGELOG.md is updated in the current worktree.",
        )
    if evidence.relevant_worktree_dirty:
        return GuardDecision(
            "fail",
            "Implementation/runtime/QA-tooling changes are present but CHANGELOG.md is unchanged.",
        )
    if evidence.latest_relevant_commit is None:
        return GuardDecision("pass", "No tracked implementation/runtime/QA-tooling commit was found.")
    if evidence.latest_changelog_commit is None:
        return GuardDecision(
            "fail",
            "Tracked implementation/runtime/QA-tooling changes exist but CHANGELOG.md has no commit.",
        )
    if evidence.relevant_commit_covered_by_changelog:
        return GuardDecision(
            "pass",
            "The latest relevant commit is covered by the latest CHANGELOG.md commit.",
        )
    return GuardDecision(
        "fail",
        "CHANGELOG.md is older than the latest implementation/runtime/QA-tooling commit.",
    )


def _git(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=PROJECT_DIR,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _worktree_dirty(paths: Sequence[str]) -> bool:
    result = _git(["status", "--porcelain", "--untracked-files=all", "--", *paths])
    return bool(result.stdout.strip())


def _latest_commit(paths: Sequence[str]) -> str | None:
    result = _git(["log", "-1", "--format=%H", "--", *paths])
    value = result.stdout.strip()
    return value or None


def collect_evidence() -> GuardEvidence:
    relevant_dirty = _worktree_dirty(RELEVANT_PATHS)
    changelog_dirty = _worktree_dirty((CHANGELOG_PATH,))
    latest_relevant = _latest_commit(RELEVANT_PATHS)
    latest_changelog = _latest_commit((CHANGELOG_PATH,))

    covered: bool | None = None
    if latest_relevant is not None and latest_changelog is not None:
        ancestry = _git(
            ["merge-base", "--is-ancestor", latest_relevant, latest_changelog],
            check=False,
        )
        if ancestry.returncode == 0:
            covered = True
        elif ancestry.returncode == 1:
            covered = False
        else:
            detail = ancestry.stderr.strip() or ancestry.stdout.strip() or "unknown git error"
            raise RuntimeError(f"Could not compare changelog ancestry: {detail}")

    return GuardEvidence(
        relevant_worktree_dirty=relevant_dirty,
        changelog_worktree_dirty=changelog_dirty,
        latest_relevant_commit=latest_relevant,
        latest_changelog_commit=latest_changelog,
        relevant_commit_covered_by_changelog=covered,
    )


def _write_report(evidence: GuardEvidence, decision: GuardDecision) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "status": decision.status,
                "reason": decision.reason,
                "evidence": asdict(evidence),
                "relevant_paths": list(RELEVANT_PATHS),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        evidence = collect_evidence()
        decision = evaluate_guard(evidence)
        _write_report(evidence, decision)
    except Exception as exc:  # noqa: BLE001
        print(f"CHANGELOG GUARD ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"CHANGELOG {decision.status.upper()}: {decision.reason}")
    print(f"Report: {REPORT_PATH.relative_to(PROJECT_DIR)}")
    return 0 if decision.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

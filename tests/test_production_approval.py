from __future__ import annotations

from pathlib import Path

import pytest

import scripts.production_approval as approval
from scripts.production_approval import (
    build_approval_manifest,
    has_successful_job,
    resolve_tag_commit,
    select_successful_run,
)

SHA = "a" * 40


def _run(**overrides: object) -> dict[str, object]:
    return {
        "databaseId": 123,
        "workflowName": "CI",
        "headSha": SHA,
        "headBranch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "createdAt": "2026-09-27T10:00:00Z",
        "url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/123",
        **overrides,
    }


def test_select_successful_run_requires_exact_sha_main_push_and_success() -> None:
    wrong_sha = _run(databaseId=1, headSha="b" * 40)
    failed = _run(databaseId=2, conclusion="failure")
    pull_request = _run(databaseId=3, event="pull_request")
    result = _run(databaseId=4)

    assert select_successful_run(
        [wrong_sha, failed, pull_request, result],
        workflow_name="CI",
        commit_sha=SHA,
    ) == result


def test_select_successful_run_fails_when_no_exact_sha_success_exists() -> None:
    for bad in (
        _run(headSha="b" * 40),
        _run(status="in_progress"),
        _run(conclusion="cancelled"),
        _run(headBranch="feature"),
        _run(event="pull_request"),
    ):
        assert select_successful_run([bad], workflow_name="CI", commit_sha=SHA) is None


def test_select_successful_run_chooses_newest_qualifying_attempt() -> None:
    older = _run(databaseId=1, createdAt="2026-09-26T10:00:00Z")
    newer = _run(databaseId=2, createdAt="2026-09-27T10:00:00Z")

    assert select_successful_run(
        [older, newer], workflow_name="CI", commit_sha=SHA
    ) == newer


def test_successful_workflow_run_must_contain_successful_required_job() -> None:
    jobs = [
        {"name": "Backend checks (ubuntu-latest)", "conclusion": "success"},
        {"name": "required", "conclusion": "success"},
    ]

    assert has_successful_job(jobs, "required")
    assert not has_successful_job(jobs, "real-qbittorrent-webseed-api")
    assert not has_successful_job([{"name": "required", "conclusion": "skipped"}], "required")


def test_approval_environment_requires_owner_reviewer_protected_branches_and_no_bypass() -> None:
    environment = {
        "name": "production-approval",
        "can_admins_bypass": False,
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"reviewer": {"login": "Spon4ik"}}],
            }
        ],
    }

    assert approval.validate_approval_environment(environment)
    assert not approval.validate_approval_environment({**environment, "can_admins_bypass": True})
    assert not approval.validate_approval_environment(
        {
            **environment,
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [],
                }
            ],
        }
    )


def test_validate_command_stops_before_tag_checks_when_environment_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Spon4ik/qBittorrent-rss-rules")
    monkeypatch.setenv("RELEASE_TAG", "v1.4.25")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    requests: list[str] = []

    def api(path: str) -> dict[str, object]:
        requests.append(path)
        return {"name": "production-approval", "protection_rules": []}

    monkeypatch.setattr(approval, "_api", api)

    with pytest.raises(ValueError, match="required owner reviewer"):
        approval._validate_command()

    assert requests == [
        "repos/Spon4ik/qBittorrent-rss-rules/environments/production-approval"
    ]
    assert not (tmp_path / "output").exists()


def test_annotated_tag_is_peeled_to_commit_and_cycles_fail_closed() -> None:
    ref = {"object": {"type": "tag", "sha": "tag-object"}}
    objects = {
        "tag-object": {"object": {"type": "tag", "sha": "inner-tag"}},
        "inner-tag": {"object": {"type": "commit", "sha": SHA}},
    }

    assert resolve_tag_commit(ref, objects.__getitem__) == SHA
    assert resolve_tag_commit(ref, lambda _sha: ref["object"]) is None


def test_approval_manifest_binds_exact_release_and_evidence_runs() -> None:
    ci = _run(databaseId=123, workflowName="CI")
    api = _run(databaseId=456, workflowName="qBittorrent web-seed API integration")

    manifest = build_approval_manifest(
        repository="Spon4ik/qBittorrent-rss-rules",
        tag="v1.4.25",
        commit_sha=SHA,
        release_url="https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.4.25",
        ci_run=ci,
        api_run=api,
        approval_run_id=789,
        approval_run_url="https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/789",
        approved_at="2026-09-27T10:01:00Z",
    )

    assert manifest == {
        "schema_version": 1,
        "repository": "Spon4ik/qBittorrent-rss-rules",
        "tag": "v1.4.25",
        "commit_sha": SHA,
        "release_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.4.25",
        "ci_run_id": 123,
        "ci_run_url": ci["url"],
        "api_run_id": 456,
        "api_run_url": api["url"],
        "approval_run_id": 789,
        "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/789",
        "approved_at": "2026-09-27T10:01:00Z",
    }


def test_validate_release_rejects_draft_and_unpublished_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        approval,
        "_api",
        lambda _path: {
            "tag_name": "v1.4.25",
            "draft": True,
            "published_at": None,
        },
    )

    with pytest.raises(ValueError, match="not a published GitHub release"):
        approval.validate_release("v1.4.25", "Spon4ik/qBittorrent-rss-rules")


def test_validate_release_requires_tag_to_be_on_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "releases": {
            "tag_name": "v1.4.25",
            "draft": False,
            "published_at": "2026-09-27T10:00:00Z",
            "html_url": "https://example.invalid/release",
        },
        "ref": {"object": {"type": "commit", "sha": SHA}},
        "compare": {"status": "ahead"},
    }

    def api(path: str) -> dict[str, object]:
        if "/releases/" in path:
            return responses["releases"]
        if "/git/ref/" in path:
            return responses["ref"]
        if "/compare/" in path:
            return responses["compare"]
        pytest.fail(f"Unexpected API call before tag-main rejection: {path}")

    monkeypatch.setattr(approval, "_api", api)

    with pytest.raises(ValueError, match="not contained in protected main"):
        approval.validate_release("v1.4.25", "Spon4ik/qBittorrent-rss-rules")


def test_validate_release_requires_successful_exact_sha_required_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ci_run = _run(databaseId=123, workflowName="CI")
    api_run = _run(
        databaseId=456,
        workflowName="qBittorrent web-seed API integration",
    )
    endpoints = {
        "releases": {
            "tag_name": "v1.4.25",
            "draft": False,
            "published_at": "2026-09-27T10:00:00Z",
            "html_url": "https://example.invalid/release",
        },
        "ref": {"object": {"type": "commit", "sha": SHA}},
        "compare": {"status": "behind"},
        "ci-runs": {
            "workflow_runs": [
                {
                    "id": 123,
                    "name": "CI",
                    "head_sha": SHA,
                    "head_branch": "main",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-09-27T10:00:00Z",
                    "html_url": ci_run["url"],
                }
            ]
        },
        "api-runs": {
            "workflow_runs": [
                {
                    "id": 456,
                    "name": "qBittorrent web-seed API integration",
                    "head_sha": SHA,
                    "head_branch": "main",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-09-27T10:00:00Z",
                    "html_url": api_run["url"],
                }
            ]
        },
        "ci-jobs": {"jobs": [{"name": "required", "conclusion": "success"}]},
        "api-jobs": {
            "jobs": [
                {
                    "name": "real-qbittorrent-webseed-api",
                    "conclusion": "success",
                }
            ]
        },
    }

    def api(path: str) -> dict[str, object]:
        if "/releases/" in path:
            return endpoints["releases"]
        if "/git/ref/" in path:
            return endpoints["ref"]
        if "/compare/" in path:
            return endpoints["compare"]
        if "/workflows/ci.yml/runs?" in path:
            return endpoints["ci-runs"]
        if "/workflows/qb-webseed-integration.yml/runs?" in path:
            return endpoints["api-runs"]
        if "/runs/123/jobs?" in path:
            return endpoints["ci-jobs"]
        if "/runs/456/jobs?" in path:
            return endpoints["api-jobs"]
        pytest.fail(f"Unexpected GitHub API request: {path}")

    monkeypatch.setattr(approval, "_api", api)

    sha, release_url, selected_ci, selected_api = approval.validate_release(
        "v1.4.25", "Spon4ik/qBittorrent-rss-rules"
    )

    assert (sha, release_url) == (SHA, "https://example.invalid/release")
    assert selected_ci["databaseId"] == 123
    assert selected_api["databaseId"] == 456

    endpoints["api-jobs"] = {"jobs": []}
    with pytest.raises(ValueError, match="lacks successful real-qbittorrent-webseed-api job"):
        approval.validate_release("v1.4.25", "Spon4ik/qBittorrent-rss-rules")


def test_workflow_is_manual_read_only_gated_and_non_cancelling() -> None:
    workflow = Path(".github/workflows/production-approval.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "  pull_request:" not in workflow
    assert "  push:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "permissions: {}" in workflow
    assert "refs/heads/main" in workflow
    assert "name: production-approval" in workflow
    assert "needs: validate-release" in workflow
    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "secrets." not in workflow
    assert "persist-credentials: false" in workflow
    assert "github.step_summary" not in workflow
    assert (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4" in workflow
    )
    assert (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2"
        in workflow
    )

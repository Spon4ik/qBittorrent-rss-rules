from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import scripts.promote_production as promotion_cli
from scripts.production_plan_authorization import (
    active_authorization,
    canonical_plan_digest,
    validate_authorization_record,
    validate_plan,
    validate_release_scope,
    validate_release_version_scope,
)

NOW = datetime.now().astimezone().astimezone(UTC).replace(microsecond=0)
REPOSITORY = "Spon4ik/qBittorrent-rss-rules"
BASELINE = "a" * 40


def plan(**overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plan_id": "snapshot-recovery-122-123",
        "issues": [47, 122, 123],
        "baseline_sha": BASELINE,
        "scope": "Complete Stremio title synchronization and durable initial and stale snapshot recovery.",
        "acceptance_criteria": ["Eligible missing snapshots are fetched and persisted."],
        "allowed_paths": ["app/**", "tests/**", "scripts/**", "docs/plans/**"],
        "permitted_operations": ["publish-patch-release", "production-promotion"],
        "authorized_exceptions": [],
        "prohibited_operations": ["restore-production-database", "change-credentials"],
        "release_constraints": [
            "protected-main",
            "exact-release-provenance",
            "exact-required-checks",
        ],
        "release_version_policy": "patch-only",
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "completion_condition": "Production acceptance is verified and the authorization is completed.",
        **overrides,
    }


def record(
    plan_document: dict[str, Any], *, action: str = "authorize", **overrides: Any
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "production-plan-authorization",
        "repository": REPOSITORY,
        "action": action,
        "plan": plan_document,
        "plan_sha256": canonical_plan_digest(plan_document),
        "workflow_run_id": 200,
        "workflow_path": ".github/workflows/production-plan-authorization.yml",
        "source_sha": BASELINE,
        "approved_by": "trusted-guardian",
        "recorded_at": NOW.isoformat(),
        **overrides,
    }


def trusted_run(run_id: int = 200) -> dict[str, Any]:
    return {
        "id": run_id,
        "path": ".github/workflows/production-plan-authorization.yml@refs/heads/main",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": BASELINE,
        "status": "completed",
        "conclusion": "success",
        "actor": {"login": "Spon4ik"},
    }


def approved_run() -> dict[str, Any]:
    return {
        "user": {"login": "trusted-guardian"},
        "state": "approved",
        "environments": [{"name": "production-plan-approval"}],
    }


def successful_jobs(_run_id: int) -> list[dict[str, Any]]:
    return [{"name": "Record plan authorization", "conclusion": "success"}]


def successful_statuses(_deployment_id: int) -> list[dict[str, Any]]:
    return [
        {
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "created_at": NOW.isoformat(),
        }
    ]


def approval_environment() -> dict[str, Any]:
    return {
        "name": "production-plan-approval",
        "can_admins_bypass": False,
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"reviewer": {"login": "trusted-guardian", "type": "User"}}],
            }
        ],
    }


def deployment(
    payload: dict[str, Any], deployment_id: int, *, created_at: str | None = None
) -> dict[str, Any]:
    return {
        "id": deployment_id,
        "creator": {"login": "github-actions[bot]"},
        "environment": "production-plan-authorization",
        "ref": payload["source_sha"],
        "sha": payload["source_sha"],
        "payload": payload,
        "created_at": created_at or NOW.isoformat(),
    }


def test_plan_digest_is_canonical_and_plan_is_time_bounded() -> None:
    document = plan()
    reordered = dict(reversed(list(document.items())))
    assert canonical_plan_digest(document) == canonical_plan_digest(reordered)
    validate_plan(document, now=NOW)


def test_candidate_plan_document_is_valid_and_narrowly_scoped() -> None:
    path = Path("docs/plans/authorizations/snapshot-recovery-122-123.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(document, now=NOW)
    assert document["issues"] == [47, 122, 123]
    assert document["release_version_policy"] == "patch-only"
    assert "production-promotion" in document["permitted_operations"]
    assert "source-rebuilt-rollback" not in document["authorized_exceptions"]
    assert canonical_plan_digest(document)


def test_plan_workflow_and_runbook_keep_legacy_release_gate_and_add_plan_path() -> None:
    workflow = Path(".github/workflows/production-plan-authorization.yml").read_text(
        encoding="utf-8"
    )
    runbook = Path("docs/production-promotion-runbook.md").read_text(encoding="utf-8")
    legacy = Path(".github/workflows/production-approval.yml").read_text(encoding="utf-8")
    assert "production-plan-approval" in workflow
    assert "deployments: write" in workflow
    assert "authorize" in workflow and "revoke" in workflow and "complete" in workflow
    assert "--plan-id snapshot-recovery-122-123" in runbook
    assert "name: production-approval" in legacy


def test_plan_version_scope_allows_corrective_patches_and_rejects_minor_release() -> None:
    document = plan()
    validate_release_version_scope("v1.4.35", "1.4.34", document)
    with pytest.raises(ValueError, match="patch releases only"):
        validate_release_version_scope("v1.5.0", "1.4.34", document)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("baseline_sha", "not-a-sha", "baseline SHA"),
        ("issues", [], "issue"),
        ("allowed_paths", [], "allowed paths"),
        ("expires_at", "not-a-date", "expiry"),
    ],
)
def test_invalid_plan_contract_fails_closed(field: str, value: object, message: str) -> None:
    document = plan()
    document[field] = value
    with pytest.raises(ValueError, match=message):
        validate_plan(document, now=NOW)


def test_authorization_requires_bot_deployment_trusted_run_and_server_approval() -> None:
    document = plan()
    payload = record(document)
    deployment_record = deployment(payload, 1)
    validate_authorization_record(
        deployment_record,
        repository=REPOSITORY,
        workflow_run=trusted_run(),
        approvals=[approved_run()],
        approval_environment=approval_environment(),
        jobs=successful_jobs(200),
        deployment_statuses=successful_statuses(1),
        now=NOW,
    )

    for tampered in (
        {**deployment_record, "creator": {"login": "Spon4ik"}},
        {**deployment_record, "ref": "b" * 40},
        deployment(record(document, plan_sha256="0" * 64), 2),
    ):
        with pytest.raises(ValueError):
            validate_authorization_record(
                tampered,
                repository=REPOSITORY,
                workflow_run=trusted_run(),
                approvals=[approved_run()],
                approval_environment=approval_environment(),
                jobs=successful_jobs(200),
                deployment_statuses=successful_statuses(1),
                now=NOW,
            )

    with pytest.raises(ValueError, match="approval"):
        validate_authorization_record(
            deployment_record,
            repository=REPOSITORY,
            workflow_run=trusted_run(),
            approvals=[{**approved_run(), "user": {"login": "someone-else"}}],
            approval_environment=approval_environment(),
            jobs=successful_jobs(200),
            deployment_statuses=successful_statuses(1),
            now=NOW,
        )

    self_approved = deployment(record(document, approved_by="Spon4ik"), 3)
    with pytest.raises(ValueError, match="independent reviewer"):
        validate_authorization_record(
            self_approved,
            repository=REPOSITORY,
            workflow_run=trusted_run(),
            approvals=[
                {
                    "user": {"login": "Spon4ik"},
                    "state": "approved",
                    "environments": [{"name": "production-plan-approval"}],
                }
            ],
            approval_environment=approval_environment(),
            jobs=successful_jobs(200),
            deployment_statuses=successful_statuses(3),
            now=NOW,
        )

    with pytest.raises(ValueError, match="successful bot status"):
        validate_authorization_record(
            deployment_record,
            repository=REPOSITORY,
            workflow_run=trusted_run(),
            approvals=[approved_run()],
            approval_environment=approval_environment(),
            jobs=successful_jobs(200),
            deployment_statuses=[
                {
                    "state": "success",
                    "creator": {"login": "github-actions[bot]"},
                    "created_at": NOW.isoformat(),
                },
                {
                    "state": "failure",
                    "creator": {"login": "github-actions[bot]"},
                    "created_at": (NOW + timedelta(seconds=1)).isoformat(),
                },
            ],
            now=NOW,
        )


def test_active_plan_can_authorize_multiple_in_scope_release_iterations() -> None:
    document = plan()
    first = deployment(record(document), 1)
    second = deployment(
        record(document, action="revoke"), 2, created_at=(NOW + timedelta(minutes=1)).isoformat()
    )
    first_authorization = active_authorization(
        [first],
        plan_id=document["plan_id"],
        repository=REPOSITORY,
        run_lookup=lambda _run_id: trusted_run(),
        approvals_lookup=lambda _run_id: [approved_run()],
        environment_lookup=approval_environment,
        jobs_lookup=successful_jobs,
        statuses_lookup=successful_statuses,
        now=NOW,
    )
    assert first_authorization["plan"]["plan_id"] == document["plan_id"]
    assert first_authorization["plan_sha256"] == canonical_plan_digest(document)

    approval_run_ids: list[int] = []

    def lookup(run_id: int) -> list[dict[str, Any]]:
        approval_run_ids.append(run_id)
        return [approved_run()]

    for release_commits, prs in (
        (
            ["b" * 40],
            [
                {
                    "number": 124,
                    "state": "closed",
                    "merged_at": "2026-10-09T22:16:23Z",
                    "base": {"ref": "main"},
                    "title": "fix #122",
                    "body": "Closes #122\nCloses #123",
                    "commit_shas": ["b" * 40],
                    "files": ["app/services/rule_fetch_ops.py"],
                }
            ],
        ),
        (
            ["b" * 40, "c" * 40],
            [
                {
                    "number": 124,
                    "state": "closed",
                    "merged_at": "2026-10-09T22:16:23Z",
                    "base": {"ref": "main"},
                    "title": "fix #122",
                    "body": "Closes #122\nCloses #123",
                    "commit_shas": ["b" * 40],
                    "files": ["app/services/rule_fetch_ops.py"],
                },
                {
                    "number": 125,
                    "state": "closed",
                    "merged_at": "2026-10-11T12:00:00Z",
                    "base": {"ref": "main"},
                    "title": "corrective release #123",
                    "body": "Closes #123\nPlan: snapshot-recovery-122-123",
                    "commit_shas": ["c" * 40],
                    "files": ["scripts/update_docker.ps1"],
                },
            ],
        ),
    ):
        reused = active_authorization(
            [first],
            plan_id=document["plan_id"],
            repository=REPOSITORY,
            run_lookup=lambda _run_id: trusted_run(),
            approvals_lookup=lookup,
            environment_lookup=approval_environment,
            jobs_lookup=successful_jobs,
            statuses_lookup=successful_statuses,
            now=NOW,
        )
        validate_release_scope(
            reused["plan"],
            release_commits,
            prs,
            authorization_time=NOW,
        )
    assert approval_run_ids == [200, 200]

    with pytest.raises(ValueError, match="revoked"):
        active_authorization(
            [second, first],
            plan_id=document["plan_id"],
            repository=REPOSITORY,
            run_lookup=lambda _run_id: trusted_run(),
            approvals_lookup=lambda _run_id: [approved_run()],
            environment_lookup=approval_environment,
            jobs_lookup=successful_jobs,
            statuses_lookup=successful_statuses,
            now=NOW + timedelta(minutes=2),
        )


def test_expired_authorization_and_duplicate_authorization_records_rejected() -> None:
    expired = plan(expires_at=(NOW - timedelta(seconds=1)).isoformat())
    expired_record = deployment(record(expired), 1)
    with pytest.raises(ValueError, match="expired"):
        active_authorization(
            [expired_record],
            plan_id=expired["plan_id"],
            repository=REPOSITORY,
            run_lookup=lambda _run_id: trusted_run(),
            approvals_lookup=lambda _run_id: [approved_run()],
            environment_lookup=approval_environment,
            jobs_lookup=successful_jobs,
            statuses_lookup=successful_statuses,
            now=NOW,
        )

    document = plan()
    duplicate = deployment(record(document), 2, created_at=(NOW + timedelta(seconds=1)).isoformat())
    with pytest.raises(ValueError, match="duplicate"):
        active_authorization(
            [deployment(record(document), 1), duplicate],
            plan_id=document["plan_id"],
            repository=REPOSITORY,
            run_lookup=lambda _run_id: trusted_run(),
            approvals_lookup=lambda _run_id: [approved_run()],
            environment_lookup=approval_environment,
            jobs_lookup=successful_jobs,
            statuses_lookup=successful_statuses,
            now=NOW,
        )


def test_release_scope_requires_linked_merged_pr_and_allowlisted_files() -> None:
    document = plan()
    prs = [
        {
            "number": 124,
            "state": "closed",
            "merged_at": "2026-10-09T22:16:23Z",
            "base": {"ref": "main"},
            "title": "fix: recover missing snapshots",
            "body": "Closes #122\nCloses #123",
            "commit_shas": ["b" * 40],
            "files": ["app/services/rule_fetch_ops.py", "tests/test_rule_fetch_ops.py"],
        }
    ]
    validate_release_scope(document, ["b" * 40], prs)

    out_of_scope = copy.deepcopy(prs)
    out_of_scope[0]["files"].append("Dockerfile")
    with pytest.raises(ValueError, match="outside"):
        validate_release_scope(document, ["b" * 40], out_of_scope)

    unlinked = copy.deepcopy(prs)
    unlinked[0]["body"] = "Routine maintenance"
    with pytest.raises(ValueError, match="issue"):
        validate_release_scope(document, ["b" * 40], unlinked)

    with pytest.raises(ValueError, match="pull request"):
        validate_release_scope(document, ["b" * 40], [])

    prefix_collision = plan(issues=[12])
    with pytest.raises(ValueError, match="related issue"):
        validate_release_scope(prefix_collision, ["b" * 40], prs)


def test_scope_handles_multiple_pull_requests_across_release_iterations() -> None:
    document = plan()
    prs = [
        {
            "number": number,
            "state": "closed",
            "merged_at": f"2026-10-{number - 100:02d}T12:00:00Z",
            "base": {"ref": "main"},
            "title": f"fix #{issue}",
            "body": f"Closes #{issue}",
            "commit_shas": ["b" * 40 if number == 124 else "c" * 40],
            "files": [path],
        }
        for number, issue, path in (
            (124, 122, "app/services/rule_fetch_ops.py"),
            (125, 123, "tests/test_rule_fetch_ops.py"),
        )
    ]
    validate_release_scope(document, ["b" * 40, "c" * 40], prs)


def test_post_authorization_pull_requests_must_name_the_exact_plan() -> None:
    document = plan()
    pull = {
        "number": 125,
        "state": "closed",
        "merged_at": (NOW + timedelta(days=1)).isoformat(),
        "base": {"ref": "main"},
        "title": "fix follow-up",
        "body": "Closes #122",
        "commit_shas": ["b" * 40],
        "files": ["app/services/rule_fetch_ops.py"],
    }
    with pytest.raises(ValueError, match="exact plan ID"):
        validate_release_scope(document, ["b" * 40], [pull], authorization_time=NOW)
    pull["body"] = "Closes #122\nPlan: snapshot-recovery-122-123"
    validate_release_scope(document, ["b" * 40], [pull], authorization_time=NOW)


def test_promoter_resolves_all_plan_scoped_release_changes_from_github(
    monkeypatch, tmp_path
) -> None:
    manager = promotion_cli.PromotionManager(
        promotion_cli.PromotionPaths(
            home=tmp_path,
            checkout=tmp_path,
            compose_file=tmp_path / "docker-compose.yml",
            env_file=tmp_path / ".env",
            private_root=tmp_path / "private",
            stable_checkout=tmp_path / "stable",
            docker_exe=tmp_path / "docker.exe",
        )
    )
    document = plan()
    paths = ["app/services/rule_fetch_ops.py", "tests/test_rule_fetch_ops.py"]

    def api(path: str) -> object:
        if "/compare/" in path and path.endswith(f"...{'b' * 40}"):
            return {"status": "ahead"}
        if path == f"repos/{REPOSITORY}/commits?sha={'b' * 40}&per_page=100&page=1":
            return [{"sha": "b" * 40}, {"sha": BASELINE}]
        if path == f"repos/{REPOSITORY}/commits/{'b' * 40}/pulls?per_page=100&page=1":
            return [{"number": 124, "title": "fix missing snapshots"}]
        if path == f"repos/{REPOSITORY}/pulls/124":
            return {
                "number": 124,
                "state": "closed",
                "merged_at": "2026-10-09T22:16:23Z",
                "base": {"ref": "main"},
                "title": "fix missing snapshots",
                "body": "Closes #122\nCloses #123",
                "changed_files": len(paths),
            }
        if path == f"repos/{REPOSITORY}/pulls/124/files?per_page=100&page=1":
            return [{"filename": filename} for filename in paths]
        raise AssertionError(f"Unexpected GitHub API request: {path}")

    monkeypatch.setattr(manager, "_api", api)
    manager._validate_plan_release_scope(
        {"plan": document, "source_sha": "d" * 40, "recorded_at": NOW.isoformat()},
        "b" * 40,
    )

    paths.append("Dockerfile")
    with pytest.raises(ValueError, match="outside the approved plan allowlist"):
        manager._validate_plan_release_scope(
            {"plan": document, "source_sha": "d" * 40, "recorded_at": NOW.isoformat()},
            "b" * 40,
        )


def test_plan_promoter_reuses_same_verified_ledger_record_without_legacy_approval(
    monkeypatch, tmp_path
) -> None:
    manager = promotion_cli.PromotionManager(
        promotion_cli.PromotionPaths(
            home=tmp_path,
            checkout=tmp_path,
            compose_file=tmp_path / "docker-compose.yml",
            env_file=tmp_path / ".env",
            private_root=tmp_path / "private",
            stable_checkout=tmp_path / "stable",
            docker_exe=tmp_path / "docker.exe",
        )
    )
    plan_document = plan()
    deployment_record = deployment(record(plan_document), 51)
    api_calls: list[str] = []

    def api(path: str) -> object:
        api_calls.append(path)
        if path.startswith(f"repos/{REPOSITORY}/deployments?environment="):
            return [deployment_record]
        if path == f"repos/{REPOSITORY}/actions/runs/200":
            return trusted_run()
        if path == f"repos/{REPOSITORY}/actions/runs/200/approvals":
            return [approved_run()]
        if path == f"repos/{REPOSITORY}/environments/production-plan-approval":
            return approval_environment()
        if path == f"repos/{REPOSITORY}/actions/runs/200/jobs?per_page=100":
            return {"jobs": successful_jobs(200)}
        if path == f"repos/{REPOSITORY}/deployments/51/statuses?per_page=100&page=1":
            return successful_statuses(51)
        raise AssertionError(f"Unexpected GitHub API request: {path}")

    monkeypatch.setattr(manager, "_api", api)
    monkeypatch.setattr(
        manager,
        "_validate_approval",
        lambda *_args: (_ for _ in ()).throw(AssertionError("legacy per-release gate was called")),
    )
    first = manager._validate_plan_authorization(plan_document["plan_id"])
    second = manager._validate_plan_authorization(plan_document["plan_id"])
    assert first["deployment_id"] == second["deployment_id"] == 51
    assert first["workflow_run_id"] == second["workflow_run_id"] == 200
    assert api_calls.count(f"repos/{REPOSITORY}/actions/runs/200/approvals") == 2

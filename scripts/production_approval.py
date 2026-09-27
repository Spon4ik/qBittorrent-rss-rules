"""Validate release provenance and emit a data-only production approval record."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlencode

TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
WORKFLOWS = (
    ("ci.yml", "CI", "required"),
    (
        "qb-webseed-integration.yml",
        "qBittorrent web-seed API integration",
        "real-qbittorrent-webseed-api",
    ),
)
APPROVAL_ENVIRONMENT = "production-approval"
APPROVER_LOGIN = "Spon4ik"


def select_successful_run(
    runs: list[dict[str, Any]], *, workflow_name: str, commit_sha: str
) -> dict[str, Any] | None:
    """Return the newest successful main push run for exactly this commit."""
    candidates = [
        run
        for run in runs
        if run.get("workflowName") == workflow_name
        and run.get("headSha") == commit_sha
        and run.get("headBranch") == "main"
        and run.get("event") == "push"
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda run: str(run.get("createdAt", "")))
    if newest.get("status") != "completed" or newest.get("conclusion") != "success":
        return None
    return newest


def has_successful_job(jobs: list[dict[str, Any]], expected_name: str) -> bool:
    return any(
        job.get("name") == expected_name and job.get("conclusion") == "success"
        for job in jobs
    )


def validate_approval_environment(environment: dict[str, Any]) -> bool:
    """Fail closed unless the owner approval and protected-branch gate exist."""
    if environment.get("name") != APPROVAL_ENVIRONMENT:
        return False
    if environment.get("can_admins_bypass") is not False:
        return False
    if environment.get("deployment_branch_policy") != {
        "protected_branches": True,
        "custom_branch_policies": False,
    }:
        return False
    rules = environment.get("protection_rules", [])
    for rule in rules:
        if rule.get("type") != "required_reviewers" or rule.get("prevent_self_review") is not False:
            continue
        reviewers = rule.get("reviewers", [])
        if (
            len(reviewers) == 1
            and reviewers[0].get("reviewer", {}).get("login", "").casefold()
            == APPROVER_LOGIN.casefold()
        ):
            return True
    return False


def resolve_tag_commit(
    ref: dict[str, Any], get_tag_object: Callable[[str], dict[str, Any]]
) -> str | None:
    """Peel nested annotated tags to a commit; reject malformed/cyclic objects."""
    obj = ref.get("object")
    visited: set[str] = set()
    for _ in range(8):
        if not isinstance(obj, dict):
            return None
        object_type = obj.get("type")
        object_sha = obj.get("sha")
        if not isinstance(object_sha, str):
            return None
        if object_type == "commit":
            return object_sha if SHA_PATTERN.fullmatch(object_sha) else None
        if object_type != "tag" or object_sha in visited:
            return None
        visited.add(object_sha)
        obj = get_tag_object(object_sha).get("object")
    return None


def build_approval_manifest(
    *,
    repository: str,
    tag: str,
    commit_sha: str,
    release_url: str,
    ci_run: dict[str, Any],
    api_run: dict[str, Any],
    approval_run_id: int,
    approval_run_url: str,
    approved_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repository": repository,
        "tag": tag,
        "commit_sha": commit_sha,
        "release_url": release_url,
        "ci_run_id": ci_run["databaseId"],
        "ci_run_url": ci_run["url"],
        "api_run_id": api_run["databaseId"],
        "api_run_url": api_run["url"],
        "approval_run_id": approval_run_id,
        "approval_run_url": approval_run_url,
        "approved_by": APPROVER_LOGIN,
        "approved_at": approved_at,
    }


def _gh_json(*args: str) -> Any:
    return json.loads(subprocess.check_output(["gh", *args], text=True, encoding="utf-8"))


def _api(path: str) -> dict[str, Any]:
    response = _gh_json("api", path)
    if not isinstance(response, dict):
        raise ValueError(f"GitHub API returned an unexpected response for {path}")
    return cast(dict[str, Any], response)


def _write_outputs(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise RuntimeError("GITHUB_OUTPUT is required")
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"Unsafe multiline workflow output: {name}")
            output.write(f"{name}={value}\n")


def validate_release(tag: str, repo: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("Release tag must use the vMAJOR.MINOR.PATCH format")

    release = _api(f"repos/{repo}/releases/tags/{quote(tag, safe='')}")
    if release.get("tag_name") != tag or release.get("draft") or not release.get("published_at"):
        raise ValueError(f"{tag} is not a published GitHub release")

    ref = _api(f"repos/{repo}/git/ref/tags/{quote(tag, safe='')}")

    def get_tag_object(object_sha: str) -> dict[str, Any]:
        return _api(f"repos/{repo}/git/tags/{object_sha}")

    commit_sha = resolve_tag_commit(ref, get_tag_object)
    if commit_sha is None:
        raise ValueError("Release tag does not resolve to a commit")

    comparison = _api(f"repos/{repo}/compare/main...{commit_sha}")
    if comparison.get("status") not in {"behind", "identical"}:
        raise ValueError("Release commit is not contained in protected main")

    selected: list[dict[str, Any]] = []
    for workflow_file, workflow_name, required_job in WORKFLOWS:
        query = urlencode(
            {
                "head_sha": commit_sha,
                "branch": "main",
                "event": "push",
                "per_page": "100",
            }
        )
        response = _api(f"repos/{repo}/actions/workflows/{workflow_file}/runs?{query}")
        runs = [
            {
                "databaseId": run.get("id"),
                "workflowName": run.get("name"),
                "headSha": run.get("head_sha"),
                "headBranch": run.get("head_branch"),
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "createdAt": run.get("created_at"),
                "url": run.get("html_url"),
            }
            for run in response.get("workflow_runs", [])
        ]
        chosen = select_successful_run(runs, workflow_name=workflow_name, commit_sha=commit_sha)
        if chosen is None:
            raise ValueError(f"No successful exact-SHA {workflow_name} run exists")
        if (
            not isinstance(chosen.get("databaseId"), int)
            or not isinstance(chosen.get("url"), str)
            or not chosen["url"].startswith("https://github.com/")
        ):
            raise ValueError(f"Exact-SHA {workflow_name} run metadata is incomplete")
        jobs_response = _api(
            f"repos/{repo}/actions/runs/{chosen['databaseId']}/jobs?per_page=100"
        )
        if not has_successful_job(jobs_response.get("jobs", []), required_job):
            raise ValueError(f"Run {chosen['databaseId']} lacks successful {required_job} job")
        selected.append(chosen)

    return commit_sha, release["html_url"], selected[0], selected[1]


def _validate_command() -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Production approval workflow must be dispatched from main")
    tag = os.environ["RELEASE_TAG"]
    repo = os.environ["GITHUB_REPOSITORY"]
    environment = _api(f"repos/{repo}/environments/{APPROVAL_ENVIRONMENT}")
    if not validate_approval_environment(environment):
        raise ValueError(
            "The production-approval Environment is missing its required owner reviewer, "
            "protected-branch policy, or disabled administrator bypass"
        )
    sha, release_url, ci_run, api_run = validate_release(tag, repo)
    _write_outputs(
        {
            "tag": tag,
            "commit_sha": sha,
            "release_url": release_url,
            "ci_run_id": str(ci_run["databaseId"]),
            "ci_run_url": str(ci_run["url"]),
            "api_run_id": str(api_run["databaseId"]),
            "api_run_url": str(api_run["url"]),
        }
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write(
            "## Source passed exact-SHA release checks\n\n"
            f"- Tag: `{tag}`\n- Commit: `{sha}`\n- Release: {release_url}\n"
            f"- CI: {ci_run['url']}\n- qBittorrent API: {api_run['url']}\n\n"
            "The next job waits for the `production-approval` Environment. "
            "No production system is contacted or changed.\n"
        )


def _emit_manifest_command() -> None:
    ci_run = {"databaseId": int(os.environ["CI_RUN_ID"]), "url": os.environ["CI_RUN_URL"]}
    api_run = {"databaseId": int(os.environ["API_RUN_ID"]), "url": os.environ["API_RUN_URL"]}
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run_url = f"{server}/{repository}/actions/runs/{run_id}"
    manifest = build_approval_manifest(
        repository=repository,
        tag=os.environ["RELEASE_TAG"],
        commit_sha=os.environ["COMMIT_SHA"],
        release_url=os.environ["RELEASE_URL"],
        ci_run=ci_run,
        api_run=api_run,
        approval_run_id=run_id,
        approval_run_url=run_url,
        approved_at=datetime.now(UTC).isoformat(),
    )
    Path("approval-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write(
            "## Approval recorded\n\n"
            f"- Tag: `{manifest['tag']}`\n- Commit: `{manifest['commit_sha']}`\n"
            f"- Approval run: {run_url}\n\n"
            "This records Environment approval only; production has not been deployed.\n"
        )


def main() -> int:
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"validate", "emit-manifest"}:
            raise ValueError("Usage: production_approval.py validate|emit-manifest")
        if sys.argv[1] == "validate":
            _validate_command()
        else:
            _emit_manifest_command()
    except (KeyError, OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"Production approval validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

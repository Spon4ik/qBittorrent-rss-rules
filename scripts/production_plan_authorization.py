"""Pure validation rules for the durable plan-scoped production authorization ledger."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.production_approval import APPROVER_LOGIN

AUTHORIZATION_ENVIRONMENT = "production-plan-authorization"
PLAN_APPROVAL_ENVIRONMENT = "production-plan-approval"
AUTHORIZATION_WORKFLOW_PATH = ".github/workflows/production-plan-authorization.yml"
PLAN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MAX_PLAN_DAYS = 90
FUTURE_TOLERANCE = timedelta(minutes=5)
PLAN_FIELDS = {
    "schema_version",
    "plan_id",
    "issues",
    "baseline_sha",
    "scope",
    "acceptance_criteria",
    "allowed_paths",
    "permitted_operations",
    "authorized_exceptions",
    "prohibited_operations",
    "release_constraints",
    "release_version_policy",
    "expires_at",
    "completion_condition",
}


def canonical_plan_bytes(plan: dict[str, Any]) -> bytes:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_plan_digest(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Plan {label} must be an ISO-8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Plan {label} must be an ISO-8601 timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"Plan {label} must include a timezone")
    return result.astimezone(UTC)


def validate_plan(plan: dict[str, Any], *, now: datetime | None = None) -> None:
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("Unsupported plan authorization schema")
    if set(plan) != PLAN_FIELDS:
        raise ValueError("Plan authorization fields do not match the versioned contract")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not PLAN_ID_PATTERN.fullmatch(plan_id):
        raise ValueError("Plan ID is invalid")
    issues = plan.get("issues")
    if (
        not isinstance(issues, list)
        or not issues
        or any(
            not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0 for issue in issues
        )
        or len(set(issues)) != len(issues)
    ):
        raise ValueError("Plan issue list must contain unique positive issue numbers")
    if not SHA_PATTERN.fullmatch(str(plan.get("baseline_sha", ""))):
        raise ValueError("Plan baseline SHA is invalid")
    for key in ("scope", "completion_condition"):
        value = plan.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Plan {key.replace('_', ' ')} must be a non-empty string")
    for key in (
        "acceptance_criteria",
        "allowed_paths",
        "permitted_operations",
        "prohibited_operations",
        "release_constraints",
    ):
        values = plan.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError(f"Plan {key.replace('_', ' ')} must be a non-empty string list")
    exceptional = plan.get("authorized_exceptions")
    if not isinstance(exceptional, list) or any(
        not isinstance(value, str) or not value.strip() for value in exceptional
    ):
        raise ValueError("Plan authorized exceptions must be a string list")
    for key in (
        "acceptance_criteria",
        "allowed_paths",
        "permitted_operations",
        "authorized_exceptions",
        "prohibited_operations",
        "release_constraints",
    ):
        if len(set(plan[key])) != len(plan[key]):
            raise ValueError(f"Plan {key.replace('_', ' ')} contains duplicates")
    if plan.get("release_version_policy") not in {"patch-only", "stable-release"}:
        raise ValueError("Plan release version policy is invalid")
    if not {"protected-main", "exact-release-provenance", "exact-required-checks"}.issubset(
        set(plan["release_constraints"])
    ):
        raise ValueError("Plan release constraints must preserve protected source and exact checks")
    paths = plan["allowed_paths"]
    if len(set(paths)) != len(paths) or any(
        path.startswith("/") or ".." in path.split("/") for path in paths
    ):
        raise ValueError("Plan allowlist contains an invalid or duplicate path")
    expiry = _parse_timestamp(plan.get("expires_at"), "expiry")
    current = _current_utc(now)
    if expiry <= current:
        raise ValueError("Plan authorization has expired")
    if expiry > current + timedelta(days=MAX_PLAN_DAYS):
        raise ValueError("Plan expiry exceeds the 90-day authorization limit")


def validate_plan_approval_environment(environment: dict[str, Any]) -> str:
    """Require one protected human reviewer outside the implementation identity."""
    if environment.get("name") != PLAN_APPROVAL_ENVIRONMENT:
        raise ValueError("Plan approval Environment is missing or has the wrong name")
    if environment.get("can_admins_bypass") is not False:
        raise ValueError("Plan approval Environment must disable administrator bypass")
    if environment.get("deployment_branch_policy") != {
        "protected_branches": True,
        "custom_branch_policies": False,
    }:
        raise ValueError(
            "Plan approval Environment must restrict deployments to protected branches"
        )
    required = [
        rule
        for rule in environment.get("protection_rules", [])
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    if len(required) != 1 or required[0].get("prevent_self_review") is not True:
        raise ValueError(
            "Plan approval Environment must require a reviewer and prevent self-review"
        )
    reviewers = required[0].get("reviewers", [])
    if (
        not isinstance(reviewers, list)
        or len(reviewers) != 1
        or not isinstance(reviewers[0], dict)
        or not isinstance(reviewers[0].get("reviewer"), dict)
    ):
        raise ValueError("Plan approval Environment must have exactly one configured reviewer")
    reviewer = reviewers[0]["reviewer"]
    login = reviewer.get("login")
    if (
        reviewer.get("type") != "User"
        or not isinstance(login, str)
        or not login
        or login.casefold() == APPROVER_LOGIN.casefold()
    ):
        raise ValueError("Plan approval reviewer must be an independent GitHub user")
    return login


def _approved_by_configured_reviewer(approvals: object, reviewer: str, dispatch_actor: str) -> bool:
    if reviewer.casefold() == dispatch_actor.casefold() or not isinstance(approvals, list):
        return False
    approved = []
    for approval in approvals:
        user = approval.get("user") if isinstance(approval, dict) else None
        login = user.get("login") if isinstance(user, dict) else None
        if (
            isinstance(approval, dict)
            and approval.get("state") == "approved"
            and isinstance(login, str)
            and login.casefold() == reviewer.casefold()
        ):
            approved.append(approval)
    return len(approved) == 1 and any(
        isinstance(environment, dict) and environment.get("name") == PLAN_APPROVAL_ENVIRONMENT
        for environment in approved[0].get("environments", [])
    )


def validate_authorization_record(
    deployment: dict[str, Any],
    *,
    repository: str,
    workflow_run: dict[str, Any],
    approvals: object,
    approval_environment: dict[str, Any],
    jobs: object,
    deployment_statuses: object,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = deployment.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Plan authorization Deployment payload is invalid")
    creator = deployment.get("creator")
    if not isinstance(creator, dict) or creator.get("login") != "github-actions[bot]":
        raise ValueError("Plan authorization was not issued by GitHub Actions")
    if deployment.get("environment") != AUTHORIZATION_ENVIRONMENT:
        raise ValueError("Plan authorization Deployment environment is invalid")
    if payload.get("schema_version") != 1 or payload.get("kind") != "production-plan-authorization":
        raise ValueError("Unsupported plan authorization record")
    if payload.get("repository") != repository:
        raise ValueError("Plan authorization repository does not match")
    action = payload.get("action")
    if action not in {"authorize", "revoke", "complete"}:
        raise ValueError("Plan authorization action is invalid")
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("Plan authorization record has no canonical plan")
    validate_plan(plan, now=now)
    digest = payload.get("plan_sha256")
    if not isinstance(digest, str) or digest != canonical_plan_digest(plan):
        raise ValueError("Plan authorization digest does not match its plan")
    try:
        approved_by = payload["approved_by"]
        dispatch_actor = workflow_run["actor"]["login"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Plan authorization reviewer identity is unavailable") from exc
    if not isinstance(approved_by, str) or not isinstance(dispatch_actor, str):
        raise ValueError("Plan authorization reviewer identity is invalid")
    if dispatch_actor.casefold() != APPROVER_LOGIN.casefold():
        raise ValueError("Plan authorization was not requested by the repository owner")
    configured_reviewer = validate_plan_approval_environment(approval_environment)
    if approved_by.casefold() != configured_reviewer.casefold():
        raise ValueError(
            "Plan authorization identity does not match the configured independent reviewer"
        )
    if not _approved_by_configured_reviewer(approvals, configured_reviewer, dispatch_actor):
        raise ValueError(
            "Plan authorization lacks the server-recorded independent reviewer approval"
        )

    run_id = payload.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id != workflow_run.get("id"):
        raise ValueError("Plan authorization workflow run identity does not match")
    if payload.get("workflow_path") != AUTHORIZATION_WORKFLOW_PATH:
        raise ValueError("Plan authorization workflow path is invalid")
    if (
        not isinstance(workflow_run.get("path"), str)
        or workflow_run["path"].split("@", 1)[0] != AUTHORIZATION_WORKFLOW_PATH
        or workflow_run.get("event") != "workflow_dispatch"
        or workflow_run.get("head_branch") != "main"
        or workflow_run.get("status") != "completed"
        or workflow_run.get("conclusion") != "success"
    ):
        raise ValueError("Plan authorization is not from a successful protected-main workflow run")
    if not isinstance(jobs, list) or not any(
        isinstance(job, dict)
        and job.get("name") == "Record plan authorization"
        and job.get("conclusion") == "success"
        for job in jobs
    ):
        raise ValueError("Plan authorization workflow job did not complete successfully")
    if (
        not isinstance(deployment_statuses, list)
        or not deployment_statuses
        or any(not isinstance(status, dict) for status in deployment_statuses)
    ):
        raise ValueError("Plan authorization Deployment has no valid status history")
    status_times = [
        _parse_timestamp(status.get("created_at"), "Deployment status timestamp")
        for status in deployment_statuses
    ]
    latest_status_index = max(range(len(status_times)), key=status_times.__getitem__)
    latest_status = deployment_statuses[latest_status_index]
    if (
        latest_status.get("state") != "success"
        or not isinstance(latest_status.get("creator"), dict)
        or latest_status["creator"].get("login") != "github-actions[bot]"
    ):
        raise ValueError("Plan authorization Deployment lacks a successful bot status")
    source_sha = payload.get("source_sha")
    if (
        not isinstance(source_sha, str)
        or not SHA_PATTERN.fullmatch(source_sha)
        or source_sha != workflow_run.get("head_sha")
        or source_sha != deployment.get("ref")
        or source_sha != deployment.get("sha")
    ):
        raise ValueError("Plan authorization source SHA does not match its workflow and Deployment")
    recorded = _parse_timestamp(payload.get("recorded_at"), "recorded timestamp")
    created = _parse_timestamp(deployment.get("created_at"), "Deployment timestamp")
    current = _current_utc(now)
    if recorded > current + FUTURE_TOLERANCE or abs(created - recorded) > timedelta(minutes=5):
        raise ValueError("Plan authorization timestamp is invalid")
    return payload


def _current_utc(now: datetime | None = None) -> datetime:
    """Return a UTC wall clock without trusting a skewed platform UTC clock."""
    if now is not None:
        return now.astimezone(UTC)
    # Windows UTC can lag local time after sleep/resume or host time sync.
    # GitHub timestamps are UTC, so use the later converted wall-clock reading.
    local_as_utc = datetime.now().astimezone().astimezone(UTC)
    utc_clock = datetime.now(UTC)
    return max(local_as_utc, utc_clock)


def active_authorization(
    deployments: Iterable[dict[str, Any]],
    *,
    plan_id: str,
    repository: str,
    run_lookup: Callable[[int], dict[str, Any]],
    approvals_lookup: Callable[[int], object],
    environment_lookup: Callable[[], dict[str, Any]],
    jobs_lookup: Callable[[int], object],
    statuses_lookup: Callable[[int], object],
    now: datetime | None = None,
) -> dict[str, Any]:
    relevant = [
        deployment
        for deployment in deployments
        if isinstance(deployment, dict)
        and isinstance(deployment.get("payload"), dict)
        and isinstance(deployment["payload"].get("plan"), dict)
        and deployment["payload"]["plan"].get("plan_id") == plan_id
    ]
    if not relevant:
        raise ValueError(f"No plan authorization exists for {plan_id}")

    verified: list[dict[str, Any]] = []
    environment = environment_lookup()
    for deployment in relevant:
        payload = deployment.get("payload")
        run_id = payload.get("workflow_run_id") if isinstance(payload, dict) else None
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            raise ValueError("Plan authorization workflow run ID is invalid")
        verified.append(
            validate_authorization_record(
                deployment,
                repository=repository,
                workflow_run=run_lookup(run_id),
                approvals=approvals_lookup(run_id),
                approval_environment=environment,
                jobs=jobs_lookup(run_id),
                deployment_statuses=statuses_lookup(int(deployment.get("id", 0))),
                now=now,
            )
        )

    authorizations = [payload for payload in verified if payload.get("action") == "authorize"]
    if len(authorizations) != 1:
        raise ValueError("Plan authorization ledger contains a duplicate or missing authorization")
    transitions = [
        payload for payload in verified if payload.get("action") in {"revoke", "complete"}
    ]
    if len(transitions) > 1:
        raise ValueError("Plan authorization ledger contains duplicate terminal transitions")
    authorization = authorizations[0]
    for payload in verified:
        if payload.get("plan_sha256") != authorization.get("plan_sha256") or payload.get(
            "plan"
        ) != authorization.get("plan"):
            raise ValueError("Plan authorization transition changed the approved plan")
    if transitions:
        transition = transitions[0]
        authorization_time = _parse_timestamp(
            next(
                deployment["created_at"]
                for deployment in relevant
                if deployment.get("payload") is authorizations[0]
            ),
            "Deployment timestamp",
        )
        transition_time = _parse_timestamp(
            next(
                deployment["created_at"]
                for deployment in relevant
                if deployment.get("payload") is transition
            ),
            "Deployment timestamp",
        )
        if transition_time <= authorization_time:
            raise ValueError("Plan authorization terminal transition predates authorization")
        if transition.get("action") == "revoke":
            raise ValueError("Plan authorization has been revoked")
        raise ValueError("Plan authorization has been completed")
    validate_plan(authorization["plan"], now=now)
    return authorization


def validate_release_scope(
    plan: dict[str, Any],
    commit_shas: list[str],
    pull_requests: list[dict[str, Any]],
    *,
    authorization_time: datetime | None = None,
) -> None:
    """Require every compared commit and PR file to be covered by the approved plan."""
    if not commit_shas:
        raise ValueError("Release comparison has no commits after the plan baseline")
    if not pull_requests:
        raise ValueError("Release changes have no associated merged pull request")
    issue_pattern = re.compile(
        r"(?<![A-Za-z0-9_])(?:"
        + "|".join(re.escape(f"#{issue}") for issue in sorted(plan["issues"], reverse=True))
        + r")(?!\d)"
    )
    covered_commits: set[str] = set()
    allowed_paths = plan["allowed_paths"]
    for pull_request in pull_requests:
        if (
            pull_request.get("state") != "closed"
            or not pull_request.get("merged_at")
            or pull_request.get("base", {}).get("ref") != "main"
        ):
            raise ValueError("Plan scope includes a pull request that is not merged into main")
        issue_text = f"{pull_request.get('title', '')}\n{pull_request.get('body', '')}"
        if not issue_pattern.search(issue_text):
            raise ValueError("Every plan-scoped pull request must link a related issue")
        if authorization_time is not None:
            merged_at = _parse_timestamp(
                pull_request.get("merged_at"), "pull request merge timestamp"
            )
            if merged_at > authorization_time.astimezone(UTC):
                plan_reference = f"plan: {plan['plan_id']}"
                if plan_reference.casefold() not in issue_text.casefold():
                    raise ValueError(
                        "Every post-authorization pull request must identify its exact plan ID"
                    )
        associated = pull_request.get("commit_shas")
        if not isinstance(associated, list) or not associated:
            raise ValueError("Plan-scoped pull request has no verified associated commits")
        covered_commits.update(sha for sha in associated if isinstance(sha, str))
        files = pull_request.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Plan-scoped pull request has no complete file list")
        for path in files:
            if not isinstance(path, str) or not any(
                fnmatch.fnmatchcase(path, pattern) for pattern in allowed_paths
            ):
                raise ValueError(
                    f"Release changes file outside the approved plan allowlist: {path}"
                )
    if any(not SHA_PATTERN.fullmatch(sha) for sha in commit_shas):
        raise ValueError("Release comparison contains an invalid commit SHA")
    if not set(commit_shas).issubset(covered_commits):
        raise ValueError(
            "Every release commit must be associated with a merged plan-scoped pull request"
        )


def validate_release_version_scope(
    target_tag: str,
    running_version: str,
    plan: dict[str, Any],
) -> None:
    from scripts.production_promotion import parse_release_version

    target = parse_release_version(target_tag)
    running = parse_release_version(
        running_version if running_version.startswith("v") else f"v{running_version}"
    )
    if target <= running:
        raise ValueError("Promotion target must be newer than the running production version")
    if plan.get("release_version_policy") == "patch-only" and target[:2] != running[:2]:
        raise ValueError(
            "Plan authorizes patch releases only within the running major/minor version"
        )


def _github_request(path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    request = Request(
        f"https://api.github.com/repos/{repository}/{path.lstrip('/')}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("GitHub plan authorization API request failed") from exc
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub plan authorization API returned invalid JSON") from exc


def _github_list(path: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for page in range(1, 101):
        response = _github_request(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        if not isinstance(response, list) or any(not isinstance(item, dict) for item in response):
            raise ValueError("GitHub returned an invalid paginated authorization response")
        values.extend(response)
        if len(response) < 100:
            return values
    raise ValueError("GitHub authorization history exceeds the pagination safety limit")


def _all_plan_deployments() -> list[dict[str, Any]]:
    return _github_list(f"deployments?environment={AUTHORIZATION_ENVIRONMENT}")


def _fetch_run(run_id: int) -> dict[str, Any]:
    response = _github_request(f"actions/runs/{run_id}")
    if not isinstance(response, dict):
        raise ValueError("GitHub workflow run response is invalid")
    return response


def _fetch_approvals(run_id: int) -> object:
    response = _github_request(f"actions/runs/{run_id}/approvals")
    return response if isinstance(response, list) else None


def _fetch_jobs(run_id: int) -> object:
    response = _github_request(f"actions/runs/{run_id}/jobs?per_page=100")
    return response.get("jobs") if isinstance(response, dict) else None


def _fetch_statuses(deployment_id: int) -> object:
    response = _github_request(f"deployments/{deployment_id}/statuses?per_page=100")
    return response if isinstance(response, list) else None


def _environment() -> dict[str, Any]:
    response = _github_request(f"environments/{PLAN_APPROVAL_ENVIRONMENT}")
    if not isinstance(response, dict):
        raise ValueError("Plan approval Environment response is invalid")
    return response


def _plan_file(plan_id: str) -> Path:
    if not PLAN_ID_PATTERN.fullmatch(plan_id):
        raise ValueError("Plan ID is invalid")
    return Path("docs/plans/authorizations") / f"{plan_id}.json"


def _load_plan(plan_id: str) -> dict[str, Any]:
    path = _plan_file(plan_id)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Plan authorization document is missing or invalid") from exc
    if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
        raise ValueError("Plan authorization document ID does not match the request")
    validate_plan(plan)
    return plan


def _validate_active_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return active_authorization(
        _all_plan_deployments(),
        plan_id=str(plan["plan_id"]),
        repository=os.environ["GITHUB_REPOSITORY"],
        run_lookup=_fetch_run,
        approvals_lookup=_fetch_approvals,
        environment_lookup=_environment,
        jobs_lookup=_fetch_jobs,
        statuses_lookup=_fetch_statuses,
    )


def _validate_plan_ancestry(plan: dict[str, Any]) -> None:
    source_sha = os.environ.get("GITHUB_SHA", "")
    if not SHA_PATTERN.fullmatch(source_sha):
        raise ValueError("Workflow source SHA is invalid")
    if (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", plan["baseline_sha"], source_sha],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        raise ValueError("Plan baseline is not an ancestor of the protected workflow source")


def _validate_request() -> None:
    action = os.environ.get("PLAN_ACTION", "")
    if action not in {"authorize", "revoke", "complete"}:
        raise ValueError("PLAN_ACTION must be authorize, revoke, or complete")
    plan_id = os.environ.get("PLAN_ID", "")
    if os.environ.get("GITHUB_ACTOR", "").casefold() != APPROVER_LOGIN.casefold():
        raise ValueError("Only the repository owner may request a plan authorization transition")
    plan = _load_plan(plan_id)
    _validate_plan_ancestry(plan)
    reviewer = validate_plan_approval_environment(_environment())
    deployments = _all_plan_deployments()
    matching = [
        deployment
        for deployment in deployments
        if isinstance(deployment.get("payload"), dict)
        and isinstance(deployment["payload"].get("plan"), dict)
        and deployment["payload"]["plan"].get("plan_id") == plan_id
    ]
    if action == "authorize":
        if matching:
            raise ValueError("Plan ID already has an authorization record; use a new plan ID")
    else:
        active = _validate_active_plan(plan)
        if active.get("plan_sha256") != canonical_plan_digest(plan):
            raise ValueError("Current plan document differs from the active authorization")
    summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    summary.write_text(
        "## Plan authorization request\n\n"
        f"- Action: `{action}`\n- Plan ID: `{plan_id}`\n"
        f"- Digest: `{canonical_plan_digest(plan)}`\n"
        f"- Issues: {', '.join(f'#{issue}' for issue in plan['issues'])}\n"
        f"- Scope: {plan['scope']}\n"
        f"- Permitted operations: {', '.join(plan['permitted_operations'])}\n"
        f"- Authorized exceptions: {', '.join(plan['authorized_exceptions']) or 'none'}\n"
        f"- Independent reviewer: `{reviewer}`\n"
        f"- Expires: {plan['expires_at']}\n",
        encoding="utf-8",
    )
    with summary.open("a", encoding="utf-8") as output:
        output.write("\n### Exact canonical plan document\n\n```json\n")
        output.write(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
        output.write("\n```\n")
    print(f"Plan {plan_id} {action} request validated; SHA-256 {canonical_plan_digest(plan)}")


def _record_authorization() -> None:
    action = os.environ.get("PLAN_ACTION", "")
    plan_id = os.environ.get("PLAN_ID", "")
    plan = _load_plan(plan_id)
    _validate_plan_ancestry(plan)
    environment = _environment()
    reviewer = validate_plan_approval_environment(environment)
    run_id = int(os.environ["GITHUB_RUN_ID"])
    repository = os.environ["GITHUB_REPOSITORY"]
    run = _fetch_run(run_id)
    approvals = _fetch_approvals(run_id)
    if not _approved_by_configured_reviewer(
        approvals, reviewer, str(run.get("actor", {}).get("login", ""))
    ):
        raise ValueError("This workflow run lacks the configured independent reviewer approval")
    run_path = run.get("path")
    if not isinstance(run_path, str) or run_path.split("@", 1)[0] != AUTHORIZATION_WORKFLOW_PATH:
        raise ValueError("Current run is not the trusted plan authorization workflow")
    if run.get("head_sha") != os.environ.get("GITHUB_SHA") or run.get("id") != run_id:
        raise ValueError("Current workflow run source identity is inconsistent")
    actor = run.get("actor")
    actor_login = actor.get("login") if isinstance(actor, dict) else None
    if not isinstance(actor_login, str) or actor_login.casefold() != APPROVER_LOGIN.casefold():
        raise ValueError("Only the repository owner may request a plan authorization transition")
    if action == "authorize":
        if any(
            isinstance(deployment.get("payload"), dict)
            and isinstance(deployment["payload"].get("plan"), dict)
            and deployment["payload"]["plan"].get("plan_id") == plan_id
            for deployment in _all_plan_deployments()
        ):
            raise ValueError("Plan ID already has an authorization record")
    else:
        active = _validate_active_plan(plan)
        if active.get("plan_sha256") != canonical_plan_digest(plan):
            raise ValueError("Current plan document differs from the active authorization")

    payload = {
        "schema_version": 1,
        "kind": "production-plan-authorization",
        "repository": repository,
        "action": action,
        "plan": plan,
        "plan_sha256": canonical_plan_digest(plan),
        "workflow_run_id": run_id,
        "workflow_path": AUTHORIZATION_WORKFLOW_PATH,
        "source_sha": os.environ["GITHUB_SHA"],
        "approved_by": reviewer,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    deployment = _github_request(
        "deployments",
        method="POST",
        body={
            "ref": payload["source_sha"],
            "task": "production-plan-authorization",
            "auto_merge": False,
            "required_contexts": [],
            "environment": AUTHORIZATION_ENVIRONMENT,
            "production_environment": False,
            "description": f"Plan {plan_id}: {action}",
            "payload": payload,
        },
    )
    if not isinstance(deployment, dict) or not isinstance(deployment.get("id"), int):
        raise RuntimeError("GitHub did not create a durable plan authorization record")
    _github_request(
        f"deployments/{deployment['id']}/statuses",
        method="POST",
        body={
            "state": "success",
            "description": f"Plan {plan_id}: {action}",
            "auto_inactive": False,
        },
    )
    print(f"Recorded plan {plan_id} action={action} deployment_id={deployment['id']}")


def main() -> int:
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"validate-request", "record-authorization"}:
            raise ValueError(
                "Usage: production_plan_authorization.py validate-request|record-authorization"
            )
        if sys.argv[1] == "validate-request":
            _validate_request()
        else:
            _record_authorization()
    except (
        KeyError,
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        URLError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Plan authorization stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

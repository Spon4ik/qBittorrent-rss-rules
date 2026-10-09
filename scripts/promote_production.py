"""Operator-only production promotion entry point for the Windows host."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.production_approval import (
    APPROVAL_ENVIRONMENT,
    APPROVER_LOGIN,
    has_successful_job,
    validate_approval_environment,
    validate_release,
)
from scripts.production_plan_authorization import (
    AUTHORIZATION_ENVIRONMENT,
    SHA_PATTERN,
    active_authorization,
    canonical_plan_digest,
    validate_release_scope,
    validate_release_version_scope,
)
from scripts.production_plan_authorization import (
    _parse_timestamp as _parse_utc_timestamp,
)
from scripts.production_promotion import (
    compose_config_digest,
    create_compose_contract,
    exclusive_file_lock,
    parse_release_version,
    parse_remote_tag_sha,
    validate_approval_manifest,
    validate_audit_retry_evidence,
    validate_checkout_state,
    validate_compose_contract,
    validate_version_upgrade,
    verify_sqlite_backup,
)

REPOSITORY = "Spon4ik/qBittorrent-rss-rules"
SERVICE = "qb-rss-rules"
CONTAINER = "qb-rss-rules"
HEALTH_URL = "http://127.0.0.1:8000/health"
ENVIRONMENT = "production"
APPROVAL_WORKFLOW_PATH = ".github/workflows/production-approval.yml"
APPROVAL_JOB_NAME = "Record production approval"
APPROVAL_ARTIFACT_NAME = "production-approval-manifest"
WINDOWS_HOST = os.name == "nt"
FALLBACK_SOURCE_TAG = "v1.4.31"
FALLBACK_SOURCE_SHA = "c2abf87db7172b8444fb3b8b7c159f6e21735c20"


@dataclass(frozen=True)
class PromotionPaths:
    home: Path
    checkout: Path
    compose_file: Path
    env_file: Path
    private_root: Path
    stable_checkout: Path
    docker_exe: Path

    @classmethod
    def current_host(cls, checkout: Path) -> PromotionPaths:
        home = Path.home()
        config_dir = home / "docker-config"
        return cls(
            home=home,
            checkout=checkout.resolve(),
            compose_file=config_dir / "docker-compose.yml",
            env_file=config_dir / ".env",
            private_root=config_dir / "qbrss-private",
            stable_checkout=home / "deployments" / "qBittorrent-rss-rules",
            docker_exe=Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"),
        )


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required tool is unavailable: {Path(args[0]).name}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name} failed with exit code {result.returncode}")
    return result


def validate_source_rebuilt_fallback(
    manifest_path: Path,
    *,
    expected_compose_sha256: str,
    expected_dockerfile_sha256: str,
    expected_image_id: str,
) -> dict[str, Any]:
    try:
        evidence = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Source-rebuilt rollback evidence is missing or invalid") from exc
    if not isinstance(evidence, dict):
        raise ValueError("Source-rebuilt rollback evidence must be a JSON object")
    if evidence.get("schema_version") != 1:
        raise ValueError("Unsupported source-rebuilt rollback evidence schema")
    if (
        evidence.get("source_tag") != FALLBACK_SOURCE_TAG
        or evidence.get("source_sha") != FALLBACK_SOURCE_SHA
    ):
        raise ValueError("Rollback fallback must use the authorized v1.4.31 source")
    if not hmac.compare_digest(str(evidence.get("compose_sha256", "")), expected_compose_sha256):
        raise ValueError(
            "Fallback Compose/build inputs do not match the resolved production contract"
        )
    if evidence.get("dockerfile_sha256") != expected_dockerfile_sha256:
        raise ValueError("Fallback Dockerfile does not match the authorized source")
    if evidence.get("image_id") != expected_image_id or not expected_image_id.startswith("sha256:"):
        raise ValueError("Fallback image identity does not match Docker's inspectable immutable ID")
    if evidence.get("scratch_database_integrity") != "ok":
        raise ValueError("Fallback scratch database integrity was not verified")
    if (
        evidence.get("container_health_check") != "passed"
        or evidence.get("validated_app_version") != "1.4.31"
    ):
        raise ValueError(
            "Fallback image health and version were not verified against the scratch database"
        )
    if (
        not isinstance(evidence.get("scratch_database_rule_count"), int)
        or evidence["scratch_database_rule_count"] <= 0
    ):
        raise ValueError("Fallback scratch database compatibility was not verified")
    return evidence


class FinalizerCleanupUncertainError(RuntimeError):
    """The finalizer timed out and its process tree could not be confirmed stopped."""


def _terminate_process_tree(pid: int) -> None:
    """Stop a timed-out Windows command and every descendant before failing promotion."""
    try:
        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FinalizerCleanupUncertainError(
            f"Could not confirm termination of finalizer process tree {pid}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "taskkill returned a nonzero status").strip()
        raise FinalizerCleanupUncertainError(
            f"Could not confirm termination of finalizer process tree {pid}: {detail[:200]}"
        )


def _run_finalizer(
    command: list[str], cwd: Path, log: Any, timeout: int = 3600
) -> subprocess.CompletedProcess[str]:
    """Run the production finalizer and stop its full process tree on timeout."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            _terminate_process_tree(process.pid)
        except FinalizerCleanupUncertainError:
            raise
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired as wait_exc:
            raise FinalizerCleanupUncertainError(
                f"Finalizer process {process.pid} remained alive after process-tree termination"
            ) from wait_exc
        raise RuntimeError(
            f"Backend finalizer timed out after {timeout} seconds; process tree terminated"
        ) from exc
    return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")


def _finalizer_command(finalizer: Path) -> list[str]:
    """Build a cmd.exe invocation that runs the batch file from its checkout."""
    return ["cmd.exe", "/d", "/c", "call", finalizer.name, "--no-pause"]


def _read_health(url: str = HEALTH_URL, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Production health endpoint is unavailable or invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("app_version"), str):
        raise RuntimeError("Production health response lacks app_version")
    return payload


def _project_version(root: Path) -> str:
    try:
        with (root / "pyproject.toml").open("rb") as file:
            version = tomllib.load(file)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("Release checkout has no valid pyproject version") from exc
    if not isinstance(version, str):
        raise RuntimeError("Release checkout project version is invalid")
    return version


def secure_private_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    whoami = _run(["whoami.exe", "/user", "/fo", "csv", "/nh"])
    rows = list(csv.reader(whoami.stdout.splitlines()))
    if not rows or len(rows[0]) < 2 or not rows[0][1].startswith("S-"):
        raise RuntimeError("Could not identify the current Windows user for private storage ACLs")
    user_sid = rows[0][1]
    _run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{user_sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ]
    )
    if next(path.iterdir(), None) is not None:
        _run(["icacls.exe", str(path / "*"), "/reset", "/T", "/C"])


class PromotionManager:
    def __init__(self, paths: PromotionPaths, *, repository: str = REPOSITORY) -> None:
        self.paths = paths
        self.repository = repository

    @property
    def contract_file(self) -> Path:
        return self.paths.private_root / "compose-contract.json"

    @property
    def contract_key_file(self) -> Path:
        return self.paths.private_root / "compose-contract.key"

    @property
    def lock_file(self) -> Path:
        return self.paths.private_root / "production.lock"

    @property
    def journal_dir(self) -> Path:
        return self.paths.private_root / "deployments"

    def _api(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        args = ["gh", "api"]
        input_text = None
        if method != "GET":
            args.extend(["--method", method])
        args.append(path)
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload, separators=(",", ":"))
        result = _run(args, input_text=input_text)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub API returned invalid JSON") from exc

    def _compose_config(self) -> dict[str, Any]:
        for required in (self.paths.compose_file, self.paths.env_file, self.paths.docker_exe):
            if not required.is_file():
                raise RuntimeError(f"Required production configuration is missing: {required.name}")
        result = _run(
            [
                str(self.paths.docker_exe),
                "compose",
                "--env-file",
                str(self.paths.env_file),
                "-f",
                str(self.paths.compose_file),
                "config",
                "--format",
                "json",
            ],
            cwd=self.paths.checkout,
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Docker Compose returned invalid resolved configuration") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Docker Compose returned an unexpected configuration shape")
        return parsed

    def capture_compose_contract(self) -> None:
        if not WINDOWS_HOST:
            raise RuntimeError(
                "Compose contract capture is supported only on the production Windows host"
            )
        secure_private_root(self.paths.private_root)
        if self.contract_file.exists() or self.contract_key_file.exists():
            raise RuntimeError("A private Compose contract already exists; refusing to replace it")
        if not self.paths.env_file.is_file():
            raise RuntimeError("The shared Compose .env file is required")

        config = self._compose_config()
        _read_health()
        services = config.get("services")
        service = services.get(SERVICE) if isinstance(services, dict) else None
        build = service.get("build") if isinstance(service, dict) else None
        context = build.get("context") if isinstance(build, dict) else None
        if not isinstance(context, str):
            raise RuntimeError("Current production service has no resolved build context")
        volumes = service.get("volumes") if isinstance(service, dict) else None
        database_mount = next(
            (
                volume
                for volume in volumes or []
                if isinstance(volume, dict) and volume.get("target") == "/app/data"
            ),
            None,
        )
        database_source = database_mount.get("source") if isinstance(database_mount, dict) else None
        if (
            not isinstance(database_source, str)
            or not (Path(database_source) / "qb_rules.db").is_file()
        ):
            raise RuntimeError(
                "Current production SQLite database is missing from the /app/data mount"
            )

        key = secrets.token_bytes(32)
        try:
            with self.contract_key_file.open("xb") as key_file:
                key_file.write(key)
                key_file.flush()
                os.fsync(key_file.fileno())
            if os.name != "nt":
                self.contract_key_file.chmod(0o600)
            contract = create_compose_contract(
                config,
                service=SERVICE,
                repository=self.repository,
                compose_file=str(self.paths.compose_file),
                env_file=str(self.paths.env_file),
                key=key,
                captured_at=datetime.now(UTC).isoformat(),
            )
            temporary = self.contract_file.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(temporary, self.contract_file)
        except Exception:
            self.contract_key_file.unlink(missing_ok=True)
            self.contract_file.with_suffix(".json.tmp").unlink(missing_ok=True)
            raise
        print(
            "Captured the private Compose contract; no database, Compose, or container was changed."
        )

    def _validate_approval(
        self, tag: str, run_id: int
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        if not tag.startswith("v"):
            raise ValueError("Promotion requires a vMAJOR.MINOR.PATCH release tag")
        parse_release_version(tag)
        environment = self._api(f"repos/{self.repository}/environments/{APPROVAL_ENVIRONMENT}")
        if not isinstance(environment, dict) or not validate_approval_environment(environment):
            raise ValueError("Production approval Environment is missing or not protected")

        run = self._api(f"repos/{self.repository}/actions/runs/{run_id}")
        if not isinstance(run, dict):
            raise ValueError("GitHub approval run response is invalid")
        if (
            run.get("path", "").split("@", 1)[0] != APPROVAL_WORKFLOW_PATH
            or run.get("event") != "workflow_dispatch"
            or run.get("head_branch") != "main"
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
        ):
            raise ValueError("Approval run is not a successful main-branch production approval")

        branch = self._api(f"repos/{self.repository}/branches/main")
        current_main_sha = branch.get("commit", {}).get("sha") if isinstance(branch, dict) else None
        if run.get("head_sha") != current_main_sha:
            raise ValueError("Approval was created by an outdated main workflow revision")

        approval_jobs = self._api(
            f"repos/{self.repository}/actions/runs/{run_id}/jobs?per_page=100"
        )
        jobs = approval_jobs.get("jobs", []) if isinstance(approval_jobs, dict) else []
        if not has_successful_job(jobs, APPROVAL_JOB_NAME):
            raise ValueError("Approval workflow did not complete its protected Environment job")

        later_runs = self._api(
            f"repos/{self.repository}/actions/workflows/production-approval.yml/runs?"
            "branch=main&event=workflow_dispatch&per_page=100"
        )
        for later in later_runs.get("workflow_runs", []) if isinstance(later_runs, dict) else []:
            if (
                isinstance(later, dict)
                and isinstance(later.get("id"), int)
                and later["id"] > run_id
                and later.get("status") == "completed"
                and later.get("conclusion") == "success"
            ):
                later_jobs_data = self._api(
                    f"repos/{self.repository}/actions/runs/{later['id']}/jobs?per_page=100"
                )
                later_jobs = (
                    later_jobs_data.get("jobs", []) if isinstance(later_jobs_data, dict) else []
                )
                if has_successful_job(later_jobs, APPROVAL_JOB_NAME):
                    raise ValueError("A newer production release approval supersedes this run")

        artifacts_response = self._api(
            f"repos/{self.repository}/actions/runs/{run_id}/artifacts?per_page=100"
        )
        artifacts = artifacts_response.get("artifacts", [])
        matches = [
            artifact
            for artifact in artifacts
            if artifact.get("name") == APPROVAL_ARTIFACT_NAME and not artifact.get("expired")
        ]
        if len(matches) != 1:
            raise ValueError("Approval run has no unique, unexpired approval manifest artifact")

        with tempfile.TemporaryDirectory(prefix="qbrss-approval-") as directory:
            _run(
                [
                    "gh",
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    self.repository,
                    "--name",
                    APPROVAL_ARTIFACT_NAME,
                    "--dir",
                    directory,
                ]
            )
            manifests = list(Path(directory).rglob("approval-manifest.json"))
            if len(manifests) != 1 or not manifests[0].is_file():
                raise ValueError("Approval artifact does not contain one manifest JSON file")
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Approval manifest must be a JSON object")
        return manifest, str(current_main_sha), run

    def _api_pages(self, path: str, *, object_key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            separator = "&" if "?" in path else "?"
            response = self._api(f"{path}{separator}per_page=100&page={page}")
            batch = (
                response.get(object_key, [])
                if object_key and isinstance(response, dict)
                else response
            )
            if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                raise ValueError(
                    "GitHub returned an invalid paginated production authorization response"
                )
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise ValueError(
            "GitHub production authorization history exceeded its pagination safety limit"
        )

    def _validate_plan_authorization(self, plan_id: str) -> dict[str, Any]:
        deployments = self._api_pages(
            f"repos/{self.repository}/deployments?environment={AUTHORIZATION_ENVIRONMENT}"
        )
        authorization = active_authorization(
            deployments,
            plan_id=plan_id,
            repository=self.repository,
            run_lookup=lambda run_id: self._api(f"repos/{self.repository}/actions/runs/{run_id}"),
            approvals_lookup=lambda run_id: self._api(
                f"repos/{self.repository}/actions/runs/{run_id}/approvals"
            ),
            environment_lookup=lambda: self._api(
                f"repos/{self.repository}/environments/production-plan-approval"
            ),
            jobs_lookup=lambda run_id: self._api(
                f"repos/{self.repository}/actions/runs/{run_id}/jobs?per_page=100"
            ).get("jobs", []),
            statuses_lookup=lambda deployment_id: self._api_pages(
                f"repos/{self.repository}/deployments/{deployment_id}/statuses"
            ),
        )
        matching = [
            deployment
            for deployment in deployments
            if isinstance(deployment.get("payload"), dict)
            and deployment["payload"].get("action") == "authorize"
            and isinstance(deployment["payload"].get("plan"), dict)
            and deployment["payload"]["plan"].get("plan_id") == plan_id
        ]
        if len(matching) != 1 or not isinstance(matching[0].get("id"), int):
            raise ValueError("Plan authorization Deployment identity is unavailable")
        return {**authorization, "deployment_id": matching[0]["id"]}

    def _validate_plan_release_scope(
        self,
        authorization: dict[str, Any],
        release_sha: str,
    ) -> None:
        plan = authorization.get("plan")
        authorization_sha = authorization.get("source_sha")
        if not isinstance(plan, dict) or not isinstance(authorization_sha, str):
            raise ValueError("Active plan authorization source evidence is invalid")
        auth_comparison = self._api(
            f"repos/{self.repository}/compare/{authorization_sha}...{release_sha}"
        )
        if not isinstance(auth_comparison, dict) or auth_comparison.get("status") not in {
            "ahead",
            "identical",
        }:
            raise ValueError(
                "Release does not contain the trusted plan authorization implementation"
            )

        baseline = str(plan.get("baseline_sha", ""))
        commit_shas: list[str] = []
        for page in range(1, 101):
            commits_page = self._api(
                f"repos/{self.repository}/commits?sha={release_sha}&per_page=100&page={page}"
            )
            if not isinstance(commits_page, list) or any(
                not isinstance(commit, dict)
                or not isinstance(commit.get("sha"), str)
                or not SHA_PATTERN.fullmatch(commit["sha"])
                for commit in commits_page
            ):
                raise ValueError("GitHub returned an incomplete plan-to-release commit list")
            reached_baseline = False
            for commit in commits_page:
                if commit["sha"] == baseline:
                    reached_baseline = True
                    break
                commit_shas.append(commit["sha"])
            if reached_baseline:
                break
            if len(commits_page) < 100:
                raise ValueError("Release does not descend from the approved plan baseline")
        else:
            raise ValueError("Plan-to-release commit history exceeded its pagination safety limit")
        if not commit_shas:
            raise ValueError("Release contains no commits after the plan baseline")

        pull_requests: dict[int, dict[str, Any]] = {}
        associated_commits: dict[int, set[str]] = {}
        for commit_sha in commit_shas:
            associated = self._api_pages(f"repos/{self.repository}/commits/{commit_sha}/pulls")
            if not associated:
                raise ValueError("A plan-to-release commit has no associated pull request")
            for pull in associated:
                number = pull.get("number")
                if not isinstance(number, int):
                    raise ValueError("GitHub returned an invalid associated pull request")
                pull_requests[number] = pull
                associated_commits.setdefault(number, set()).add(commit_sha)

        normalized_pulls: list[dict[str, Any]] = []
        for number, associated_pull in sorted(pull_requests.items()):
            pull = self._api(f"repos/{self.repository}/pulls/{number}")
            if not isinstance(pull, dict):
                raise ValueError("GitHub returned an invalid plan-scoped pull request")
            file_records = self._api_pages(f"repos/{self.repository}/pulls/{number}/files")
            files = [record.get("filename") for record in file_records]
            changed_files = pull.get("changed_files")
            if (
                not isinstance(changed_files, int)
                or changed_files != len(files)
                or any(not isinstance(filename, str) for filename in files)
            ):
                raise ValueError("Pull request changed-file list is incomplete")
            normalized_pulls.append(
                {
                    "number": number,
                    "state": pull.get("state"),
                    "merged_at": pull.get("merged_at"),
                    "base": pull.get("base"),
                    "title": pull.get("title", associated_pull.get("title", "")),
                    "body": pull.get("body", ""),
                    "commit_shas": sorted(associated_commits[number]),
                    "files": files,
                }
            )

        authorization_time = _parse_utc_timestamp(
            authorization.get("recorded_at"), "plan authorization timestamp"
        )
        validate_release_scope(
            plan,
            commit_shas,
            normalized_pulls,
            authorization_time=authorization_time.astimezone(UTC),
        )

    def _checkout_preflight(self, tag: str, expected_sha: str) -> None:
        root = self.paths.checkout
        head_sha = _run(["git", "-C", str(root), "rev-parse", "HEAD"]).stdout.strip()
        branch_name = _run(["git", "-C", str(root), "branch", "--show-current"]).stdout.strip()
        clean = not bool(_run(["git", "-C", str(root), "status", "--porcelain"]).stdout.strip())
        validate_checkout_state(
            checkout_root=str(root),
            expected_root=str(self.paths.stable_checkout),
            head_sha=head_sha,
            expected_sha=expected_sha,
            branch_name=branch_name,
            clean=clean,
        )

        local_tag_sha = _run(
            ["git", "-C", str(root), "rev-parse", f"refs/tags/{tag}^{{commit}}"]
        ).stdout.strip()
        if local_tag_sha != expected_sha:
            raise ValueError("Local release tag does not resolve to the approved SHA")
        remote_tags = _run(
            [
                "git",
                "-C",
                str(root),
                "ls-remote",
                "--tags",
                "origin",
                f"refs/tags/{tag}",
                f"refs/tags/{tag}^{{}}",
            ]
        ).stdout
        if parse_remote_tag_sha(remote_tags, tag) != expected_sha:
            raise ValueError("Published origin tag does not resolve to the approved SHA")
        _run(["git", "-C", str(root), "fetch", "--no-tags", "origin", "main"])
        ancestry = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", expected_sha, "FETCH_HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if ancestry.returncode != 0:
            raise ValueError("Approved release SHA is no longer contained in origin/main")

    def preflight(
        self,
        tag: str,
        approval_run_id: int | None = None,
        *,
        plan_id: str | None = None,
        allow_source_rebuilt_fallback: bool = False,
    ) -> dict[str, Any]:
        if (approval_run_id is None) == (plan_id is None):
            raise ValueError("Promotion requires exactly one of --approval-run-id or --plan-id")
        authorization: dict[str, Any] | None = None
        authorization_run_id: int | None = None
        if plan_id is not None:
            authorization = self._validate_plan_authorization(plan_id)
            plan_document = authorization.get("plan")
            if not isinstance(plan_document, dict):
                raise ValueError("Active plan authorization has no canonical plan document")
            if authorization.get("plan_sha256") != canonical_plan_digest(plan_document):
                raise ValueError(
                    "Active plan authorization digest does not match the approved plan"
                )
            if "production-promotion" not in plan_document.get("permitted_operations", []):
                raise ValueError("The approved plan does not permit production promotion")
            if allow_source_rebuilt_fallback and "source-rebuilt-rollback" not in plan_document.get(
                "authorized_exceptions", []
            ):
                raise ValueError(
                    "The approved plan does not authorize a source-rebuilt rollback image"
                )
            plan_path = (
                self.paths.checkout / "docs" / "plans" / "authorizations" / f"{plan_id}.json"
            )
            try:
                release_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "Release checkout does not contain the approved plan document"
                ) from exc
            if canonical_plan_digest(release_plan) != authorization.get("plan_sha256"):
                raise ValueError(
                    "Release checkout plan document differs from the owner-approved plan"
                )
            branch = self._api(f"repos/{self.repository}/branches/main")
            current_main_sha = (
                branch.get("commit", {}).get("sha") if isinstance(branch, dict) else None
            )
            raw_authorization_run_id = authorization.get("workflow_run_id")
            if not isinstance(raw_authorization_run_id, int):
                raise ValueError("Plan authorization workflow run ID is invalid")
            authorization_run_id = raw_authorization_run_id
            approval_run = self._api(f"repos/{self.repository}/actions/runs/{authorization_run_id}")
            if not isinstance(approval_run, dict) or not isinstance(current_main_sha, str):
                raise ValueError(
                    "Plan authorization workflow or current main identity is unavailable"
                )
        else:
            if approval_run_id is None:
                raise ValueError("Release approval run ID is required for the legacy path")
            manifest, current_main_sha, approval_run = self._validate_approval(tag, approval_run_id)

        commit_sha, release_url, ci_run, api_run = validate_release(tag, self.repository)
        if authorization is None:
            if approval_run_id is None:
                raise ValueError("Release approval run ID is required for the legacy path")
            if commit_sha != manifest.get("commit_sha"):
                raise ValueError(
                    "Approval manifest source SHA no longer matches the published release tag"
                )
            validate_approval_manifest(
                manifest,
                repository=self.repository,
                tag=tag,
                commit_sha=commit_sha,
                approval_run_id=approval_run_id,
                approver=APPROVER_LOGIN,
            )
            if (
                manifest.get("release_url") != release_url
                or manifest.get("ci_run_id") != ci_run.get("databaseId")
                or manifest.get("api_run_id") != api_run.get("databaseId")
                or manifest.get("approval_run_url") != approval_run.get("html_url")
            ):
                raise ValueError("Approval manifest release or validation evidence has changed")
        else:
            self._validate_plan_release_scope(authorization, commit_sha)

        if _project_version(self.paths.checkout) != tag[1:]:
            raise ValueError("Release tag and stable checkout project version do not match")
        self._checkout_preflight(tag, commit_sha)

        if not self.contract_file.is_file() or not self.contract_key_file.is_file():
            raise ValueError("Capture the private Compose contract before promotion")
        contract = json.loads(self.contract_file.read_text(encoding="utf-8"))
        key = self.contract_key_file.read_bytes()
        if not isinstance(contract, dict) or len(key) != 32:
            raise ValueError("Private Compose contract is invalid")

        compose_config = self._compose_config()
        validate_compose_contract(
            contract,
            compose_config,
            repository=self.repository,
            compose_file=str(self.paths.compose_file),
            env_file=str(self.paths.env_file),
            expected_context=str(self.paths.stable_checkout),
            key=key,
        )
        mounts = contract.get("mounts", [])
        data_mount = next((mount for mount in mounts if mount.get("target") == "/app/data"), None)
        if not isinstance(data_mount, dict):
            raise ValueError("Private Compose contract is missing the persistent database mount")
        database_path = Path(data_mount["source"]) / "qb_rules.db"
        if not database_path.is_file():
            raise ValueError("Persistent production SQLite database is missing")

        health = _read_health()
        running_version = health["app_version"]
        target_version = _project_version(self.paths.checkout)
        validate_version_upgrade(target_version, running_version)
        if authorization is not None:
            validate_release_version_scope(target_version, running_version, authorization["plan"])
        if health.get("database_ready") is False:
            raise ValueError("Production health reports that the database is not ready")

        if not self.paths.docker_exe.is_file():
            raise ValueError("Docker Desktop CLI is missing")
        _run([str(self.paths.docker_exe), "info"], timeout=30)
        image_id = _run(
            [str(self.paths.docker_exe), "inspect", "--format", "{{.Image}}", CONTAINER]
        ).stdout.strip()
        if not image_id.startswith("sha256:"):
            raise ValueError("Current production container has no immutable image identity")
        fallback_evidence: dict[str, Any] | None = None
        try:
            retained_image_id = _run(
                [
                    str(self.paths.docker_exe),
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    image_id,
                ]
            ).stdout.strip()
        except RuntimeError as exc:
            if not allow_source_rebuilt_fallback:
                raise ValueError(
                    f"Previous production image {image_id} is not inspectable for rollback retention; "
                    "recover the exact image or use the explicitly approved source-fallback procedure"
                ) from exc
            fallback_manifest = (
                self.paths.private_root / "rollback" / "v1.4.31-source-fallback-verified.json"
            )
            compose_digest = compose_config_digest(
                compose_config,
                service=SERVICE,
                key=key,
            )
            dockerfile = self.paths.stable_checkout / "Dockerfile"
            fallback_id = _run(
                [
                    str(self.paths.docker_exe),
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    "qbrss-v1.4.31-source-fallback:verified",
                ]
            ).stdout.strip()
            fallback_evidence = validate_source_rebuilt_fallback(
                fallback_manifest,
                expected_compose_sha256=compose_digest,
                expected_dockerfile_sha256=hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
                expected_image_id=fallback_id,
            )
            if fallback_evidence.get("source_sha") != FALLBACK_SOURCE_SHA:
                raise ValueError("Source-rebuilt rollback image provenance is invalid") from exc
        if fallback_evidence is None and retained_image_id != image_id:
            raise ValueError(
                f"Previous production image {image_id} resolved to {retained_image_id or 'no image ID'}; "
                "rollback retention requires the exact immutable image"
            )

        venv_python = self.paths.checkout / ".venv" / "Scripts" / "python.exe"
        finalizer = self.paths.checkout / "Finalize-Backend.cmd"
        runtime_state = self.paths.checkout / "scripts" / "runtime_state.bat"
        for required in (venv_python, finalizer, runtime_state):
            if not required.is_file():
                raise ValueError(f"Stable release checkout is missing {required.name}")
        _run(
            [
                str(venv_python),
                "-c",
                "import fastapi, mypy, pytest, ruff, sqlalchemy",
            ],
            cwd=self.paths.checkout,
        )
        return {
            "tag": tag,
            "commit_sha": commit_sha,
            "target_version": target_version,
            "running_version": running_version,
            "current_main_sha": current_main_sha,
            "release_url": release_url,
            "approval_run_id": approval_run_id if authorization is None else None,
            "approval_run_url": approval_run.get("html_url"),
            "authorization_mode": "plan" if authorization is not None else "release",
            "plan_id": plan_id,
            "plan_authorization_run_id": authorization_run_id,
            "plan_authorization_reviewer": (
                authorization.get("approved_by") if authorization is not None else None
            ),
            "plan_authorization_deployment_id": (
                authorization.get("deployment_id") if authorization is not None else None
            ),
            "plan_authorization_digest": (
                authorization.get("plan_sha256") if authorization is not None else None
            ),
            "ci_run_id": ci_run["databaseId"],
            "ci_run_url": ci_run["url"],
            "api_run_id": api_run["databaseId"],
            "api_run_url": api_run["url"],
            "database_path": str(database_path),
            "previous_image_id": image_id,
            "previous_image_fallback": fallback_evidence,
            "contract_hmac": contract["compose_hmac"],
        }

    def _create_deployment(self, evidence: dict[str, Any]) -> int:
        response = self._api(
            f"repos/{self.repository}/deployments",
            method="POST",
            payload={
                "ref": evidence["commit_sha"],
                "task": "deploy",
                "auto_merge": False,
                "required_contexts": [],
                "environment": ENVIRONMENT,
                "production_environment": True,
                "description": f"Manual promotion of {evidence['tag']}",
                "payload": {
                    "release_tag": evidence["tag"],
                    "source_sha": evidence["commit_sha"],
                    "release_url": evidence["release_url"],
                    "approval_run_id": evidence["approval_run_id"],
                    "ci_run_id": evidence["ci_run_id"],
                    "api_run_id": evidence["api_run_id"],
                    "authorization_mode": evidence["authorization_mode"],
                    "plan_id": evidence["plan_id"],
                    "plan_authorization_run_id": evidence["plan_authorization_run_id"],
                    "plan_authorization_reviewer": evidence["plan_authorization_reviewer"],
                    "plan_authorization_deployment_id": evidence[
                        "plan_authorization_deployment_id"
                    ],
                    "plan_authorization_digest": evidence["plan_authorization_digest"],
                },
            },
        )
        deployment_id = response.get("id") if isinstance(response, dict) else None
        if not isinstance(deployment_id, int):
            raise RuntimeError("GitHub did not create a production Deployment record")
        return deployment_id

    def _set_deployment_status(
        self,
        deployment_id: int,
        *,
        state: str,
        description: str,
        log_url: str,
    ) -> None:
        self._api(
            f"repos/{self.repository}/deployments/{deployment_id}/statuses",
            method="POST",
            payload={
                "state": state,
                "description": description[:140],
                "log_url": log_url,
                "auto_inactive": False,
            },
        )

    def _write_journal(self, record: dict[str, Any]) -> Path:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        tag = str(record["tag"])
        deployment_id = int(record["deployment_id"])
        path = self.journal_dir / f"{tag}-{deployment_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path

    def promote(
        self,
        tag: str,
        approval_run_id: int | None = None,
        *,
        plan_id: str | None = None,
        allow_source_rebuilt_fallback: bool = False,
    ) -> None:
        if not WINDOWS_HOST:
            raise RuntimeError("Production promotion is supported only on the Windows host")
        secure_private_root(self.paths.private_root)
        with exclusive_file_lock(self.lock_file):
            evidence = self.preflight(
                tag,
                approval_run_id,
                plan_id=plan_id,
                allow_source_rebuilt_fallback=allow_source_rebuilt_fallback,
            )
            deployment_id = self._create_deployment(evidence)
            record: dict[str, Any] = {
                **evidence,
                "deployment_id": deployment_id,
                "stage": "deployment-created",
                "started_at": datetime.now(UTC).isoformat(),
                "private_backup_path": "",
                "backup_sha256": "",
                "previous_image_rollback_tag": "",
                "previous_image_fallback": evidence.get("previous_image_fallback"),
                "deployed_image_id": "",
                "finalizer_exit_code": None,
            }
            try:
                self._write_journal(record)
            except Exception as exc:
                try:
                    self._set_deployment_status(
                        deployment_id,
                        state="failure",
                        description=f"Promotion stopped for {tag}; private journal could not be created",
                        log_url=evidence["approval_run_url"],
                    )
                except Exception:
                    print(
                        "GitHub failure status is pending; the private deployment journal could not be created."
                    )
                raise RuntimeError(
                    "Could not persist the private deployment journal; production mutation did not start."
                ) from exc
            try:
                self._set_deployment_status(
                    deployment_id,
                    state="in_progress",
                    description=f"Promoting {tag} at {evidence['commit_sha'][:12]}",
                    log_url=evidence["approval_run_url"],
                )
                backup_root = self.paths.private_root / "backups"
                backup_root.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                backup_path = backup_root / f"{tag}-{deployment_id}-{timestamp}.sqlite3"
                record["stage"] = "deployment-created"
                record["private_backup_path"] = str(backup_path)
                self._write_journal(record)
                record["backup_sha256"] = verify_sqlite_backup(
                    Path(evidence["database_path"]), backup_path
                )
                record["stage"] = "backup-verified"
                self._write_journal(record)

                rollback_source = evidence.get("previous_image_fallback")
                rollback_image_id = (
                    str(rollback_source["image_id"])
                    if isinstance(rollback_source, dict)
                    else evidence["previous_image_id"]
                )
                rollback_tag = f"qbittorrent-rss-rule-manager:rollback-{timestamp.replace('T', '-').replace('Z', '')}"
                _run([str(self.paths.docker_exe), "image", "tag", rollback_image_id, rollback_tag])
                retained_image_id = _run(
                    [
                        str(self.paths.docker_exe),
                        "image",
                        "inspect",
                        "--format",
                        "{{.Id}}",
                        rollback_tag,
                    ]
                ).stdout.strip()
                if retained_image_id != rollback_image_id:
                    raise RuntimeError(
                        "Previous production rollback image was not retained by immutable ID"
                    )
                record["previous_image_rollback_tag"] = rollback_tag
                record["stage"] = "finalizer-running"
                self._write_journal(record)

                log_path = self.paths.private_root / "logs" / f"{tag}-{deployment_id}-finalizer.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                finalizer = self.paths.checkout / "Finalize-Backend.cmd"
                with log_path.open("w", encoding="utf-8", newline="\n") as log:
                    finalizer_result = _run_finalizer(
                        _finalizer_command(finalizer), self.paths.checkout, log
                    )
                record["finalizer_exit_code"] = finalizer_result.returncode
                record["finalizer_log_path"] = str(log_path)
                if finalizer_result.returncode != 0:
                    raise RuntimeError(
                        f"Backend finalizer failed with exit code {finalizer_result.returncode}"
                    )

                health = _read_health()
                if health["app_version"] != evidence["target_version"]:
                    raise RuntimeError(
                        "Production health version does not equal the approved release"
                    )
                runtime_log = (
                    self.paths.private_root / "logs" / f"{tag}-{deployment_id}-runtime.log"
                )
                with runtime_log.open("w", encoding="utf-8", newline="\n") as log:
                    runtime_result = subprocess.run(
                        [
                            str(self.paths.checkout / "scripts" / "runtime_state.bat"),
                            "--require-runtime-current",
                        ],
                        cwd=self.paths.checkout,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        timeout=60,
                        check=False,
                    )
                if runtime_result.returncode != 0:
                    raise RuntimeError("Runtime-state version check failed after promotion")
                deployed_image = _run(
                    [str(self.paths.docker_exe), "inspect", "--format", "{{.Image}}", CONTAINER]
                ).stdout.strip()
                if not deployed_image.startswith("sha256:"):
                    raise RuntimeError(
                        "Deployed production container has no immutable image identity"
                    )
                record.update(
                    {
                        "stage": "health-verified",
                        "deployed_image_id": deployed_image,
                        "health_version": health["app_version"],
                        "health_verified_at": datetime.now(UTC).isoformat(),
                        "runtime_state_log_path": str(runtime_log),
                    }
                )
                self._write_journal(record)
            except FinalizerCleanupUncertainError as exc:
                record["stage"] = "finalizer-cleanup-required"
                record["failure"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
                try:
                    self._write_journal(record)
                except Exception:
                    print(
                        "Finalizer cleanup could not be confirmed and the private journal update failed; "
                        "do not retry promotion until the host process tree is inspected."
                    )
                raise
            except Exception as exc:
                record["stage"] = "failure"
                record["failure"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
                try:
                    self._write_journal(record)
                except Exception:
                    print(
                        "Private failure journal update failed; GitHub failure status will still be attempted."
                    )
                try:
                    self._set_deployment_status(
                        deployment_id,
                        state="failure",
                        description=f"Promotion failed for {tag}; inspect the operator-local record",
                        log_url=evidence["approval_run_url"],
                    )
                except Exception:
                    print(
                        "GitHub failure status is pending; operator-local journal records the failure."
                    )
                raise

            try:
                self._set_deployment_status(
                    deployment_id,
                    state="success",
                    description=(
                        f"{tag} source {evidence['commit_sha'][:12]} image {record['deployed_image_id']}"
                    ),
                    log_url=evidence["approval_run_url"],
                )
            except Exception as exc:
                record["stage"] = "audit-pending"
                record["audit_error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
                self._write_journal(record)
                raise RuntimeError(
                    "Runtime health passed; GitHub Deployment status is pending. "
                    "Retry audit recording without redeploying."
                ) from exc

            record["stage"] = "deployment-recorded"
            record["completed_at"] = datetime.now(UTC).isoformat()
            journal = self._write_journal(record)
            print(
                f"Production promotion succeeded: {tag} at {evidence['commit_sha'][:12]} "
                f"(image {record['deployed_image_id'][:19]}). Private evidence: {journal.name}"
            )

    def retry_audit(self, journal_path: Path) -> None:
        if not WINDOWS_HOST:
            raise RuntimeError("Production audit retry is supported only on the Windows host")
        secure_private_root(self.paths.private_root)
        with exclusive_file_lock(self.lock_file):
            allowed_dir = self.journal_dir.resolve()
            resolved_path = journal_path.resolve()
            try:
                resolved_path.relative_to(allowed_dir)
            except ValueError as exc:
                raise ValueError(
                    "Audit retry record must be inside private deployment storage"
                ) from exc
            record = json.loads(resolved_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not isinstance(record.get("deployment_id"), int):
                raise ValueError("Private deployment record is invalid")
            head_sha = _run(
                ["git", "-C", str(self.paths.checkout), "rev-parse", "HEAD"]
            ).stdout.strip()
            branch_name = _run(
                ["git", "-C", str(self.paths.checkout), "branch", "--show-current"]
            ).stdout.strip()
            clean = not bool(
                _run(
                    ["git", "-C", str(self.paths.checkout), "status", "--porcelain"]
                ).stdout.strip()
            )
            validate_checkout_state(
                checkout_root=str(self.paths.checkout),
                expected_root=str(self.paths.stable_checkout),
                head_sha=head_sha,
                expected_sha=str(record.get("commit_sha", "")),
                branch_name=branch_name,
                clean=clean,
            )
            _run(
                [
                    str(self.paths.checkout / "scripts" / "runtime_state.bat"),
                    "--require-runtime-current",
                ],
                cwd=self.paths.checkout,
                timeout=60,
            )
            health = _read_health()
            image_id = _run(
                [str(self.paths.docker_exe), "inspect", "--format", "{{.Image}}", CONTAINER]
            ).stdout.strip()
            deployment_id = record["deployment_id"]
            deployment = self._api(f"repos/{self.repository}/deployments/{deployment_id}")
            if not isinstance(deployment, dict):
                raise ValueError("GitHub production Deployment record is unavailable")
            validate_audit_retry_evidence(
                record,
                deployment,
                running_version=health["app_version"],
                running_image_id=image_id,
            )
            statuses = self._api(
                f"repos/{self.repository}/deployments/{deployment_id}/statuses?per_page=100"
            )
            if isinstance(statuses, list) and statuses and statuses[0].get("state") == "success":
                record["stage"] = "deployment-recorded"
                record["completed_at"] = datetime.now(UTC).isoformat()
                self._write_journal(record)
                print(
                    "GitHub production status was already successful; local journal is synchronized."
                )
                return
            self._set_deployment_status(
                deployment_id,
                state="success",
                description=(f"src {record['commit_sha']} image {record['deployed_image_id']}"),
                log_url=str(record["approval_run_url"]),
            )
            record["stage"] = "deployment-recorded"
            record["completed_at"] = datetime.now(UTC).isoformat()
            self._write_journal(record)
            print("GitHub deployment audit recorded; no database or Docker changes were made.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and manually promote an approved release to the local Windows production host."
    )
    parser.add_argument("--tag", help="Published release tag, for example v1.4.25")
    authorization = parser.add_mutually_exclusive_group()
    authorization.add_argument(
        "--approval-run-id", type=int, help="Successful protected release approval workflow run ID"
    )
    authorization.add_argument(
        "--plan-id", help="Active, verified production plan authorization ID"
    )
    parser.add_argument(
        "--allow-source-rebuilt-fallback",
        action="store_true",
        help="Use the owner-approved, privately evidenced v1.4.31 source rebuild if the exact prior image is unavailable.",
    )
    parser.add_argument(
        "--capture-compose-contract",
        action="store_true",
        help="Capture the current resolved Compose configuration before changing its build context.",
    )
    parser.add_argument(
        "--confirm-current-mounts",
        action="store_true",
        help="Confirm that the current database and host mounts are the intended production mounts.",
    )
    parser.add_argument(
        "--retry-audit-record",
        type=Path,
        help="Retry only the GitHub status for a verified local audit-pending journal.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checkout = Path(__file__).resolve().parents[1]
    paths = PromotionPaths.current_host(checkout)
    manager = PromotionManager(paths)
    try:
        if args.capture_compose_contract:
            if (
                not args.confirm_current_mounts
                or args.tag
                or args.approval_run_id
                or args.plan_id
                or args.retry_audit_record
            ):
                raise ValueError(
                    "Contract capture requires --confirm-current-mounts and cannot be combined with a release."
                )
            secure_private_root(paths.private_root)
            with exclusive_file_lock(manager.lock_file):
                manager.capture_compose_contract()
            return 0
        if args.retry_audit_record:
            if args.tag or args.approval_run_id or args.plan_id or args.confirm_current_mounts:
                raise ValueError(
                    "Audit-only retry cannot be combined with release or capture arguments."
                )
            manager.retry_audit(args.retry_audit_record)
            return 0
        if (
            args.confirm_current_mounts
            or not args.tag
            or (args.approval_run_id is None and args.plan_id is None)
        ):
            raise ValueError(
                "Promotion requires --tag and exactly one approval mode; use --confirm-current-mounts only for contract capture."
            )
        manager.promote(
            args.tag,
            args.approval_run_id,
            plan_id=args.plan_id,
            allow_source_rebuilt_fallback=args.allow_source_rebuilt_fallback,
        )
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Production promotion stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

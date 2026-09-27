"""Operator-only production promotion entry point for the Windows host."""

from __future__ import annotations

import argparse
import csv
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
from scripts.production_promotion import (
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


def _run_finalizer(command: list[str], cwd: Path, log: Any, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
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
        raise RuntimeError(f"Backend finalizer timed out after {timeout} seconds; process tree terminated") from exc
    return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")


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
            raise RuntimeError("Compose contract capture is supported only on the production Windows host")
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
        if not isinstance(database_source, str) or not (Path(database_source) / "qb_rules.db").is_file():
            raise RuntimeError("Current production SQLite database is missing from the /app/data mount")

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
        print("Captured the private Compose contract; no database, Compose, or container was changed.")

    def _validate_approval(self, tag: str, run_id: int) -> tuple[dict[str, Any], str, dict[str, Any]]:
        if not tag.startswith("v"):
            raise ValueError("Promotion requires a vMAJOR.MINOR.PATCH release tag")
        parse_release_version(tag)
        environment = self._api(
            f"repos/{self.repository}/environments/{APPROVAL_ENVIRONMENT}"
        )
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
                    later_jobs_data.get("jobs", [])
                    if isinstance(later_jobs_data, dict)
                    else []
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

    def preflight(self, tag: str, approval_run_id: int) -> dict[str, Any]:
        manifest, current_main_sha, approval_run = self._validate_approval(tag, approval_run_id)
        commit_sha, release_url, ci_run, api_run = validate_release(tag, self.repository)
        if commit_sha != manifest.get("commit_sha"):
            raise ValueError("Approval manifest source SHA no longer matches the published release tag")
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
            "approval_run_id": approval_run_id,
            "approval_run_url": approval_run.get("html_url"),
            "ci_run_id": ci_run["databaseId"],
            "ci_run_url": ci_run["url"],
            "api_run_id": api_run["databaseId"],
            "api_run_url": api_run["url"],
            "database_path": str(database_path),
            "previous_image_id": image_id,
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

    def promote(self, tag: str, approval_run_id: int) -> None:
        if not WINDOWS_HOST:
            raise RuntimeError("Production promotion is supported only on the Windows host")
        secure_private_root(self.paths.private_root)
        with exclusive_file_lock(self.lock_file):
            evidence = self.preflight(tag, approval_run_id)
            deployment_id = self._create_deployment(evidence)
            record: dict[str, Any] = {
                **evidence,
                "deployment_id": deployment_id,
                "stage": "deployment-created",
                "started_at": datetime.now(UTC).isoformat(),
                "private_backup_path": "",
                "backup_sha256": "",
                "previous_image_rollback_tag": "",
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
                    print("GitHub failure status is pending; the private deployment journal could not be created.")
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

                rollback_tag = (
                    f"qbittorrent-rss-rule-manager:rollback-{timestamp.replace('T', '-').replace('Z', '')}"
                )
                _run(
                    [str(self.paths.docker_exe), "image", "tag", evidence["previous_image_id"], rollback_tag]
                )
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
                if retained_image_id != evidence["previous_image_id"]:
                    raise RuntimeError("Previous production image was not retained by immutable ID")
                record["previous_image_rollback_tag"] = rollback_tag
                record["stage"] = "finalizer-running"
                self._write_journal(record)

                log_path = self.paths.private_root / "logs" / f"{tag}-{deployment_id}-finalizer.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                finalizer = self.paths.checkout / "Finalize-Backend.cmd"
                command = f'""{finalizer}" --no-pause"'
                with log_path.open("w", encoding="utf-8", newline="\n") as log:
                    finalizer_result = _run_finalizer(
                        ["cmd.exe", "/d", "/s", "/c", command], self.paths.checkout, log
                    )
                record["finalizer_exit_code"] = finalizer_result.returncode
                record["finalizer_log_path"] = str(log_path)
                if finalizer_result.returncode != 0:
                    raise RuntimeError(
                        f"Backend finalizer failed with exit code {finalizer_result.returncode}"
                    )

                health = _read_health()
                if health["app_version"] != evidence["target_version"]:
                    raise RuntimeError("Production health version does not equal the approved release")
                runtime_log = self.paths.private_root / "logs" / f"{tag}-{deployment_id}-runtime.log"
                with runtime_log.open("w", encoding="utf-8", newline="\n") as log:
                    runtime_result = subprocess.run(
                        [str(self.paths.checkout / "scripts" / "runtime_state.bat"), "--require-runtime-current"],
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
                    raise RuntimeError("Deployed production container has no immutable image identity")
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
                    print("Private failure journal update failed; GitHub failure status will still be attempted.")
                try:
                    self._set_deployment_status(
                        deployment_id,
                        state="failure",
                        description=f"Promotion failed for {tag}; inspect the operator-local record",
                        log_url=evidence["approval_run_url"],
                    )
                except Exception:
                    print("GitHub failure status is pending; operator-local journal records the failure.")
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
                raise ValueError("Audit retry record must be inside private deployment storage") from exc
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
                _run(["git", "-C", str(self.paths.checkout), "status", "--porcelain"]).stdout.strip()
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
            deployment = self._api(
                f"repos/{self.repository}/deployments/{deployment_id}"
            )
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
                print("GitHub production status was already successful; local journal is synchronized.")
                return
            self._set_deployment_status(
                deployment_id,
                state="success",
                description=(
                    f"src {record['commit_sha']} image {record['deployed_image_id']}"
                ),
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
    parser.add_argument("--approval-run-id", type=int, help="Successful protected approval workflow run ID")
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
            if args.tag or args.approval_run_id or args.confirm_current_mounts:
                raise ValueError("Audit-only retry cannot be combined with release or capture arguments.")
            manager.retry_audit(args.retry_audit_record)
            return 0
        if args.confirm_current_mounts or not args.tag or not args.approval_run_id:
            raise ValueError(
                "Promotion requires --tag and --approval-run-id; use --confirm-current-mounts only for contract capture."
            )
        manager.promote(args.tag, args.approval_run_id)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Production promotion stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

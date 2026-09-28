from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "DockerLifecycleAudit.psm1"


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is available only on the Windows validation runner")
    return executable


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def test_lifecycle_audit_appends_redacted_intent_and_outcome_records(tmp_path: Path) -> None:
    powershell = _powershell()
    audit_path = tmp_path / "docker-starts.jsonl"
    module_path = _ps_literal(str(MODULE))
    audit_literal = _ps_literal(str(audit_path))
    command = f"""
$ErrorActionPreference = 'Stop'
Import-Module {module_path} -Force
$before = [pscustomobject]@{{ QuerySucceeded = $true; ContainerCount = 1; ContainerId = ('a' * 64); ImageId = 'sha256:' + ('1' * 64); State = 'exited'; Health = 'none'; Service = 'qb-rss-rules' }}
$after = [pscustomobject]@{{ QuerySucceeded = $true; ContainerCount = 1; ContainerId = ('b' * 64); ImageId = 'sha256:' + ('2' * 64); State = 'running'; Health = 'healthy'; Service = 'qb-rss-rules' }}
Write-DockerLifecycleAuditRecord -AuditPath {audit_literal} -RunId 'run-123' -AttemptId 'attempt-1' -Attempt 1 -Event 'compose_up_intent' -Service 'qb-rss-rules' -CheckoutSha 'abc1234' -Operation 'compose_up' -BeforeSnapshot $before
Write-DockerLifecycleAuditRecord -AuditPath {audit_literal} -RunId 'run-123' -AttemptId 'attempt-1' -Attempt 1 -Event 'compose_up_result' -Service 'qb-rss-rules' -CheckoutSha 'abc1234' -Operation 'compose_up' -BeforeSnapshot $before -AfterSnapshot $after -ComposeExitCode 7 -IdentityChanged $true -ExpectedServiceProvenRunning $false
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert [record["event"] for record in records] == [
        "compose_up_intent",
        "compose_up_result",
    ]
    assert all(record["run_id"] == "run-123" for record in records)
    assert all(record["attempt_id"] == "attempt-1" for record in records)
    assert all(record["service"] == "qb-rss-rules" for record in records)
    assert all(record["checkout_sha"] == "abc1234" for record in records)
    assert all(record["operation"] == "compose_up" for record in records)
    assert records[1]["compose_exit_code"] == 7
    assert all(record["attempt"] == 1 for record in records)
    assert records[0]["before"]["container_id"] == "a" * 64
    assert records[0]["after"] is None
    assert records[1]["before"]["image_id"] == "sha256:" + "1" * 64
    assert records[1]["after"]["container_id"] == "b" * 64
    assert records[1]["after"]["state"] == "running"
    assert records[1]["identity_changed"] is True
    assert records[1]["expected_service_proven_running"] is False
    assert all(
        set(record)
        == {
            "timestamp_utc",
            "run_id",
            "attempt",
            "attempt_id",
            "event",
            "service",
            "checkout_sha",
            "operation",
            "compose_exit_code",
            "before",
            "after",
            "identity_changed",
            "expected_service_proven_running",
        }
        for record in records
    )


def test_updater_records_intent_before_and_result_after_compose_up() -> None:
    script = (ROOT / "scripts" / "update_docker.ps1").read_text(encoding="utf-8")
    intent = script.index("-Event \"compose_up_intent\"")
    compose = script.index("$composeExit = Invoke-DockerLogged -DockerArguments $upArgs")
    outcome = script.index("-Event \"compose_up_result\"")
    assert intent < compose < outcome
    assert script.count("$lifecycleRunId = [Guid]::NewGuid()") == 1
    assert script.count("$lifecycleAttemptId = [Guid]::NewGuid()") == 2
    proof_gate = script.index("if (-not $startProven)")
    proof_failure = script.index("target service '$Service' could not be proven present and running")
    health_wait = script.index('Write-Host "Waiting for backend health..."')
    assert outcome < proof_gate < proof_failure < health_wait


def test_lifecycle_audit_captures_container_identity_and_correlates_retries(
    tmp_path: Path,
) -> None:
    powershell = _powershell()
    audit_path = _ps_literal(str(tmp_path / "docker-starts.jsonl"))
    module_path = _ps_literal(str(MODULE))
    command = f"""
$ErrorActionPreference = 'Stop'
Import-Module {module_path} -Force
$script:SnapshotIndex = 0
$script:SensitiveSentinel = 'private-url=https://internal.invalid;Authorization=Bearer do-not-log'
$script:MockTargets = @(
    @{{ Id = ('a' * 64); Image = ('1' * 64); State = 'exited'; Health = 'none'; Service = 'qb-rss-rules' }},
    @{{ Id = ('b' * 64); Image = ('2' * 64); State = 'running'; Health = 'healthy'; Service = 'qb-rss-rules' }},
    @{{ Id = ('b' * 64); Image = ('2' * 64); State = 'running'; Health = 'healthy'; Service = 'qb-rss-rules' }},
    @{{ Id = ('c' * 64); Image = ('3' * 64); State = 'running'; Health = 'healthy'; Service = 'qb-rss-rules' }}
)
function Invoke-MockedDocker {{
    param([string[]]$DockerArguments, [string]$OutputMode)
    if ($DockerArguments[0] -eq 'compose') {{
        $target = $script:MockTargets[$script:SnapshotIndex]
        $script:SnapshotIndex++
        return [pscustomobject]@{{ ExitCode = 0; StdOut = @($target.Id, $script:SensitiveSentinel) }}
    }}
    if ($DockerArguments[0] -eq 'inspect') {{
        $target = $script:MockTargets[$script:SnapshotIndex - 1]
        $summary = '{{0}}|sha256:{{1}}|{{2}}|{{3}}|{{4}}' -f $target.Id, $target.Image, $target.State, $target.Health, $target.Service
        return [pscustomobject]@{{ ExitCode = 0; StdOut = @($summary) }}
    }}
    throw 'Unexpected mocked Docker command.'
}}
$dockerInvoker = {{ param($DockerArguments, $OutputMode) Invoke-MockedDocker -DockerArguments $DockerArguments -OutputMode $OutputMode }}
$before1 = Get-DockerLifecycleTargetSnapshot -ComposeArguments @('compose') -Service 'qb-rss-rules' -DockerInvoker $dockerInvoker
$after1 = Get-DockerLifecycleTargetSnapshot -ComposeArguments @('compose') -Service 'qb-rss-rules' -DockerInvoker $dockerInvoker
$proven1 = Test-DockerLifecycleProvenRunning -Snapshot $after1 -Service 'qb-rss-rules' -ComposeExitCode 0
$changed1 = $before1.ContainerId -ne $after1.ContainerId
Write-DockerLifecycleAuditRecord -AuditPath {audit_path} -RunId 'run-123' -AttemptId 'attempt-1' -Attempt 1 -Event 'compose_up_intent' -Service 'qb-rss-rules' -CheckoutSha 'sha-main' -Operation 'compose_up' -BeforeSnapshot $before1
Write-DockerLifecycleAuditRecord -AuditPath {audit_path} -RunId 'run-123' -AttemptId 'attempt-1' -Attempt 1 -Event 'compose_up_result' -Service 'qb-rss-rules' -CheckoutSha 'sha-main' -Operation 'compose_up' -BeforeSnapshot $before1 -AfterSnapshot $after1 -ComposeExitCode 1 -IdentityChanged $changed1 -ExpectedServiceProvenRunning $false
$before2 = Get-DockerLifecycleTargetSnapshot -ComposeArguments @('compose') -Service 'qb-rss-rules' -DockerInvoker $dockerInvoker
$after2 = Get-DockerLifecycleTargetSnapshot -ComposeArguments @('compose') -Service 'qb-rss-rules' -DockerInvoker $dockerInvoker
$proven2 = Test-DockerLifecycleProvenRunning -Snapshot $after2 -Service 'qb-rss-rules' -ComposeExitCode 0
$changed2 = $before2.ContainerId -ne $after2.ContainerId
Write-DockerLifecycleAuditRecord -AuditPath {audit_path} -RunId 'run-123' -AttemptId 'attempt-2' -Attempt 2 -Event 'compose_up_intent' -Service 'qb-rss-rules' -CheckoutSha 'sha-main' -Operation 'compose_up' -BeforeSnapshot $before2
Write-DockerLifecycleAuditRecord -AuditPath {audit_path} -RunId 'run-123' -AttemptId 'attempt-2' -Attempt 2 -Event 'compose_up_result' -Service 'qb-rss-rules' -CheckoutSha 'sha-main' -Operation 'compose_up' -BeforeSnapshot $before2 -AfterSnapshot $after2 -ComposeExitCode 0 -IdentityChanged $changed2 -ExpectedServiceProvenRunning $proven2
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (tmp_path / "docker-starts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["attempt"] for record in records] == [1, 1, 2, 2]
    assert {record["run_id"] for record in records} == {"run-123"}
    assert [record["attempt_id"] for record in records] == ["attempt-1", "attempt-1", "attempt-2", "attempt-2"]
    first_result = records[1]
    second_result = records[3]
    assert first_result["before"]["container_id"] == "a" * 64
    assert first_result["before"]["image_id"] == "sha256:" + "1" * 64
    assert first_result["before"]["state"] == "exited"
    assert first_result["after"]["container_id"] == "b" * 64
    assert first_result["identity_changed"] is True
    assert first_result["expected_service_proven_running"] is False
    assert second_result["before"]["container_id"] == "b" * 64
    assert second_result["after"]["container_id"] == "c" * 64
    assert second_result["after"]["image_id"] == "sha256:" + "3" * 64
    assert second_result["after"]["state"] == "running"
    assert second_result["after"]["health"] == "healthy"
    assert second_result["identity_changed"] is True
    assert second_result["expected_service_proven_running"] is True
    assert all(record["timestamp_utc"].endswith("Z") for record in records)
    assert all(record["service"] == "qb-rss-rules" for record in records)
    assert all(record["checkout_sha"] == "sha-main" for record in records)
    assert all(record["operation"] == "compose_up" for record in records)
    assert all("authorization" not in json.dumps(record).casefold() for record in records)
    assert all("do-not-log" not in json.dumps(record) for record in records)
    assert all("command" not in record and "environment" not in record for record in records)


def test_successful_compose_exit_without_running_target_is_not_proven() -> None:
    powershell = _powershell()
    module_path = _ps_literal(str(MODULE))
    command = f"""
$ErrorActionPreference = 'Stop'
Import-Module {module_path} -Force
$missing = [pscustomobject]@{{ QuerySucceeded = $true; ContainerCount = 0; ContainerId = $null; ImageId = $null; State = $null; Health = $null; Service = $null }}
$stopped = [pscustomobject]@{{ QuerySucceeded = $true; ContainerCount = 1; ContainerId = ('a' * 64); ImageId = 'sha256:' + ('1' * 64); State = 'exited'; Health = 'none'; Service = 'qb-rss-rules' }}
$wrongService = [pscustomobject]@{{ QuerySucceeded = $true; ContainerCount = 1; ContainerId = ('b' * 64); ImageId = 'sha256:' + ('2' * 64); State = 'running'; Health = 'healthy'; Service = 'other-service' }}
if (Test-DockerLifecycleProvenRunning -Snapshot $missing -Service 'qb-rss-rules' -ComposeExitCode 0) {{ throw 'A missing container was falsely proven running.' }}
if (Test-DockerLifecycleProvenRunning -Snapshot $stopped -Service 'qb-rss-rules' -ComposeExitCode 0) {{ throw 'An exited container was falsely proven running.' }}
if (Test-DockerLifecycleProvenRunning -Snapshot $wrongService -Service 'qb-rss-rules' -ComposeExitCode 0) {{ throw 'A different service was falsely proven running.' }}
if (Test-DockerLifecycleProvenRunning -Snapshot $stopped -Service 'qb-rss-rules' -ComposeExitCode 7) {{ throw 'A failed Compose attempt was falsely proven running.' }}
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr

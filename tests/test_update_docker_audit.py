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
Write-DockerLifecycleAuditRecord -AuditPath {audit_literal} -RunId 'run-123' -Attempt 1 -Event 'compose_up_intent' -Service 'qb-rss-rules' -Commit 'abc1234'
Write-DockerLifecycleAuditRecord -AuditPath {audit_literal} -RunId 'run-123' -Attempt 1 -Event 'compose_up_result' -Service 'qb-rss-rules' -Commit 'abc1234' -ExitCode 7
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
    assert all(record["service"] == "qb-rss-rules" for record in records)
    assert all(record["commit"] == "abc1234" for record in records)
    assert records[1]["exit_code"] == 7
    assert all(record["attempt"] == 1 for record in records)
    assert all(set(record) == {"timestamp_utc", "run_id", "attempt", "event", "service", "commit", "exit_code"} for record in records)


def test_updater_records_intent_before_and_result_after_compose_up() -> None:
    script = (ROOT / "scripts" / "update_docker.ps1").read_text(encoding="utf-8")
    intent = script.index("-Event \"compose_up_intent\"")
    compose = script.index("$composeExit = Invoke-DockerLogged -DockerArguments $upArgs")
    outcome = script.index("-Event \"compose_up_result\"")
    assert intent < compose < outcome

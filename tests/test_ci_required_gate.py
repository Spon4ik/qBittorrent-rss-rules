from __future__ import annotations

import pytest

from scripts.ci_required_gate import REQUIRED_LANES, check_required_lanes, main


def test_required_gate_accepts_all_successful_lanes() -> None:
    results = {lane: "success" for lane in REQUIRED_LANES}

    assert check_required_lanes(results) == []


@pytest.mark.parametrize("failed_result", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize("failed_lane", REQUIRED_LANES)
def test_required_gate_rejects_each_non_success_lane(
    failed_lane: str, failed_result: str
) -> None:
    results = {lane: "success" for lane in REQUIRED_LANES}
    results[failed_lane] = failed_result

    errors = check_required_lanes(results)

    assert errors == [f"{failed_lane} must succeed; got {failed_result}"]


def test_required_gate_rejects_missing_lane_result() -> None:
    results = {lane: "success" for lane in REQUIRED_LANES}
    del results["browser-ui"]

    assert check_required_lanes(results) == ["browser-ui must succeed; got missing"]


def test_required_gate_cli_reads_workflow_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_CHECKS_RESULT", "success")
    monkeypatch.setenv("BROWSER_UI_RESULT", "failure")
    monkeypatch.setenv("DESKTOP_BUILD_RESULT", "success")

    assert main() == 1

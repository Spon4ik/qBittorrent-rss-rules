from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import browser_qa  # noqa: E402

WINDOWS_WRAPPER = SCRIPTS_DIR / "browser_qa.bat"
SHELL_WRAPPER = SCRIPTS_DIR / "browser_qa.sh"


def _noop(_runtime: browser_qa.FocusedRuntime) -> None:
    return None


def test_normalize_phase_accepts_human_and_check_prefixes() -> None:
    assert browser_qa.normalize_phase("Phase 44") == "44"
    assert browser_qa.normalize_phase("P44") == "44"
    assert browser_qa.normalize_phase("44") == "44"


def test_current_p44_check_resolves_by_check_or_phase() -> None:
    assert browser_qa.resolve_selection(
        check_ids=["p44-03"], phases=None, specs=browser_qa.CHECK_SPECS
    ) == ["P44-03"]
    assert browser_qa.resolve_selection(
        check_ids=None, phases=["44"], specs=browser_qa.CHECK_SPECS
    ) == ["P44-03"]


def test_selection_expands_dependencies_in_registry_order() -> None:
    specs = {
        "BASE-01": browser_qa.CheckSpec("BASE-01", "1", "base", (), _noop),
        "NEXT-01": browser_qa.CheckSpec("NEXT-01", "2", "next", ("BASE-01",), _noop),
    }

    assert browser_qa.resolve_selection(
        check_ids=["NEXT-01"], phases=None, specs=specs
    ) == ["BASE-01", "NEXT-01"]


def test_legacy_classifier_marks_dependency_cascades_blocked() -> None:
    compact = browser_qa.classify_legacy_report(
        {
            "generated_at": "2026-08-20T20:00:00Z",
            "checks": [
                {"check_id": "P6-05", "status": "fail", "detail": "missing action"},
                {"check_id": "P7-10", "status": "fail", "detail": "missing context"},
            ],
        }
    )
    by_id = {item["check_id"]: item for item in compact["checks"]}

    assert by_id["P6-05"]["status"] == "quarantined"
    assert by_id["P7-10"]["status"] == "blocked"
    assert "P6-05" in by_id["P7-10"]["detail"]
    assert compact["counts"]["blocked"] == 1
    assert compact["counts"]["quarantined"] == 1


def test_legacy_classifier_quarantines_only_known_stale_contracts() -> None:
    compact = browser_qa.classify_legacy_report(
        {
            "checks": [
                {"check_id": "P4-01", "status": "fail", "detail": "hidden"},
                {"check_id": "P6-02", "status": "fail", "detail": "zero results"},
                {"check_id": "P6-03", "status": "pass", "detail": "OK"},
            ]
        }
    )
    by_id = {item["check_id"]: item for item in compact["checks"]}

    assert by_id["P4-01"]["status"] == "quarantined"
    assert by_id["P6-02"]["status"] == "fail"
    assert by_id["P6-03"]["status"] == "pass"
    assert compact["counts"] == {
        "total": 3,
        "passed": 1,
        "failed": 1,
        "blocked": 0,
        "quarantined": 1,
    }


def test_p5_media_failure_is_blocked_when_p9_setup_failed() -> None:
    compact = browser_qa.classify_legacy_report(
        {
            "checks": [
                {"check_id": "P9-01", "status": "fail", "detail": "setup failed"},
                {"check_id": "P5-01", "status": "fail", "detail": "wrong page"},
            ]
        }
    )
    by_id = {item["check_id"]: item for item in compact["checks"]}

    assert by_id["P9-01"]["status"] == "fail"
    assert by_id["P5-01"]["status"] == "blocked"


def test_browser_qa_wrappers_prefer_repo_virtualenv() -> None:
    windows = WINDOWS_WRAPPER.read_text(encoding="utf-8")
    shell = SHELL_WRAPPER.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\python.exe" in windows
    assert "scripts\\browser_qa.py" in windows
    assert ".venv/bin/python" in shell
    assert "scripts/browser_qa.py" in shell

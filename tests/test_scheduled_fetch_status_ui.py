from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIAGNOSTICS = ROOT / "app" / "services" / "runtime_diagnostics.py"
RUNTIME_HEALTH_JS = ROOT / "app" / "static" / "runtime_health.js"


def test_runtime_diagnostics_exposes_current_scheduled_fetch_state() -> None:
    source = RUNTIME_DIAGNOSTICS.read_text(encoding="utf-8")

    assert "current_scheduled_fetch_state" in source
    assert '"scheduled_fetch_current_state"' in source
    assert '"current_state": current_state' in source


def test_rules_status_ui_leads_with_current_health_and_keeps_history_secondary() -> None:
    source = RUNTIME_HEALTH_JS.read_text(encoding="utf-8")

    assert "Current status: ${status}." in source
    assert "Previous scheduled run: ${historicalStatus} (historical)." in source
    assert "component?.current_state" in source
    assert "currentState.historical_failure_superseded" in source
    assert "Previous run detail:" not in source

from __future__ import annotations

from datetime import UTC, datetime

from app.services.functional_invariants import evaluate_unhandled_api_errors

NOW = datetime(2026, 8, 21, 19, 0, tzinfo=UTC)


def test_f03_skips_runtime_that_predates_api_error_telemetry() -> None:
    result = evaluate_unhandled_api_errors({"components": {}}, NOW)

    assert result.status == "skip"
    assert result.metrics["telemetry_supported"] is False


def test_f03_fails_when_runtime_advertises_telemetry_but_omits_component() -> None:
    result = evaluate_unhandled_api_errors(
        {
            "diagnostic_capabilities": ["unhandled_api_error_telemetry"],
            "components": {},
        },
        NOW,
    )

    assert result.status == "fail"
    assert result.metrics["telemetry_supported"] is True


def test_f03_passes_when_current_runtime_has_no_unhandled_api_errors() -> None:
    result = evaluate_unhandled_api_errors(
        {
            "diagnostic_capabilities": ["unhandled_api_error_telemetry"],
            "components": {
                "api": {
                    "unhandled_errors": {
                        "count": 0,
                        "last": None,
                    }
                }
            },
        },
        NOW,
    )

    assert result.status == "pass"
    assert result.metrics["unhandled_error_count"] == 0


def test_f03_reports_latest_unhandled_api_error_without_secret_detail() -> None:
    result = evaluate_unhandled_api_errors(
        {
            "diagnostic_capabilities": ["unhandled_api_error_telemetry"],
            "components": {
                "api": {
                    "unhandled_errors": {
                        "count": 1,
                        "last": {
                            "id": "api-123",
                            "occurred_at": "2026-08-21T18:59:00+00:00",
                            "method": "POST",
                            "path": "/api/rules/fetch",
                            "error_type": "JSONDecodeError",
                        },
                    }
                }
            },
        },
        NOW,
    )

    assert result.status == "fail"
    assert "POST /api/rules/fetch" in result.summary
    assert "JSONDecodeError" in result.summary
    assert "api-123" in result.summary

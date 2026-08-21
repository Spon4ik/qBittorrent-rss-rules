from __future__ import annotations


def test_unhandled_api_exception_returns_bounded_json_and_records_diagnostics(app_client) -> None:
    private_detail = "provider-secret-detail-must-not-leak"

    def raise_unhandled_error() -> None:
        raise RuntimeError(private_detail)

    app_client.app.add_api_route(
        "/api/__test__/unhandled-error",
        raise_unhandled_error,
        methods=["GET"],
    )

    response = app_client.get("/api/__test__/unhandled-error")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_id"].startswith("api-")
    assert payload["error_id"] in payload["error"]
    assert private_detail not in response.text

    diagnostics_response = app_client.get("/api/diagnostics/runtime")

    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    error_status = diagnostics["components"]["api"]["unhandled_errors"]
    assert error_status["count"] == 1
    assert error_status["last"] == {
        "id": payload["error_id"],
        "occurred_at": error_status["last"]["occurred_at"],
        "method": "GET",
        "path": "/api/__test__/unhandled-error",
        "error_type": "RuntimeError",
    }
    assert diagnostics["invariants"]["F-03"]["status"] == "fail"
    assert diagnostics["invariants"]["F-03"]["metrics"]["last_error_id"] == payload["error_id"]

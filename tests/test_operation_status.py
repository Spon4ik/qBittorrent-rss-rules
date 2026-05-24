from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import operation_status


def setup_function() -> None:
    operation_status.reset_operations_for_tests()


def test_operation_registry_tracks_active_and_completed_progress() -> None:
    operation = operation_status.start_operation(
        operation_type="jackett_fetch",
        label="Fetching releases",
        total=4,
    )

    operation_status.update_operation(
        operation.operation_id,
        current=2,
        message="Fetched 2 of 4 rules.",
    )
    active_payload = operation_status.operations_status_payload()

    assert active_payload["summary"]["is_running"] is True
    assert active_payload["summary"]["current"] == 2
    assert active_payload["summary"]["total"] == 4
    assert active_payload["summary"]["percent"] == 50
    assert active_payload["operations"][0]["status"] == "running"
    assert active_payload["operations"][0]["message"] == "Fetched 2 of 4 rules."

    operation_status.complete_operation(operation.operation_id, message="Fetch complete.")
    completed_payload = operation_status.operations_status_payload()

    assert completed_payload["summary"]["is_running"] is False
    assert completed_payload["summary"]["percent"] == 100
    assert completed_payload["operations"][0]["status"] == "success"
    assert completed_payload["operations"][0]["message"] == "Fetch complete."


def test_operation_registry_keeps_unknown_total_separate_from_percent() -> None:
    operation_status.start_operation(
        operation_type="stremio_sync",
        label="Syncing Stremio",
    )

    payload = operation_status.operations_status_payload()

    assert payload["summary"]["is_running"] is True
    assert payload["summary"]["current"] == 0
    assert payload["summary"]["total"] == 0
    assert payload["summary"]["percent"] is None
    assert payload["operations"][0]["percent"] is None


def test_operation_registry_prunes_recent_completed_operations() -> None:
    operation = operation_status.start_operation(
        operation_type="qb_sync",
        label="Syncing qB",
        total=1,
    )
    operation_status.complete_operation(operation.operation_id, message="Done.")
    stale_completed_at = datetime.now(UTC) - timedelta(minutes=10)

    operation_status.update_operation_for_tests(
        operation.operation_id,
        completed_at=stale_completed_at,
        updated_at=stale_completed_at,
    )
    payload = operation_status.operations_status_payload(recent_seconds=60)

    assert payload["operations"] == []
    assert payload["summary"]["operation_count"] == 0


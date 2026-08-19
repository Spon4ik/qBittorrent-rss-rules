from __future__ import annotations

import json
from types import SimpleNamespace

from app.services import codex_maintenance


def test_acceleration_maintenance_request_declares_incident_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(codex_maintenance, "REQUEST_DIR", tmp_path / "requests")
    job = SimpleNamespace(
        id="job-1",
        info_hash="a" * 40,
        provider_download_id=None,
        state="retry_wait",
        torrent_name="Example torrent",
        rule_id=None,
        last_error="provider failed",
    )

    payload = codex_maintenance.queue_acceleration_maintenance_request(job, rule=None)

    assert payload["mode"] == "incident"
    assert payload["route"] == "incident_lead"
    assert str(payload["instruction"]).startswith("MODE: INCIDENT.")
    assert "`incident_lead`" in str(payload["instruction"])

    request_path = next((tmp_path / "requests").glob("*.json"))
    persisted = json.loads(request_path.read_text(encoding="utf-8"))
    assert persisted["mode"] == "incident"
    assert persisted["route"] == "incident_lead"

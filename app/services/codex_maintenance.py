from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

from app.config import DATA_DIR
from app.models import DownloadAccelerationJob, Rule
from app.services.log_redaction import redact_sensitive_text

REQUEST_DIR = DATA_DIR / "codex-maintenance-requests"


def maintenance_status_by_job() -> dict[str, dict[str, object]]:
    statuses: dict[str, dict[str, object]] = {}
    if not REQUEST_DIR.exists():
        return statuses
    for request_path in REQUEST_DIR.glob("*.json"):
        try:
            payload = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        job_id = str(payload.get("job_id") or "")
        if not job_id:
            continue
        current = statuses.get(job_id)
        if current is None or str(payload.get("updated_at") or "") > str(
            current.get("updated_at") or ""
        ):
            statuses[job_id] = payload
    return statuses


def queue_acceleration_maintenance_request(
    job: DownloadAccelerationJob,
    *,
    rule: Rule | None,
) -> dict[str, object]:
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    for existing_path in REQUEST_DIR.glob("*.json"):
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(existing, dict):
            continue
        if (
            str(existing.get("job_id") or "") == job.id
            and str(existing.get("status") or "") in {"pending", "running"}
        ):
            return dict(existing)

    request_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "id": request_id,
        "status": "pending",
        "mode": "incident",
        "route": "incident_lead",
        "kind": "real_debrid_acceleration",
        "created_at": created_at,
        "updated_at": created_at,
        "job_id": job.id,
        "job_reference": str(job.info_hash or job.provider_download_id or job.id)[:12],
        "job_state": job.state,
        "torrent_name": job.torrent_name,
        "rule_id": rule.id if rule else job.rule_id,
        "rule_name": rule.rule_name if rule else None,
        "error": redact_sensitive_text(job.last_error),
        "instruction": (
            "MODE: INCIDENT. Read AGENTS.md first. This request is already classified; "
            "route it to `incident_lead` and pass this structured payload unchanged as the "
            "incident evidence. Use deterministic evidence first. Diagnose and fix routine/local "
            "causes safely. Escalate to `deep_debugger` only through a compact escalation packet "
            "when material unresolved causal ambiguity remains. Validate the affected runtime/UI, "
            "then update this request with status and result."
        ),
    }
    target = REQUEST_DIR / f"{request_id}.json"
    temporary = REQUEST_DIR / f".{request_id}.tmp"
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return payload

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.services.functional_invariants import CHECKS
from app.services.functional_watchdog import functional_watchdog_status
from app.services.runtime_diagnostics import runtime_diagnostics_payload

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/runtime")
def runtime_diagnostics(session: Session = Depends(get_db_session)) -> JSONResponse:
    payload = runtime_diagnostics_payload(session)
    observed_at = datetime.now(UTC)
    payload["invariants"] = {
        check_id: asdict(spec.evaluator(payload, observed_at))
        for check_id, spec in CHECKS.items()
    }
    payload["functional_watchdog"] = functional_watchdog_status()
    return JSONResponse(payload)

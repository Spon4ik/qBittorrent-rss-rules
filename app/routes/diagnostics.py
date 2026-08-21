from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.services.runtime_diagnostics import runtime_diagnostics_payload

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/runtime")
def runtime_diagnostics(session: Session = Depends(get_db_session)) -> JSONResponse:
    return JSONResponse(runtime_diagnostics_payload(session))

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

RUNTIME_INSTANCE_ID = uuid4().hex
RUNTIME_STARTED_AT = datetime.now(UTC)


def runtime_identity_payload() -> dict[str, str]:
    return {
        "instance_id": RUNTIME_INSTANCE_ID,
        "started_at": RUNTIME_STARTED_AT.isoformat(),
    }

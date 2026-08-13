from __future__ import annotations

import logging
import re

WEBSEED_TOKEN_RE = re.compile(r"(/webseeds/real-debrid/)[^/?\s]+")
QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:apikey|api_key|token|access_token|auth)=)[^&\s]+"
)


def redact_sensitive_text(value: str) -> str:
    redacted = WEBSEED_TOKEN_RE.sub(r"\1<redacted>", str(value or ""))
    return QUERY_SECRET_RE.sub(r"\1<redacted>", redacted)


class SensitivePathAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_sensitive_text(value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        return True


def install_sensitive_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, SensitivePathAccessLogFilter) for item in logger.filters):
        return
    logger.addFilter(SensitivePathAccessLogFilter())

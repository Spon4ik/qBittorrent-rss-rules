from __future__ import annotations

import logging

from app.services.log_redaction import SensitivePathAccessLogFilter


def test_uvicorn_access_filter_redacts_webseed_token_but_keeps_path() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1",
            "GET",
            "/webseeds/real-debrid/super-secret-token/folder/file.mkv",
            "1.1",
            206,
        ),
        None,
    )
    assert SensitivePathAccessLogFilter().filter(record) is True
    rendered = record.getMessage()
    assert "super-secret-token" not in rendered
    assert "/webseeds/real-debrid/<redacted>/folder/file.mkv" in rendered

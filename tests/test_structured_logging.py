from __future__ import annotations

import json
import logging

from backend.utils.structured_logging import JsonFormatter


def test_formatter_omits_unstructured_message_text() -> None:
    record = logging.LogRecord(
        "backend.test",
        logging.ERROR,
        "",
        0,
        "private user question and provider secret",
        (),
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "log_record"
    assert "private user question" not in json.dumps(payload)
    assert "provider secret" not in json.dumps(payload)


def test_formatter_includes_only_explicit_safe_metadata() -> None:
    record = logging.LogRecord("backend.api", logging.INFO, "", 0, "ignored", (), None)
    record.event = "http_request_complete"
    record.method = "POST"
    record.path = "/chat"
    record.status_code = 200
    record.duration_ms = 12.5

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "http_request_complete"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.5
    assert "message" not in payload

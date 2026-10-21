from __future__ import annotations

import pytest

from backend.utils.retry import is_quota_exhausted, retry_transient


class HttpError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_retries_503_with_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def request() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise HttpError(503)
        return "ok"

    result = retry_transient(
        request,
        max_attempts=4,
        base_delay=0.5,
        max_delay=2,
        sleep=delays.append,
        random_fn=lambda: 0,
    )()

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_retries_429_then_stops_after_max_attempts() -> None:
    attempts = 0
    delays: list[float] = []

    def request() -> None:
        nonlocal attempts
        attempts += 1
        raise HttpError(429)

    with pytest.raises(HttpError):
        retry_transient(
            request,
            max_attempts=3,
            base_delay=0.2,
            sleep=delays.append,
            random_fn=lambda: 0,
        )()

    assert attempts == 3
    assert delays == [0.2, 0.4]


def test_does_not_retry_non_transient_status() -> None:
    attempts = 0

    def request() -> None:
        nonlocal attempts
        attempts += 1
        raise HttpError(400)

    with pytest.raises(HttpError):
        retry_transient(request, max_attempts=5, sleep=lambda _delay: None)()

    assert attempts == 1


def test_honors_retry_after_header() -> None:
    attempts = 0
    delays: list[float] = []
    response = type("Response", (), {"headers": {"Retry-After": "3"}})()

    def request() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = HttpError(503)
            error.response = response
            raise error
        return "ok"

    assert retry_transient(
        request,
        max_attempts=2,
        base_delay=0.1,
        max_delay=5,
        sleep=delays.append,
        random_fn=lambda: 0,
    )() == "ok"
    assert delays == [3]


def test_does_not_retry_exhausted_provider_quota() -> None:
    attempts = 0
    delays: list[float] = []

    class QuotaError(Exception):
        status_code = 429

    def request() -> None:
        nonlocal attempts
        attempts += 1
        raise QuotaError("429 RESOURCE_EXHAUSTED: exceeded your current quota")

    with pytest.raises(QuotaError):
        retry_transient(
            request,
            max_attempts=4,
            sleep=delays.append,
            random_fn=lambda: 0,
        )()

    assert attempts == 1
    assert delays == []
    assert is_quota_exhausted(QuotaError("RESOURCE_EXHAUSTED"))

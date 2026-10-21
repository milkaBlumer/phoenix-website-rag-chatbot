"""Retry helpers for transient rate-limit and service-unavailable errors."""

from __future__ import annotations

import functools
import os
import random
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from backend.check_setup import read_local_env

P = ParamSpec("P")
R = TypeVar("R")

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0
RETRYABLE_STATUS_CODES = {429, 503}


def _status_code(error: Exception) -> int | None:
    """Extract an HTTP status code from common SDK and HTTP-client exceptions."""
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_quota_exhausted(error: Exception) -> bool:
    """Detect provider quota exhaustion, which will not be fixed by short retries."""
    current: BaseException | None = error
    while current is not None:
        message = str(current).casefold()
        if any(
            marker in message
            for marker in ("resource_exhausted", "exceeded your current quota", "quota exceeded", "insufficient_quota")
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _retry_after(error: Exception) -> float | None:
    """Read a numeric Retry-After hint when available."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("Retry-After") if headers else None
    if value is None:
        value = getattr(error, "retry_after", None)
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def retry_transient(
    function: Callable[P, R] | None = None,
    *,
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    random_fn: Callable[[], float] = random.random,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry only HTTP 429/503 failures using exponential backoff and jitter.

    ``max_attempts`` includes the initial call. Other exceptions and status codes are
    re-raised immediately. ``sleep`` and ``random_fn`` can be injected for tests.
    """
    local_env = read_local_env()
    try:
        max_attempts = max_attempts if max_attempts is not None else int(
            os.environ.get("RETRY_MAX_ATTEMPTS")
            or local_env.get("RETRY_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))
        )
        base_delay = base_delay if base_delay is not None else float(
            os.environ.get("RETRY_BASE_DELAY_SECONDS")
            or local_env.get("RETRY_BASE_DELAY_SECONDS", str(DEFAULT_BASE_DELAY_SECONDS))
        )
        max_delay = max_delay if max_delay is not None else float(
            os.environ.get("RETRY_MAX_DELAY_SECONDS")
            or local_env.get("RETRY_MAX_DELAY_SECONDS", str(DEFAULT_MAX_DELAY_SECONDS))
        )
    except ValueError as error:
        raise ValueError("Retry settings must be valid numbers.") from error
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if base_delay < 0 or max_delay < 0:
        raise ValueError("Retry delays must be non-negative")

    def decorate(target: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(target)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, max_attempts + 1):
                try:
                    return target(*args, **kwargs)
                except Exception as error:
                    if (
                        is_quota_exhausted(error)
                        or _status_code(error) not in RETRYABLE_STATUS_CODES
                        or attempt == max_attempts
                    ):
                        raise
                    exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    retry_after = _retry_after(error)
                    delay = min(max_delay, retry_after) if retry_after is not None else exponential
                    sleep(delay + random_fn() * min(0.25, delay * 0.1))
            raise RuntimeError("Retry loop exited unexpectedly")

        return wrapped

    return decorate(function) if function is not None else decorate

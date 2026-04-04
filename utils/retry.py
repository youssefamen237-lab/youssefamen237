"""
utils/retry.py
==============
Retry decorator with exponential backoff for all external API calls.

Every call that touches a remote service (Gemini, Groq, Tavily,
Pexels, Pixabay, YouTube) should be wrapped with @with_retry so
transient failures (rate limits, 503s, network blips) are handled
automatically without crashing the pipeline.

Usage
-----
    from utils.retry import with_retry

    @with_retry()                         # default settings from settings.py
    def call_gemini(prompt: str) -> dict:
        ...

    @with_retry(max_attempts=5, wait_min=1, wait_max=30)
    def call_youtube_upload(file_path: str) -> str:
        ...

    # Also works as a plain function wrapper (no decorator syntax):
    result = with_retry()(some_function)(arg1, arg2)

Design
------
- Built on Tenacity — battle-tested, supports async, sync, and generators.
- Retries on ANY Exception by default; callers can pass `reraise=True`
  to bubble the final exception after exhausting attempts.
- Logs every retry attempt at WARNING level with the exception message
  so GitHub Actions logs are self-explanatory.
- The `jitter` parameter adds small random noise to wait times, which
  prevents "thundering herd" when multiple pipeline steps hit the same
  API simultaneously.
"""

import functools
import random
from typing import Any, Callable, Optional, Type, Union

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryError,
    TryAgain,
)
import logging

from config.settings import (
    RETRY_MAX_ATTEMPTS,
    RETRY_MULTIPLIER,
    RETRY_WAIT_MAX_SEC,
    RETRY_WAIT_MIN_SEC,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def with_retry(
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    wait_min: float = RETRY_WAIT_MIN_SEC,
    wait_max: float = RETRY_WAIT_MAX_SEC,
    multiplier: float = RETRY_MULTIPLIER,
    jitter: bool = True,
    reraise: bool = True,
    retry_on: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Return a decorator that wraps a function with retry + exponential backoff.

    Parameters
    ----------
    max_attempts : Maximum number of total attempts (1 = no retry).
    wait_min     : Minimum wait between retries in seconds.
    wait_max     : Maximum wait between retries in seconds.
    multiplier   : Backoff multiplier (wait = multiplier * 2^n seconds).
    jitter       : Add ±20 % random jitter to each wait to avoid stampedes.
    reraise      : If True, re-raise the last exception after all attempts
                   are exhausted.  If False, return None on final failure.
    retry_on     : Tuple of exception types that trigger a retry.
                   Defaults to (Exception,) — retry on anything.

    Returns
    -------
    A decorator that can be applied to any callable.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0

            while True:
                attempt += 1
                try:
                    return func(*args, **kwargs)

                except retry_on as exc:
                    if attempt >= max_attempts:
                        logger.error(
                            "[retry] %s — all %d attempts exhausted. "
                            "Final error: %s",
                            func.__qualname__, max_attempts, exc,
                        )
                        if reraise:
                            raise
                        return None

                    # Compute wait with exponential backoff
                    base_wait = min(
                        wait_min * (multiplier ** (attempt - 1)),
                        wait_max,
                    )
                    actual_wait = (
                        base_wait * random.uniform(0.8, 1.2) if jitter else base_wait
                    )

                    logger.warning(
                        "[retry] %s — attempt %d/%d failed (%s: %s). "
                        "Retrying in %.1fs …",
                        func.__qualname__,
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        str(exc)[:120],
                        actual_wait,
                    )

                    import time
                    time.sleep(actual_wait)

        return wrapper
    return decorator


# ── Convenience pre-configured decorators ─────────────────────────────────

def retry_api(func: Callable) -> Callable:
    """
    Standard decorator for external API calls.
    3 attempts, exponential backoff 2s → 10s, re-raises on final failure.
    Apply this to any function that makes an HTTP request.
    """
    return with_retry()(func)


def retry_upload(func: Callable) -> Callable:
    """
    More patient decorator for YouTube uploads.
    5 attempts, backoff 5s → 60s (uploads are expensive to restart).
    """
    return with_retry(
        max_attempts=5,
        wait_min=5.0,
        wait_max=60.0,
        multiplier=2.0,
    )(func)


def retry_render(func: Callable) -> Callable:
    """
    Decorator for video rendering steps.
    2 attempts only — rendering failures are usually deterministic.
    """
    return with_retry(
        max_attempts=2,
        wait_min=3.0,
        wait_max=10.0,
    )(func)

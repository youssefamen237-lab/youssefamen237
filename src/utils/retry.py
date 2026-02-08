from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    tries: int = 5,
    base_delay_s: float = 1.0,
    max_delay_s: float = 20.0,
    jitter_s: float = 0.25,
    retry_if: Callable[[Exception], bool] | None = None,
) -> T:
    last_err: Exception | None = None
    for attempt in range(1, max(1, tries) + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if retry_if is not None and not retry_if(e):
                raise
            if attempt >= tries:
                raise
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            delay = max(0.0, delay + random.uniform(-jitter_s, jitter_s))
            time.sleep(delay)
    if last_err is not None:
        raise last_err
    raise RuntimeError("retry() failed without exception")

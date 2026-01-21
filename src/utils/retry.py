from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    jitter: float = 0.25,
) -> T:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i == attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2 ** i))
            delay = delay * (1.0 + random.uniform(-jitter, jitter))
            time.sleep(max(0.0, delay))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry failed without exception")

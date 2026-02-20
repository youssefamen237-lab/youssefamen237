import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_retry(fn: Callable[[], T], retries: int = 3, delay: float = 2.0, fallback: Callable[[], T] | None = None) -> T:
    last_err = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(delay * (attempt + 1))
    if fallback:
        return fallback()
    raise RuntimeError(f"Operation failed after retries: {last_err}")

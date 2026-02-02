from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class UploadThrottle:
    min_interval_s: float = 20.0
    _last_ts: float = 0.0

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self._last_ts
        if self._last_ts > 0 and elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_ts = time.time()

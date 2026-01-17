from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .tts_base import TTSProvider, TTSResult


@dataclass
class ProviderHealth:
    provider: TTSProvider
    consecutive_failures: int = 0
    cooldown_until: float = 0.0


class TTSChain:
    def __init__(self, providers: List[TTSProvider], max_failures: int = 3, cooldown_s: int = 1800):
        self._providers = [ProviderHealth(p) for p in providers]
        self._max_failures = max_failures
        self._cooldown_s = cooldown_s

    def synthesize(self, text: str, voice: str, out_path: Path, timeout_s: int = 60) -> TTSResult:
        last_err: Exception | None = None
        now = time.time()
        for ph in self._providers:
            if ph.cooldown_until > now:
                continue
            try:
                res = ph.provider.synthesize(text=text, voice=voice, out_path=out_path, timeout_s=timeout_s)
                ph.consecutive_failures = 0
                return res
            except Exception as e:
                last_err = e
                ph.consecutive_failures += 1
                if ph.consecutive_failures >= self._max_failures:
                    ph.cooldown_until = time.time() + self._cooldown_s
        if last_err:
            raise last_err
        raise RuntimeError("No TTS providers available")

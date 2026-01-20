from __future__ import annotations

import logging
import math
import random
import wave
from pathlib import Path
from typing import List, Optional

from .base import AudioPick, MusicProviderBase

logger = logging.getLogger(__name__)


class GeneratedMusicProvider(MusicProviderBase):
    key = "music_generated"

    def __init__(self, *, rng: random.Random, out_dir: Path) -> None:
        self.rng = rng
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _existing(self) -> List[Path]:
        files = sorted(self.out_dir.glob("*.wav"))
        return [p for p in files if p.is_file()]

    def _make_track(self, idx: int, seconds: int = 60, sample_rate: int = 44100) -> Path:
        path = self.out_dir / f"gen_music_{idx:03d}.wav"
        freq_base = self.rng.choice([110.0, 130.8, 146.8, 164.8])
        freqs = [freq_base, freq_base * 1.5, freq_base * 2.0]
        amp = 0.15
        nframes = seconds * sample_rate
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for i in range(nframes):
                t = i / sample_rate
                # Soft pad: detuned sines + slow LFO
                lfo = 0.6 + 0.4 * math.sin(2 * math.pi * 0.12 * t)
                v = 0.0
                for f in freqs:
                    v += math.sin(2 * math.pi * f * t)
                    v += 0.5 * math.sin(2 * math.pi * (f * 1.01) * t)
                v /= (len(freqs) * 1.5)
                v *= amp * lfo
                # Gentle noise
                v += (self.rng.random() - 0.5) * 0.01
                # Clip
                v = max(-1.0, min(1.0, v))
                samp = int(v * 32767)
                wf.writeframesraw(samp.to_bytes(2, byteorder="little", signed=True) * 2)
        return path

    def ensure_pool(self, min_count: int = 5) -> None:
        existing = self._existing()
        if len(existing) >= min_count:
            return
        start = len(existing)
        for i in range(start, min_count):
            self._make_track(i)

    def pick(self, *, duration_seconds: float) -> Optional[AudioPick]:
        self.ensure_pool(min_count=5)
        files = self._existing()
        if not files:
            return None
        path = self.rng.choice(files)
        return AudioPick(path=path, asset_id=path.stem, provider_key=self.key)

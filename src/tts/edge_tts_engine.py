from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import edge_tts

log = logging.getLogger("edge_tts_engine")


async def _synth_async(text: str, voice: str, rate: str, pitch: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_path))


def synthesize(text: str, *, voice: str, rate: str = "+0%", pitch: str = "+0Hz", out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = text.strip()
    if not text:
        raise ValueError("TTS text is empty")
    try:
        asyncio.run(_synth_async(text, voice, rate, pitch, out))
    except RuntimeError:
        # If already in event loop, fallback to creating a new loop
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_synth_async(text, voice, rate, pitch, out))
        finally:
            loop.close()
    return out

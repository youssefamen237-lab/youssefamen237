from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import requests
import edge_tts

from yt_auto.config import Config
from yt_auto.utils import RetryPolicy, backoff_sleep_s, ensure_dir


def synthesize_tts(cfg: Config, text: str, out_wav: Path) -> str:
    ensure_dir(out_wav.parent)
    last_err: Exception | None = None

    for provider in cfg.tts_order:
        p = provider.strip().lower()

        if p == "elevenlabs":
            if not cfg.eleven_api_key:
                continue
            try:
                _elevenlabs_to_wav(cfg, text, out_wav)
                return "elevenlabs"
            except Exception as e:
                last_err = e

        if p == "edge":
            try:
                _edge_to_wav(cfg, text, out_wav)
                return "edge"
            except Exception as e:
                last_err = e

    if last_err:
        raise last_err
    raise RuntimeError("no_tts_provider_available")


def _edge_to_wav(cfg: Config, text: str, out_wav: Path) -> None:
    mp3 = out_wav.with_suffix(".mp3")

    async def _run() -> None:
        communicate = edge_tts.Communicate(text=text, voice=cfg.edge_voice, rate=cfg.tts_speed)
        await communicate.save(str(mp3))

    asyncio.run(_run())
    _ffmpeg_convert_audio(mp3, out_wav)
    if mp3.exists():
        mp3.unlink(missing_ok=True)


def _elevenlabs_to_wav(cfg: Config, text: str, out_wav: Path) -> None:
    policy = RetryPolicy(max_attempts=4, base_sleep_s=0.9, max_sleep_s=8.0)

    voice_id = cfg.eleven_voice_id.strip()
    if not voice_id:
        voice_id = _elevenlabs_pick_voice(cfg.eleven_api_key)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": cfg.eleven_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload: dict[str, Any] = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.15,
            "use_speaker_boost": True,
        },
    }

    mp3 = out_wav.with_suffix(".mp3")

    for attempt in range(1, policy.max_attempts + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            r.raise_for_status()
            mp3.write_bytes(r.content)
            _ffmpeg_convert_audio(mp3, out_wav)
            mp3.unlink(missing_ok=True)
            return
        except Exception:
            time.sleep(backoff_sleep_s(attempt, policy))

    raise RuntimeError("elevenlabs_failed")


def _elevenlabs_pick_voice(api_key: str) -> str:
    url = "https://api.elevenlabs.io/v1/voices"
    r = requests.get(url, headers={"xi-api-key": api_key}, timeout=30)
    r.raise_for_status()
    data = r.json()
    voices = data.get("voices") or []
    if not voices:
        raise RuntimeError("elevenlabs_no_voices")
    vid = (voices[0] or {}).get("voice_id")
    if not isinstance(vid, str) or not vid.strip():
        raise RuntimeError("elevenlabs_bad_voice_id")
    return vid.strip()


def _ffmpeg_convert_audio(in_path: Path, out_wav: Path) -> None:
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_path),
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg_audio_convert_failed: {p.stderr[:500]}")

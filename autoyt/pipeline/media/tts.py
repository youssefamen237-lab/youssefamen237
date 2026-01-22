\
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from autoyt.utils.fs import ensure_dir, read_json, write_json
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.tts")


ELEVEN_BASE = "https://api.elevenlabs.io/v1"


def _ffprobe_duration_seconds(audio_path: Path) -> float:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def _hash_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()[:24]


def _elevenlabs_list_voices(api_key: str, cache_path: Path) -> Dict[str, str]:
    """Return mapping voice_name -> voice_id with caching."""
    if cache_path.exists():
        try:
            m = read_json(cache_path)
            if isinstance(m, dict) and m:
                return {str(k): str(v) for k, v in m.items()}
        except Exception:
            pass

    url = f"{ELEVEN_BASE}/voices"
    headers = {"xi-api-key": api_key, "User-Agent": "autoyt/1.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    mapping: Dict[str, str] = {}
    for v in data.get("voices", []) or []:
        name = v.get("name")
        vid = v.get("voice_id")
        if name and vid:
            mapping[str(name)] = str(vid)

    if mapping:
        write_json(cache_path, mapping)
    return mapping


def synthesize_tts(
    text: str,
    voice_profile: Dict[str, Any],
    out_path: Path,
    cache_dir: Path,
) -> float:
    """
    Generate TTS audio file for `text` using voice_profile.
    Returns audio duration in seconds (best-effort).
    """
    ensure_dir(out_path.parent)
    ensure_dir(cache_dir)

    provider = str(voice_profile.get("provider") or "").strip()
    voice_name = str(voice_profile.get("voice_name") or voice_profile.get("voice_id") or "").strip()

    # Cache
    cache_key = _hash_key(provider, voice_name, text)
    cached = cache_dir / f"{cache_key}.mp3"
    if cached.exists():
        shutil.copyfile(cached, out_path)
        return _ffprobe_duration_seconds(out_path)

    # Try providers
    try:
        if provider == "elevenlabs":
            api_key = os.environ.get("ELEVEN_API_KEY", "")
            if not api_key:
                raise RuntimeError("ELEVEN_API_KEY missing")
            voices_cache = cache_dir / "elevenlabs_voices.json"
            mapping = _elevenlabs_list_voices(api_key, voices_cache)
            voice_id = str(voice_profile.get("voice_id") or "").strip()
            if not voice_id:
                # resolve from name
                voice_id = mapping.get(voice_name) or ""
            if not voice_id:
                # pick any
                voice_id = next(iter(mapping.values())) if mapping else ""
            if not voice_id:
                raise RuntimeError("Could not resolve ElevenLabs voice_id")

            url = f"{ELEVEN_BASE}/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "accept": "audio/mpeg",
                "Content-Type": "application/json",
                "User-Agent": "autoyt/1.0",
            }
            payload = {
                "text": text,
                # Keep settings mild and natural
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2, "use_speaker_boost": True},
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        elif provider == "edge_tts":
            import edge_tts  # type: ignore

            async def _run() -> None:
                communicate = edge_tts.Communicate(text=text, voice=voice_name or "en-US-GuyNeural", rate="+0%")
                await communicate.save(str(out_path))

            asyncio.run(_run())

        else:
            raise RuntimeError(f"Unknown provider: {provider}")

        # Cache it
        try:
            shutil.copyfile(out_path, cached)
        except Exception:
            pass

        return _ffprobe_duration_seconds(out_path)

    except Exception as e:
        log.warning(f"TTS failed for provider={provider} voice={voice_name}: {e}")

    # Fallback: try edge-tts if not already
    if provider != "edge_tts":
        try:
            fallback_profile = {"provider": "edge_tts", "voice_name": "en-US-GuyNeural"}
            return synthesize_tts(text, fallback_profile, out_path, cache_dir)
        except Exception:
            pass

    # Last resort: silent audio (return 0)
    try:
        # create 0.1s silent audio to keep ffmpeg happy
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.1", str(out_path)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return 0.0

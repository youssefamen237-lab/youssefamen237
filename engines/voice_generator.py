"""
engines/voice_generator.py
"""
from __future__ import annotations
import json, os, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import structlog
from cascade.tts.tts_cascade import get_tts
from storage.r2_client import R2Paths, get_r2

logger = structlog.get_logger(__name__)


@dataclass
class VoiceResult:
    local_audio_path: str
    r2_audio_path:    str
    alignment:        Optional[dict]
    voice_id:         str
    voice_gender:     str
    provider:         str
    char_count:       int
    duration_seconds: float


class VoiceGenerator:

    def __init__(self) -> None:
        self._tts = get_tts()
        self._r2  = get_r2()

    def generate(
        self,
        script_text:       str,
        queue_id:          str,
        gender:            str = "female",
        voice_id_override: Optional[str] = None,
        local_dir:         Optional[str] = None,
    ) -> VoiceResult:
        if not script_text.strip():
            raise ValueError("generate() received empty script text.")

        if local_dir is None:
            local_dir = tempfile.mkdtemp(prefix=f"yta_voice_{queue_id[:8]}_")
        os.makedirs(local_dir, exist_ok=True)

        tts = self._tts.generate_audio(
            text=script_text,
            gender=gender,
            voice_id_override=voice_id_override,
        )

        local_path = os.path.join(local_dir, "narration.mp3")
        Path(local_path).write_bytes(tts.audio_bytes)

        r2_key = R2Paths.audio(queue_id, "narration.mp3")
        try:
            self._r2.upload_file(local_path, r2_key, content_type="audio/mpeg")
        except Exception as exc:
            logger.warning("voice_r2_upload_failed", queue_id=queue_id[:8], error=str(exc))

        duration = _probe_duration(local_path)

        logger.info(
            "voice_generated",
            queue_id=queue_id[:8],
            provider=tts.provider,
            gender=gender,
            chars=tts.char_count,
            duration=round(duration, 2),
            has_alignment=tts.alignment is not None,
        )
        return VoiceResult(
            local_audio_path=local_path,
            r2_audio_path=r2_key,
            alignment=tts.alignment,
            voice_id=tts.voice_id,
            voice_gender=tts.voice_gender,
            provider=tts.provider,
            char_count=tts.char_count,
            duration_seconds=duration,
        )


def _probe_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        data = json.loads(r.stdout)
        return float(data["format"].get("duration", 0) or 0)
    except Exception:
        return 0.0


_instance: Optional[VoiceGenerator] = None

def get_voice_generator() -> VoiceGenerator:
    global _instance
    if _instance is None:
        _instance = VoiceGenerator()
    return _instance

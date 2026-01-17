from __future__ import annotations

from pathlib import Path

from ..utils.media_utils import get_audio_duration_s
from ..utils.subprocesses import run_cmd
from .tts_base import TTSProvider, TTSResult


class EspeakTTS:
    name = "espeak-ng"

    def synthesize(self, text: str, voice: str, out_path: Path, timeout_s: int = 60) -> TTSResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # voice mapping: voice string can be "male" or "female" or explicit espeak voice
        espeak_voice = voice
        if voice.lower() in {"male", "m"}:
            espeak_voice = "en-us+m3"
        elif voice.lower() in {"female", "f"}:
            espeak_voice = "en-us+f3"
        cmd = [
            "espeak-ng",
            "-v",
            espeak_voice,
            "-s",
            "155",
            "-w",
            str(out_path),
            text,
        ]
        run_cmd(cmd, timeout=timeout_s, check=True)
        dur = get_audio_duration_s(out_path)
        return TTSResult(audio_path=out_path, duration_s=dur, provider=self.name, voice=espeak_voice)

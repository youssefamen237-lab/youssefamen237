"""
core/tts.py
===========
Text-to-speech generation using edge-tts (Microsoft Neural TTS, free).
Returns audio file path + exact duration in seconds for dynamic video timing.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import edge_tts
from pydub import AudioSegment

from config.settings import CHANNEL_VOICE, OUTPUT_AUDIO_DIR
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger(__name__)

# Padding added between hook and body in the combined narration (milliseconds)
INTER_SENTENCE_PAUSE_MS: int = 300

# edge-tts voice options — randomly rotated to add humanization
VOICE_POOL: list[str] = [
    "en-US-GuyNeural",       # primary — deep, authoritative
    "en-US-EricNeural",      # alternate male — slightly warmer
    "en-GB-RyanNeural",      # UK accent variant
]


@dataclass
class TTSResult:
    """
    Output of a single TTS generation call.

    Attributes
    ----------
    audio_path     : Absolute path to the rendered .mp3 file.
    duration_secs  : Exact playback duration measured from the audio file.
    voice          : edge-tts voice identifier that was used.
    hook_end_secs  : Timestamp (seconds) where the hook narration ends.
                     Used by video_editor.py to time the frame transition.
    """
    audio_path:    Path
    duration_secs: float
    voice:         str
    hook_end_secs: float


class TTSEngine:
    """
    Generates narration audio for one Short script (hook + body).

    The hook and body are rendered as a single continuous audio file with
    a brief pause between them.  The exact duration is measured via pydub
    so video_editor.py can dynamically match video length to audio length.

    Parameters
    ----------
    voice       : edge-tts voice name.  Defaults to CHANNEL_VOICE from settings.
    output_dir  : Directory for .mp3 output.  Created if missing.
    """

    def __init__(
        self,
        voice: Optional[str] = None,
        output_dir: Path = OUTPUT_AUDIO_DIR,
    ) -> None:
        self._voice      = voice or CHANNEL_VOICE
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public ─────────────────────────────────────────────────────────────

    def generate(self, hook: str, body: str, script_id: str = "") -> TTSResult:
        """
        Render hook + body to a single .mp3 and return a TTSResult.

        Parameters
        ----------
        hook      : Frame 1 text (spoken first).
        body      : Frame 2 text (spoken after pause).
        script_id : Optional UUID for deterministic filename correlation.

        Returns
        -------
        TTSResult with audio_path, duration_secs, and hook_end_secs.
        """
        uid   = script_id or str(uuid.uuid4())
        voice = self._voice

        logger.info("TTS: generating audio for script_id=%s voice=%s", uid, voice)

        # Render hook and body separately so we can measure hook duration
        hook_path = self._output_dir / f"{uid}_hook.mp3"
        body_path = self._output_dir / f"{uid}_body.mp3"
        out_path  = self._output_dir / f"{uid}.mp3"

        self._render_segment(hook, voice, hook_path)
        self._render_segment(body, voice, body_path)

        hook_audio = AudioSegment.from_mp3(str(hook_path))
        body_audio = AudioSegment.from_mp3(str(body_path))
        pause      = AudioSegment.silent(duration=INTER_SENTENCE_PAUSE_MS)

        combined = hook_audio + pause + body_audio
        combined.export(str(out_path), format="mp3", bitrate="192k")

        # Clean up intermediates
        hook_path.unlink(missing_ok=True)
        body_path.unlink(missing_ok=True)

        duration_secs  = len(combined) / 1000.0
        hook_end_secs  = (len(hook_audio) + INTER_SENTENCE_PAUSE_MS) / 1000.0

        logger.info(
            "TTS done: path=%s duration=%.2fs hook_end=%.2fs",
            out_path, duration_secs, hook_end_secs,
        )

        return TTSResult(
            audio_path=out_path,
            duration_secs=duration_secs,
            voice=voice,
            hook_end_secs=hook_end_secs,
        )

    # ── Private ─────────────────────────────────────────────────────────────

    @with_retry()
    def _render_segment(self, text: str, voice: str, out_path: Path) -> None:
        """
        Render a single text segment to an .mp3 file via edge-tts.
        Runs the async edge-tts coroutine synchronously so TTSEngine
        integrates cleanly into the synchronous pipeline.
        """
        asyncio.run(self._async_render(text, voice, out_path))
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(
                f"edge-tts produced no output for voice={voice} text='{text[:50]}'"
            )

    @staticmethod
    async def _async_render(text: str, voice: str, out_path: Path) -> None:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(out_path))

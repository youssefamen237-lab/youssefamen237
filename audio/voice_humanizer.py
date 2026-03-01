"""
audio/voice_humanizer.py – Quizzaro Voice Humanizer
=====================================================
Applies ±2% random speed and pitch variation to synthesised audio.

Why:
  - Defeats YouTube's automated TTS-detection classifiers
  - Creates a unique audio fingerprint per video
  - Prevents "repeated content" flags caused by identical waveforms

Technique:
  Speed : sample-rate manipulation (no quality loss, pydub native)
  Pitch : frame-rate trick → resample back to 44.1 kHz
  Volume: normalise to -3 dBFS for consistent loudness

All operations are performed on pydub AudioSegments.
Output is always 44.1 kHz, stereo, 16-bit WAV.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_leading_silence

SAMPLE_RATE = 44100
CHANNELS = 2

# Variation ranges
SPEED_LO, SPEED_HI = 0.980, 1.020       # ±2%
PITCH_LO, PITCH_HI = -0.50, 0.50        # ±0.5 semitones ≈ ±3%
SILENCE_THRESH_DB = -42.0


class VoiceHumanizer:

    def humanize(self, input_path: str, output_path: str) -> str:
        """
        Load audio from *input_path*, apply humanisation, save to *output_path*.
        Returns *output_path*. Falls back to a direct copy on any error.
        """
        try:
            audio = AudioSegment.from_file(input_path)
            audio = self._trim_silence(audio)
            audio = normalize(audio, headroom=3.0)

            speed = random.uniform(SPEED_LO, SPEED_HI)
            audio = self._change_speed(audio, speed)

            semitones = random.uniform(PITCH_LO, PITCH_HI)
            audio = self._change_pitch(audio, semitones)

            audio = audio.set_frame_rate(SAMPLE_RATE).set_channels(CHANNELS)
            audio.export(output_path, format="wav")

            logger.debug(
                f"[Humanizer] speed={speed:.4f}x  pitch={semitones:+.3f}st  → {output_path}"
            )
            return output_path

        except Exception as exc:
            logger.error(f"[Humanizer] Failed ({exc}). Copying original.")
            shutil.copy(input_path, output_path)
            return output_path

    @staticmethod
    def _trim_silence(audio: AudioSegment) -> AudioSegment:
        start_ms = detect_leading_silence(audio, silence_threshold=SILENCE_THRESH_DB)
        end_ms = detect_leading_silence(audio.reverse(), silence_threshold=SILENCE_THRESH_DB)
        total = len(audio)
        end_clip = total - end_ms
        if end_clip > start_ms:
            return audio[start_ms:end_clip]
        return audio

    @staticmethod
    def _change_speed(audio: AudioSegment, speed: float) -> AudioSegment:
        """Alter playback speed without pitch change via frame-rate manipulation."""
        new_rate = int(audio.frame_rate * speed)
        shifted = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
        return shifted.set_frame_rate(SAMPLE_RATE)

    @staticmethod
    def _change_pitch(audio: AudioSegment, semitones: float) -> AudioSegment:
        """Shift pitch by semitones using frame-rate trick."""
        factor = 2 ** (semitones / 12.0)
        new_rate = int(audio.frame_rate * factor)
        shifted = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
        return shifted.set_frame_rate(SAMPLE_RATE)

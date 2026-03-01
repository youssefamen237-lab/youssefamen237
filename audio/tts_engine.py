"""
audio/tts_engine.py – Quizzaro TTS Engine
==========================================
Standalone Text-to-Speech module used by VideoComposer.

Provider chain (in order):
  1. edge-tts   — Microsoft Edge neural voices (free, async, no key required)
  2. Kokoro ONNX — open-source offline model (runs inside GH Actions runner)
  3. Bark (HF)   — Hugging Face Inference API (HF_API_TOKEN required)

Each call picks a random voice in the requested gender so the channel
never sounds like the same person. Output is always 44.1 kHz stereo WAV.

This file is the thin synthesis layer.  Pitch/speed humanisation lives
in voice_humanizer.py, and SFX management lives in sfx_manager.py.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Optional

import requests
import soundfile as sf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

SAMPLE_RATE = 44100
CHANNELS = 2

# ── Edge-TTS voice pools ───────────────────────────────────────────────────
EDGE_VOICES: dict[str, list[str]] = {
    "male": [
        "en-US-AndrewNeural",
        "en-US-BrianNeural",
        "en-GB-RyanNeural",
        "en-AU-WilliamNeural",
        "en-CA-LiamNeural",
        "en-IE-ConnorNeural",
    ],
    "female": [
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-GB-SoniaNeural",
        "en-AU-NatashaNeural",
        "en-CA-ClaraNeural",
        "en-NZ-MollyNeural",
    ],
}

# ── Kokoro voice pools ─────────────────────────────────────────────────────
KOKORO_VOICES: dict[str, list[str]] = {
    "male": ["am_adam", "am_michael", "bm_george", "bm_lewis"],
    "female": ["af_heart", "af_bella", "bf_emma", "bf_isabella"],
}

# ── Bark speaker presets ───────────────────────────────────────────────────
BARK_VOICES: dict[str, list[str]] = {
    "male": ["v2/en_speaker_6", "v2/en_speaker_9", "v2/en_speaker_3"],
    "female": ["v2/en_speaker_5", "v2/en_speaker_4", "v2/en_speaker_2"],
}

BARK_HF_URL = "https://api-inference.huggingface.co/models/suno/bark-small"


class TTSEngine:
    """
    Orchestrates the full TTS fallback chain.
    Called by VideoComposer / AudioEngine for every Short.
    """

    def __init__(self, hf_token: str = "", fallback_manager=None) -> None:
        self._hf_token = hf_token
        self._fb = fallback_manager
        self._edge_ok = self._check_edge_tts()
        self._kokoro = self._load_kokoro()

    # ── Provider availability checks ──────────────────────────────────────

    @staticmethod
    def _check_edge_tts() -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            logger.warning("[TTS] edge-tts not installed.")
            return False

    @staticmethod
    def _load_kokoro():
        try:
            from kokoro_onnx import Kokoro
            k = Kokoro("kokoro-v0_19.onnx", "voices.bin")
            logger.info("[TTS] Kokoro ONNX model loaded.")
            return k
        except Exception as exc:
            logger.warning(f"[TTS] Kokoro not available: {exc}")
            return None

    # ── Edge-TTS ──────────────────────────────────────────────────────────

    async def _edge_async(self, text: str, voice: str, out: str) -> None:
        import edge_tts
        comm = edge_tts.Communicate(text=text, voice=voice)
        await comm.save(out)

    def _synth_edge(self, text: str, gender: str, out: str) -> bool:
        if not self._edge_ok:
            return False
        if self._fb and self._fb.is_failed("tts", "edge"):
            return False
        voice = random.choice(EDGE_VOICES[gender])
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._edge_async(text, voice, out))
            loop.close()
            logger.debug(f"[TTS] edge-tts | voice={voice}")
            return True
        except Exception as exc:
            logger.warning(f"[TTS] edge-tts failed: {exc}")
            if self._fb:
                self._fb.mark_failed("tts", "edge")
            return False

    # ── Kokoro ────────────────────────────────────────────────────────────

    def _synth_kokoro(self, text: str, gender: str, out: str) -> bool:
        if not self._kokoro:
            return False
        if self._fb and self._fb.is_failed("tts", "kokoro"):
            return False
        voice = random.choice(KOKORO_VOICES[gender])
        try:
            samples, sr = self._kokoro.create(text=text, voice=voice, speed=1.0, lang="en-us")
            sf.write(out, samples, sr)
            logger.debug(f"[TTS] Kokoro | voice={voice}")
            return True
        except Exception as exc:
            logger.warning(f"[TTS] Kokoro failed: {exc}")
            if self._fb:
                self._fb.mark_failed("tts", "kokoro")
            return False

    # ── Bark (HF Inference API) ────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
    def _synth_bark(self, text: str, gender: str, out: str) -> bool:
        if not self._hf_token:
            return False
        if self._fb and self._fb.is_failed("tts", "bark"):
            return False
        voice = random.choice(BARK_VOICES[gender])
        try:
            resp = requests.post(
                BARK_HF_URL,
                headers={"Authorization": f"Bearer {self._hf_token}"},
                json={"inputs": text, "parameters": {"voice_preset": voice}},
                timeout=90,
            )
            resp.raise_for_status()
            with open(out, "wb") as f:
                f.write(resp.content)
            logger.debug(f"[TTS] Bark | voice={voice}")
            return True
        except Exception as exc:
            logger.warning(f"[TTS] Bark failed: {exc}")
            if self._fb:
                self._fb.mark_failed("tts", "bark")
            return False

    # ── Public interface ───────────────────────────────────────────────────

    def synthesize(self, text: str, gender: str, output_path: str) -> str:
        """
        Synthesize *text* in the requested *gender* voice.
        Tries Edge → Kokoro → Bark. Returns output_path on success.
        Raises RuntimeError if all providers fail.
        """
        raw_out = output_path.replace(".wav", "_raw.wav")

        if self._synth_edge(text, gender, raw_out):
            return raw_out
        if self._synth_kokoro(text, gender, raw_out):
            return raw_out
        if self._synth_bark(text, gender, raw_out):
            return raw_out

        raise RuntimeError(f"[TTS] All providers failed for: {text[:80]}")

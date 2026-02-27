"""
tts_engine.py
Text-to-speech using edge-tts (primary) and Hugging Face Kokoro (fallback).
Applies random pitch/speed variation per video to create unique audio fingerprints.
100% free.
"""

import os
import random
import asyncio
import tempfile
import subprocess
import requests
import json

HF_API_TOKEN = os.environ.get("HF_API_TOKEN", "")

EDGE_TTS_VOICES = [
    "en-US-ChristopherNeural",
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
    "en-AU-WilliamNeural",
    "en-CA-LiamNeural",
]


async def _edge_tts_generate(text: str, voice: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def _apply_audio_variation(input_path: str, output_path: str):
    """
    Applies random speed (±2%) and pitch (±2%) variation using ffmpeg.
    Creates unique audio fingerprint per video to avoid spam detection.
    """
    speed_factor = random.uniform(0.98, 1.02)
    pitch_semitones = random.uniform(-0.3, 0.3)
    pitch_hz = 440 * (2 ** (pitch_semitones / 12)) - 440

    atempo = f"atempo={speed_factor:.4f}"
    asetrate_val = int(44100 * (1 + pitch_semitones / 100))

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", f"{atempo},asetrate={asetrate_val},aresample=44100",
        "-ar", "44100",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        import shutil
        shutil.copy(input_path, output_path)


def _hf_kokoro_tts(text: str, output_path: str):
    """
    Uses Hugging Face Inference API with Kokoro-82M or similar model.
    """
    url = "https://api-inference.huggingface.co/models/hexgrad/Kokoro-82M"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return True
    return False


def generate_speech(text: str, output_path: str, voice_override: str = None) -> str:
    """
    Generates speech audio file at output_path.
    Returns path to final audio file with variation applied.
    """
    voice = voice_override or random.choice(EDGE_TTS_VOICES)
    raw_path = output_path.replace(".mp3", "_raw.mp3").replace(".wav", "_raw.wav")
    if not raw_path.endswith("_raw.mp3"):
        raw_path = output_path + "_raw.mp3"
        final_path = output_path if output_path.endswith(".mp3") else output_path + ".mp3"
    else:
        final_path = output_path

    # Primary: edge-tts
    try:
        asyncio.run(_edge_tts_generate(text, voice, raw_path))
        _apply_audio_variation(raw_path, final_path)
        if os.path.exists(raw_path):
            os.remove(raw_path)
        print(f"[TTS] Generated with edge-tts voice: {voice}")
        return final_path
    except Exception as e:
        print(f"[TTS] edge-tts failed: {e}")

    # Fallback: Hugging Face Kokoro
    if HF_API_TOKEN:
        try:
            if _hf_kokoro_tts(text, raw_path):
                _apply_audio_variation(raw_path, final_path)
                if os.path.exists(raw_path):
                    os.remove(raw_path)
                print("[TTS] Generated with HF Kokoro TTS")
                return final_path
        except Exception as e:
            print(f"[TTS] HF Kokoro failed: {e}")

    # Last resort: Google TTS via gTTS
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(raw_path)
        _apply_audio_variation(raw_path, final_path)
        if os.path.exists(raw_path):
            os.remove(raw_path)
        print("[TTS] Generated with gTTS fallback")
        return final_path
    except Exception as e:
        print(f"[TTS] gTTS failed: {e}")

    raise RuntimeError("All TTS providers failed.")


def get_consistent_voice() -> str:
    """
    Returns a consistent voice per session (channel identity).
    Randomly picks from top quality voices.
    """
    return random.choice(["en-US-ChristopherNeural", "en-US-GuyNeural"])

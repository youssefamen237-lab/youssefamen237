"""
Audio Generator — Natural human-sounding TTS, NEVER silent.
Chain: ElevenLabs (best) → OpenAI TTS → CambAI → HuggingFace → gTTS (free, guaranteed)
Audio is 100% MANDATORY. Every video MUST have voice.
"""

import os
import subprocess
import random
import time
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Channel voice identity ───────────────────────────────────────────────────
CHANNEL_VOICE_ELEVEN = "21m00Tcm4TlvDq8ikWAM"   # Rachel — warm, clear, natural
CHANNEL_VOICE_SETTINGS = {
    "stability": 0.65,
    "similarity_boost": 0.80,
    "style": 0.35,
    "use_speaker_boost": True,
}
CHANNEL_VOICE_OPENAI = "nova"   # nova = warm natural female, very close to human


def _verify_audio(path: str, min_bytes: int = 2000) -> bool:
    try:
        return bool(path) and os.path.exists(path) and os.path.getsize(path) >= min_bytes
    except Exception:
        return False


def _reencode_to_aac(input_path: str, output_path: str) -> str:
    """Re-encode any audio to AAC 44100Hz stereo (required for FFmpeg concat)"""
    r = subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "44100", "-ac", "2",
        "-c:a", "aac", "-b:a", "192k",
        output_path
    ], capture_output=True, text=True)
    if r.returncode == 0 and _verify_audio(output_path):
        return output_path
    return input_path


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
def _eleven_labs(text: str, output_path: str) -> str:
    api_key = os.environ.get("ELEVEN_API_KEY", "")
    if not api_key:
        raise ValueError("No ELEVEN_API_KEY")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{CHANNEL_VOICE_ELEVEN}"
    headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": api_key}
    body = {"text": text, "model_id": "eleven_monolingual_v1", "voice_settings": CHANNEL_VOICE_SETTINGS}
    r = requests.post(url, json=body, headers=headers, timeout=45)
    r.raise_for_status()
    if len(r.content) < 2000:
        raise ValueError(f"ElevenLabs response too small: {len(r.content)}")
    with open(output_path, "wb") as f:
        f.write(r.content)
    if not _verify_audio(output_path):
        raise ValueError("ElevenLabs output invalid")
    print(f"[TTS] ✓ ElevenLabs ({os.path.getsize(output_path)//1024}KB)")
    return output_path


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
def _openai_tts(text: str, output_path: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("No OPENAI_API_KEY")
    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": "tts-1-hd", "input": text, "voice": CHANNEL_VOICE_OPENAI,
            "response_format": "mp3", "speed": 0.95}
    r = requests.post(url, json=body, headers=headers, timeout=45)
    r.raise_for_status()
    if len(r.content) < 2000:
        raise ValueError(f"OpenAI TTS too small: {len(r.content)}")
    with open(output_path, "wb") as f:
        f.write(r.content)
    if not _verify_audio(output_path):
        raise ValueError("OpenAI TTS output invalid")
    print(f"[TTS] ✓ OpenAI TTS-HD ({os.path.getsize(output_path)//1024}KB)")
    return output_path


@retry(stop=stop_after_attempt(1), wait=wait_exponential(min=2, max=8))
def _camb_ai(text: str, output_path: str) -> str:
    api_key = os.environ.get("CAMB_AI_KEY_1", "")
    if not api_key:
        raise ValueError("No CAMB_AI_KEY_1")
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    r = requests.post("https://client.camb.ai/apis/tts",
                      json={"text": text, "voice_id": 1, "language": 1, "gender": 2, "age": 1},
                      headers=headers, timeout=30)
    r.raise_for_status()
    task_id = r.json().get("task_id")
    if not task_id:
        raise ValueError("No task_id")
    for _ in range(15):
        time.sleep(3)
        sr = requests.get(f"https://client.camb.ai/apis/tts/{task_id}", headers=headers, timeout=20)
        sd = sr.json()
        if sd.get("status") == "SUCCESS":
            ar = requests.get(sd["audio_url"], timeout=30)
            with open(output_path, "wb") as f:
                f.write(ar.content)
            if _verify_audio(output_path):
                print(f"[TTS] ✓ CambAI ({os.path.getsize(output_path)//1024}KB)")
                return output_path
    raise ValueError("CambAI timed out")


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=3, max=10))
def _huggingface_tts(text: str, output_path: str) -> str:
    api_key = os.environ.get("HF_API_TOKEN", "")
    if not api_key:
        raise ValueError("No HF_API_TOKEN")
    url = "https://api-inference.huggingface.co/models/espnet/kan-bayashi_ljspeech_vits"
    r = requests.post(url, headers={"Authorization": f"Bearer {api_key}"},
                      json={"inputs": text}, timeout=45)
    if r.status_code != 200 or len(r.content) < 1000:
        raise ValueError(f"HuggingFace bad response: {r.status_code}")
    raw = output_path + ".raw"
    with open(raw, "wb") as f:
        f.write(r.content)
    conv = subprocess.run([
        "ffmpeg", "-y", "-i", raw,
        "-ar", "44100", "-ac", "2", "-b:a", "192k", output_path
    ], capture_output=True)
    try:
        os.remove(raw)
    except Exception:
        pass
    if conv.returncode == 0 and _verify_audio(output_path):
        print(f"[TTS] ✓ HuggingFace ({os.path.getsize(output_path)//1024}KB)")
        return output_path
    raise ValueError("HuggingFace conversion failed")


def _gtts(text: str, output_path: str) -> str:
    """
    Google TTS — 100% free, no API key, ALWAYS available.
    Natural-sounding, clear English voice. This is the guaranteed fallback.
    """
    from gtts import gTTS

    tmp = output_path + ".gtts.mp3"
    tts = gTTS(text=text, lang="en", slow=False, tld="com")
    tts.save(tmp)

    if not os.path.exists(tmp) or os.path.getsize(tmp) < 500:
        raise RuntimeError("gTTS produced empty file")

    # Re-encode for clean audio
    result = subprocess.run([
        "ffmpeg", "-y", "-i", tmp,
        "-ar", "44100", "-ac", "2", "-b:a", "192k",
        output_path
    ], capture_output=True)

    try:
        os.remove(tmp)
    except Exception:
        pass

    if result.returncode != 0 or not _verify_audio(output_path, 500):
        # ffmpeg failed — use raw gTTS file directly
        import shutil
        if os.path.exists(tmp):
            shutil.copy(tmp, output_path)
        else:
            # Re-save directly
            tts2 = gTTS(text=text, lang="en", slow=False)
            tts2.save(output_path)

    if not _verify_audio(output_path, 500):
        raise RuntimeError(f"gTTS final output invalid")

    print(f"[TTS] ✓ gTTS free ({os.path.getsize(output_path)//1024}KB)")
    return output_path


def generate_audio(text: str, output_path: str) -> str:
    """
    Generate natural TTS audio. GUARANTEED to return valid audio file.
    Never silently fails — raises RuntimeError only if everything breaks.
    """
    if not output_path.endswith(".mp3"):
        output_path += ".mp3"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    providers = [
        ("ElevenLabs", _eleven_labs),
        ("OpenAI TTS-HD", _openai_tts),
        ("CambAI", _camb_ai),
        ("HuggingFace", _huggingface_tts),
    ]
    for name, fn in providers:
        try:
            result = fn(text, output_path)
            if _verify_audio(result):
                return result
        except Exception as e:
            print(f"[TTS] {name} unavailable: {e}")

    print("[TTS] All premium providers failed → gTTS guaranteed fallback")
    return _gtts(text, output_path)


def generate_full_short_audio(question_text: str, cta_text: str, output_dir: str) -> dict:
    """
    Generate all audio for a Short video and return a single combined AAC track.

    Timeline: [Question read aloud] [0.5s pause] [CTA read aloud]
    The combined track is synced to play during the question+CTA section of the video.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    q_mp3  = str(out / "question.mp3")
    cta_mp3 = str(out / "cta.mp3")
    q_aac  = str(out / "question.aac")
    cta_aac = str(out / "cta.aac")
    sil_aac = str(out / "silence.aac")
    combined = str(out / "combined.aac")

    print("\n[TTS] === Generating Short audio ===")
    generate_audio(question_text, q_mp3)
    generate_audio(cta_text, cta_mp3)

    # Convert to AAC (required for FFmpeg concat filter)
    _reencode_to_aac(q_mp3, q_aac)
    _reencode_to_aac(cta_mp3, cta_aac)

    # Generate 0.5s silence AAC
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", "0.5", "-c:a", "aac", "-b:a", "128k", sil_aac
    ], capture_output=True, check=True)

    # Concat: question → pause → CTA
    concat_txt = str(out / "concat.txt")
    with open(concat_txt, "w") as f:
        f.write(f"file '{q_aac}'\n")
        f.write(f"file '{sil_aac}'\n")
        f.write(f"file '{cta_aac}'\n")

    r1 = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c", "copy", combined
    ], capture_output=True, text=True)

    if r1.returncode != 0 or not _verify_audio(combined):
        print(f"[TTS] Concat failed ({r1.stderr[:80]}), using filter_complex")
        r2 = subprocess.run([
            "ffmpeg", "-y",
            "-i", q_aac, "-i", sil_aac, "-i", cta_aac,
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
            combined
        ], capture_output=True, text=True)
        if r2.returncode != 0 or not _verify_audio(combined):
            print(f"[TTS] filter_complex also failed, using question only")
            _reencode_to_aac(q_mp3, combined)

    if not _verify_audio(combined):
        raise RuntimeError(f"[TTS] CRITICAL: combined audio track invalid")

    print(f"[TTS] ✓ Combined audio: {os.path.getsize(combined)//1024}KB")
    return {
        "question_audio": q_mp3,
        "cta_audio": cta_mp3,
        "combined_audio": combined,
    }


if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the capital of France?"
    out = generate_audio(text, "/tmp/test_tts_output.mp3")
    print(f"Output: {out} ({os.path.getsize(out)//1024}KB)")

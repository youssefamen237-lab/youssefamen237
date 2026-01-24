\
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from .utils.media_utils import ffprobe_duration_seconds

logger = logging.getLogger(__name__)


def _ssml(text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz") -> str:
    safe_text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{voice}'>"
        f"<prosody rate='{rate}' pitch='{pitch}'>"
        f"{safe_text}"
        "</prosody>"
        "</voice>"
        "</speak>"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=10))
def tts_edge(text: str, profile: Dict[str, Any], out_mp3: Path) -> float:
    import edge_tts

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    voice = profile.get("voice") or "en-US-JennyNeural"
    rate = profile.get("rate") or "+0%"
    pitch = profile.get("pitch") or "+0Hz"

    ssml = _ssml(text, voice=voice, rate=rate, pitch=pitch)

    async def _run() -> None:
        communicate = edge_tts.Communicate(ssml, voice=voice)
        await communicate.save(str(out_mp3))

    asyncio.run(_run())

    dur = ffprobe_duration_seconds(out_mp3) or 0.0
    return float(dur)


@retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=6))
def tts_gtts(text: str, out_mp3: Path) -> float:
    from gtts import gTTS

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    tts = gTTS(text=text, lang="en")
    tts.save(str(out_mp3))

    dur = ffprobe_duration_seconds(out_mp3) or 0.0
    return float(dur)


def synthesize(text: str, profile: Dict[str, Any], out_mp3: Path) -> float:
    provider = (profile.get("provider") or "edge_tts").lower()
    if provider == "edge_tts":
        try:
            return tts_edge(text, profile, out_mp3)
        except Exception as e:
            logger.warning("edge_tts failed: %s", e)

    # fallback
    return tts_gtts(text, out_mp3)

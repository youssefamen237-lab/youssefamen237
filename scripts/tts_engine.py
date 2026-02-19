import os
import logging
import uuid
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_fixed
from gtts import gTTS

from .config import Config

logger = logging.getLogger("tts_engine")
handler = logging.FileHandler(Config.LOG_DIR / "tts_engine.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Attempt to import ElevenLabs; if unavailable, fallback will use gTTS
try:
    import elevenlabs
    ELEVEN_AVAILABLE = True
except Exception:
    ELEVEN_AVAILABLE = False
    logger.warning("ElevenLabs library not available, will fallback to gTTS.")


class TTSEngine:
    def __init__(self):
        self.eleven_key = Config.ELEVEN_API_KEY
        if ELEVEN_AVAILABLE and self.eleven_key:
            elevenlabs.set_api_key(self.eleven_key)
            self.voice_id = Config.ELEVEN_VOICE_ID
        else:
            self.voice_id = None

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Generate speech audio for `text` and save to `output_path` (MP3).
        Preference: ElevenLabs → gTTS.
        """
        if ELEVEN_AVAILABLE and self.eleven_key:
            try:
                logger.info("Using ElevenLabs TTS.")
                audio = elevenlabs.generate(
                    text=text,
                    voice=self.voice_id,
                    model="eleven_multilingual_v2"
                )
                elevenlabs.save(audio, str(output_path))
                return output_path
            except Exception as e:
                logger.warning(f"ElevenLabs failed ({e}), falling back to gTTS.")
        # Fallback to gTTS (requires internet)
        try:
            logger.info("Using gTTS fallback.")
            tts = gTTS(text=text, lang="en", slow=False)
            tts.save(str(output_path))
            return output_path
        except Exception as e:
            logger.exception(f"TTS generation failed: {e}")
            raise RuntimeError("All TTS providers failed.") from e

    def generate_question_audio(self, question_text: str) -> Path:
        suffix = uuid.uuid4().hex
        out = Path(f"temp/question_{suffix}.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)
        return self.synthesize(question_text, out)

    def generate_cta_audio(self, cta_text: str) -> Path:
        suffix = uuid.uuid4().hex
        out = Path(f"temp/cta_{suffix}.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)
        return self.synthesize(cta_text, out)

import elevenlabs
from config import Config
import asyncio
import edge_tts
import os

class AudioEngine:
    def __init__(self):
        if Config.ELEVEN_API_KEY:
            elevenlabs.set_api_key(Config.ELEVEN_API_KEY)

    def generate_voice(self, text, filename):
        # Try ElevenLabs first (High Quality)
        if Config.ELEVEN_API_KEY:
            try:
                audio = elevenlabs.generate(
                    text=text,
                    voice=Config.VOICE_ID,
                    model="eleven_monolingual_v1"
                )
                with open(filename, "wb") as f:
                    f.write(audio)
                return filename
            except Exception as e:
                print(f"ElevenLabs failed: {e}, falling back to Edge-TTS")
        
        # Fallback to Edge-TTS (Free, High Quality Microsoft Voices)
        return self._generate_edge_tts(text, filename)

    async def _generate_edge_tts(self, text, filename):
        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
        await communicate.save(filename)
        return filename

    def generate_audio_sync(self, text, filename):
        asyncio.run(self._generate_edge_tts(text, filename))

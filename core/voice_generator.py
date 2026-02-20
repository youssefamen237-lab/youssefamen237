import os
import re
import time
import logging
import httpx
from datetime import datetime
from typing import Tuple, Optional

import edge_tts
from dotenv import load_dotenv

load_dotenv()

class VoiceGenerator:
    def __init__(self):
        self.setup_logger()
        self.voice_options = [
            "en-US-AvaNeural",  # Female, clear voice
            "en-US-AndrewNeural",  # Male, professional
            "en-GB-SoniaNeural",  # British accent
            "en-CA-LiamNeural",   # Canadian accent
            "en-US-EricNeural",   # Male, energetic
            "en-US-JennyNeural"   # Female, friendly
        ]
        self.current_voice = None
        self.last_voice_change = None
        self.voice_change_interval = 3  # Change voice every 3 videos
        
    def setup_logger(self):
        self.logger = logging.getLogger('VoiceGenerator')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def get_voice(self) -> str:
        """Select appropriate voice with rotation logic"""
        current_time = datetime.now()
        
        # Change voice periodically to avoid repetition
        if (self.last_voice_change is None or 
            (current_time - self.last_voice_change).days >= self.voice_change_interval)):
            
            # Prefer voices matching target audience (US, UK, CA)
            audience_voices = [
                v for v in self.voice_options 
                if "en-US" in v or "en-GB" in v or "en-CA" in v
            ]
            self.current_voice = random.choice(audience_voices)
            self.last_voice_change = current_time
            self.logger.info(f"Voice changed to: {self.current_voice}")
            
        return self.current_voice
    
    def generate_audio(self, text: str, output_path: str) -> bool:
        """Generate natural-sounding audio using available services with fallback"""
        voice = self.get_voice()
        
        # Try ElevenLabs first (best quality)
        if self._try_elevenlabs(text, output_path, voice):
            return True
            
        # Try Edge TTS (free alternative)
        if self._try_edge_tts(text, output_path, voice):
            return True
            
        # Try Google Cloud Text-to-Speech (if API key available)
        if self._try_google_tts(text, output_path, voice):
            return True
            
        self.logger.error("All voice generation services failed")
        return False
    
    def _try_elevenlabs(self, text: str, output_path: str, voice: str) -> bool:
        api_key = os.getenv('ELEVEN_API_KEY')
        if not api_key:
            return False
            
        try:
            # Map our voice names to ElevenLabs voice IDs
            voice_map = {
                "en-US-AvaNeural": "EXAVITQu4vr4xnSDxMaL",
                "en-US-AndrewNeural": "VR6AewLTigWG4xSOukaG",
                "en-GB-SoniaNeural": "AZnzlk1XvdvUeBnXmlld",
                "en-CA-LiamNeural": "TX3LPaxmHKxFdv7VOQHJ",
                "en-US-EricNeural": "BJFRvMvJ2JxK2JxK2JxK",
                "en-US-JennyNeural": "jFwnyq59XJzq7BQ7JxK2"
            }
            
            voice_id = voice_map.get(voice, "EXAVITQu4vr4xnSDxMaL")  # Default to Ava
            
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "xi-api-key": api_key,
                "Content-Type": "application/json"
            }
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            response = httpx.post(url, json=data, headers=headers, timeout=30.0)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
                
        except Exception as e:
            self.logger.error(f"ElevenLabs error: {str(e)}")
            
        return False
    
    def _try_edge_tts(self, text: str, output_path: str, voice: str) -> bool:
        try:
            # Map our voice names to Edge TTS voice names
            voice_map = {
                "en-US-AvaNeural": "en-US-AvaNeural",
                "en-US-AndrewNeural": "en-US-AndrewNeural",
                "en-GB-SoniaNeural": "en-GB-SoniaNeural",
                "en-CA-LiamNeural": "en-CA-LiamNeural",
                "en-US-EricNeural": "en-US-EricNeural",
                "en-US-JennyNeural": "en-US-JennyNeural"
            }
            
            edge_voice = voice_map.get(voice, "en-US-AvaNeural")
            
            # Generate audio using Edge TTS
            communicate = edge_tts.Communicate(text, edge_voice)
            asyncio.run(communicate.save(output_path))
            return True
            
        except Exception as e:
            self.logger.error(f"Edge TTS error: {str(e)}")
            return False
    
    def _try_google_tts(self, text: str, output_path: str, voice: str) -> bool:
        api_key = os.getenv('GOOGLE_CLOUD_API_KEY')
        if not api_key:
            return False
            
        try:
            # Map our voice names to Google Cloud voices
            voice_map = {
                "en-US-AvaNeural": "en-US-Wavenet-A",
                "en-US-AndrewNeural": "en-US-Wavenet-B",
                "en-GB-SoniaNeural": "en-GB-Wavenet-A",
                "en-CA-LiamNeural": "en-CA-Wavenet-A",
                "en-US-EricNeural": "en-US-Wavenet-C",
                "en-US-JennyNeural": "en-US-Wavenet-D"
            }
            
            voice_name = voice_map.get(voice, "en-US-Wavenet-A")
            
            url = "https://texttospeech.googleapis.com/v1/text:synthesize"
            params = {"key": api_key}
            data = {
                "input": {"text": text},
                "voice": {"languageCode": "en-US", "name": voice_name},
                "audioConfig": {"audioEncoding": "MP3"}
            }
            
            response = httpx.post(url, params=params, json=data, timeout=30.0)
            if response.status_code == 200:
                audio_content = base64.b64decode(response.json()["audioContent"])
                with open(output_path, 'wb') as f:
                    f.write(audio_content)
                return True
                
        except Exception as e:
            self.logger.error(f"Google TTS error: {str(e)}")
            
        return False
    
    def generate_countdown_audio(self, output_path: str) -> bool:
        """Generate the 5-second countdown audio"""
        try:
            # Create a simple countdown with beeps
            countdown_text = "5... 4... 3... 2... 1..."
            return self.generate_audio(countdown_text, output_path)
        except Exception as e:
            self.logger.error(f"Countdown audio generation failed: {str(e)}")
            return False

import os
import requests
from elevenlabs import set_api_key, voices, generate, stream, Voice, play
from gtts import gTTS
from pydub import AudioSegment
from config import ELEVEN_API_KEY, AUDIO_DIR
import random

class AudioGenerator:
    def __init__(self):
        if ELEVEN_API_KEY:
            set_api_key(ELEVEN_API_KEY)
            self.use_elevenlabs = True
        else:
            self.use_elevenlabs = False
    
    def generate_question_audio(self, text, filename):
        """Generate audio for the question part"""
        filepath = os.path.join(AUDIO_DIR, f"{filename}_question.mp3")
        
        if self.use_elevenlabs:
            try:
                # Use a natural sounding voice from ElevenLabs
                audio = generate(
                    text=text,
                    voice=Voice(voice_id="EXAVITQu4vr4xnSDxMaL"),  # Adam voice
                    model="eleven_multilingual_v2"
                )
                with open(filepath, 'wb') as f:
                    f.write(audio)
            except Exception as e:
                print(f"ElevenLabs failed: {e}, falling back to gTTS")
                self._generate_with_gtts(text, filepath)
        else:
            self._generate_with_gtts(text, filepath)
        
        return filepath
    
    def generate_cta_audio(self, cta_text, filename):
        """Generate audio for the call-to-action"""
        filepath = os.path.join(AUDIO_DIR, f"{filename}_cta.mp3")
        
        if self.use_elevenlabs:
            try:
                audio = generate(
                    text=cta_text,
                    voice=Voice(voice_id="EXAVITQu4vr4xnSDxMaL"),  # Adam voice
                    model="eleven_multilingual_v2"
                )
                with open(filepath, 'wb') as f:
                    f.write(audio)
            except Exception as e:
                print(f"ElevenLabs CTA failed: {e}, falling back to gTTS")
                self._generate_with_gtts(cta_text, filepath)
        else:
            self._generate_with_gtts(cta_text, filepath)
        
        return filepath
    
    def _generate_with_gtts(self, text, filepath):
        """Fallback to gTTS if ElevenLabs fails"""
        tts = gTTS(text=text, lang='en')
        tts.save(filepath)
    
    def combine_audio_segments(self, segments, output_path):
        """Combine multiple audio segments into one"""
        combined = AudioSegment.empty()
        
        for segment_path in segments:
            if os.path.exists(segment_path):
                segment = AudioSegment.from_mp3(segment_path)
                combined += segment
        
        combined.export(output_path, format="mp3")
        return output_path

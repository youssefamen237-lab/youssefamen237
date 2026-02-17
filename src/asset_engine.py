import os
import random
import requests
import edge_tts
import asyncio
from dotenv import load_dotenv

load_dotenv()

class AssetEngine:
    def __init__(self):
        self.pexels_key = os.getenv("PEXELS_API_KEY")
        self.eleven_key = os.getenv("ELEVEN_API_KEY")
        self.fallback_voice = "en-US-ChristopherNeural"
        
    async def generate_voice(self, text, filename):
        # Try ElevenLabs first (Higher Quality)
        if self.eleven_key:
            try:
                url = "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM" # Rachel Voice
                headers = {"xi-api-key": self.eleven_key, "Content-Type": "application/json"}
                data = {"text": text, "model_id": "eleven_monolingual_v1", "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}}
                resp = requests.post(url, json=data, headers=headers)
                if resp.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(resp.content)
                    return
            except Exception as e:
                print(f"ElevenLabs failed, falling back to Edge-TTS: {e}")
        
        # Fallback to Edge-TTS (Free, Unlimited)
        communicate = edge_tts.Communicate(text, self.fallback_voice)
        await communicate.save(filename)

    def get_background_image(self, query, filename):
        headers = {"Authorization": self.pexels_key}
        params = {"query": query, "per_page": 1, "orientation": "portrait"}
        
        try:
            resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
            data = resp.json()
            if data['photos']:
                img_url = data['photos'][0]['src']['portrait']
                img_data = requests.get(img_url).content
                with open(filename, 'wb') as f:
                    f.write(img_data)
                return True
        except:
            pass
        
        # Fallback: Generate a solid color or gradient if API fails
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1080, 1920), color=(random.randint(50,150), random.randint(50,150), random.randint(50,150)))
        img.save(filename)
        return True

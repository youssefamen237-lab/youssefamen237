import requests
import os
from PIL import Image, ImageFilter
from io import BytesIO
from elevenlabs import ElevenLabs  # تم تحديث الاستيراد
import random
from src.config import ELEVEN_API_KEY, UNSPLASH_ACCESS_KEY, OPENAI_API_KEY

class AssetManager:
    def __init__(self):
        # تهيئة عميل ElevenLabs بالطريقة الجديدة
        self.eleven_client = ElevenLabs(api_key=ELEVEN_API_KEY) if ELEVEN_API_KEY else None
        
        self.bg_folder = "assets/backgrounds"
        os.makedirs(self.bg_folder, exist_ok=True)

    def get_background_image(self):
        # 1. Try local folder
        if os.path.exists(self.bg_folder) and os.listdir(self.bg_folder):
            img_name = random.choice(os.listdir(self.bg_folder))
            return os.path.join(self.bg_folder, img_name)
        
        # 2. Fetch from Unsplash (Fallback/Strategy)
        if UNSPLASH_ACCESS_KEY:
            try:
                url = f"https://api.unsplash.com/photos/random?query=nature,abstract,texture&client_id={UNSPLASH_ACCESS_KEY}"
                resp = requests.get(url).json()
                img_url = resp['urls']['regular']
                img_data = requests.get(img_url).content
                img = Image.open(BytesIO(img_data))
                img = img.filter(ImageFilter.GaussianBlur(radius=15))
                path = os.path.join(self.bg_folder, "temp_bg.jpg")
                img.save(path)
                return path
            except Exception as e:
                print(f"Unsplash failed: {e}")
        
        # Fallback: Generate solid color image
        img = Image.new('RGB', (1080, 1920), color = (random.randint(0,255), random.randint(0,255), random.randint(0,255)))
        path = "assets/solid_bg.jpg"
        img.save(path)
        return path

    def generate_audio(self, text, voice_type="default"):
        audio_path = "assets/temp_audio.mp3"
        
        # Primary: ElevenLabs (Natural Voice) - Updated API
        if self.eleven_client:
            try:
                # استخدام الطريقة الجديدة للعميل
                audio_generator = self.eleven_client.generate(
                    text=text,
                    voice="Rachel", # استخدام اسم الصوت مباشرة أو ID
                    model="eleven_monolingual_v1"
                )
                # حفظ البايتات في ملف
                with open(audio_path, 'wb') as f:
                    for chunk in audio_generator:
                        f.write(chunk)
                return audio_path
            except Exception as e:
                print(f"ElevenLabs failed: {e}")

        # Fallback: OpenAI TTS
        if OPENAI_API_KEY:
            try:
                import openai
                openai.api_key = OPENAI_API_KEY
                response = openai.audio.speech.create(
                    model="tts-1",
                    voice="alloy",
                    input=text
                )
                response.stream_to_file(audio_path)
                return audio_path
            except Exception as e:
                print(f"OpenAI TTS failed: {e}")

        # Critical Fallback: gTTS (Robotic, but guarantees output)
        from gtts import gTTS
        tts = gTTS(text=text, lang='en')
        tts.save(audio_path)
        return audio_path

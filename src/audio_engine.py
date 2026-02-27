import os
import random
import subprocess
from pydub import AudioSegment
import requests
from src.config import TEMP_DIR, FREESOUND_API

def generate_tts(text, filename):
    filepath = os.path.join(TEMP_DIR, filename)
    # Using Edge TTS (Free, high quality)
    voice = random.choice(["en-US-ChristopherNeural", "en-US-GuyNeural", "en-GB-RyanNeural"])
    subprocess.run(["edge-tts", "--voice", voice, "--text", text, "--write-media", filepath], check=True)
    
    # Apply random speed variation (±2%) to avoid spam detection
    audio = AudioSegment.from_file(filepath)
    speed_factor = random.uniform(0.98, 1.02)
    altered_audio = audio._spawn(audio.raw_data, overrides={
        "frame_rate": int(audio.frame_rate * speed_factor)
    }).set_frame_rate(audio.frame_rate)
    
    altered_audio.export(filepath, format="mp3")
    return filepath

def get_sfx(sfx_type):
    # Fallback local files if API fails
    filepath = os.path.join(TEMP_DIR, f"{sfx_type}.mp3")
    if os.path.exists(filepath): return filepath
    
    query = "tick tock" if sfx_type == "timer" else "ding"
    url = f"https://freesound.org/apiv2/search/text/?query={query}&token={FREESOUND_API}&fields=id,name,previews"
    try:
        res = requests.get(url).json()
        audio_url = res['results'][0]['previews']['preview-hq-mp3']
        audio_data = requests.get(audio_url).content
        with open(filepath, "wb") as f:
            f.write(audio_data)
        return filepath
    except:
        # Create silent audio as absolute fallback
        AudioSegment.silent(duration=1000).export(filepath, format="mp3")
        return filepath

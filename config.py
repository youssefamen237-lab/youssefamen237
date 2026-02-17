import os
from dotenv import load_dotenv
import random

load_dotenv()

class Config:
    # API Keys (Matching Provided Secrets)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
    UNSPLASH_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    
    # YouTube OAuth (Matching Provided Secrets Exactly)
    YT_CLIENT_ID = os.getenv("YT_CLIENT_ID_3")
    YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET_3")
    YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN_3")
    CHANNEL_ID = os.getenv("YT_CHANNEL_ID")

    # Content Settings
    TARGET_AUDIENCE = "American"
    SAFE_AREA_PADDING = 100
    
    # Templates
    TEMPLATES = [
        "True / False",
        "Multiple Choice",
        "Direct Question",
        "Guess the Answer",
        "Quick Challenge",
        "Only Geniuses",
        "Memory Test",
        "Visual Question"
    ]

    # Voice Settings
    VOICE_ID = "Josh"
    
    # Safety
    MAX_RETRIES = 3
    
    @staticmethod
    def get_random_template():
        return random.choice(Config.TEMPLATES)

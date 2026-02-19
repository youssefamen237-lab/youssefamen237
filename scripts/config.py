import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Config:
    # LLM keys
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    # TTS
    ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
    ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "Adam")  # default voice

    # YouTube OAuth
    YT_CLIENT_ID = os.getenv("YT_CLIENT_ID_3")
    YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET_3")
    YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN_3")
    YT_CHANNEL_ID = os.getenv("YT_CHANNEL_ID")

    # Misc
    LOG_DIR = BASE_DIR / "data" / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Paths
    BACKGROUND_DIR = BASE_DIR / "assets" / "backgrounds"
    FONT_PATH = BASE_DIR / "assets" / "fonts" / "Roboto-Bold.ttf"
    SHORT_VIDEO_DIR = BASE_DIR / "data" / "short_videos"
    THUMBNAIL_DIR = BASE_DIR / "data" / "thumbnails"
    STRATEGY_PATH = BASE_DIR / "data" / "strategy.json"
    DB_PATH = BASE_DIR / "data" / "duplicate.db"

    # Ensure directories exist
    SHORT_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

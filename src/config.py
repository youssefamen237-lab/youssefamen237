import os

# API Keys from GitHub Secrets
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
FREESOUND_API = os.getenv("FREESOUND_API")

# YouTube Credentials
YT_CLIENT_ID_1 = os.getenv("YT_CLIENT_ID_1")
YT_CLIENT_SECRET_1 = os.getenv("YT_CLIENT_SECRET_1")
YT_REFRESH_TOKEN_1 = os.getenv("YT_REFRESH_TOKEN_1")

# Channel Info
CHANNEL_NAME = "@Quiz Plus"
WATERMARK_OPACITY = 0.3

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DB_FILE = os.path.join(BASE_DIR, "database.json")

# Create directories if they don't exist
for d in [TEMP_DIR, OUTPUT_DIR, ASSETS_DIR]:
    os.makedirs(d, exist_ok=True)

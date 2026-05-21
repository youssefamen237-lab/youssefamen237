"""
config/settings.py
Karma Vault Stories — Central Configuration & Secret Mapping
All environment variable names are 1:1 with confirmed GitHub Secrets.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
# BASE PATHS (CI-safe, relative to repo root)
# ─────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STORY_BANK_DIR = DATA_DIR / "story_bank"
ANALYTICS_DIR = DATA_DIR / "analytics"
HEURISTICS_DIR = DATA_DIR / "heuristics"
EMERGENCY_EXPORT_DIR = DATA_DIR / "emergency_export"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
AUDIO_DIR = ASSETS_DIR / "audio"
MUSIC_DIR = AUDIO_DIR / "music"
SFX_DIR = AUDIO_DIR / "sfx"
LOGS_DIR = ROOT_DIR / "logs"
WORKSPACE_DIR = Path(os.environ.get("GITHUB_WORKSPACE", str(ROOT_DIR)))

for _d in [
    DATA_DIR, STORY_BANK_DIR, ANALYTICS_DIR, HEURISTICS_DIR,
    EMERGENCY_EXPORT_DIR, ASSETS_DIR, FONTS_DIR, AUDIO_DIR,
    MUSIC_DIR, SFX_DIR, LOGS_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# AI / WRITING MODEL SECRETS
# ─────────────────────────────────────────────
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY        = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY      = os.environ.get("OPENROUTER_KEY", "")
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY", "")

WRITING_MODEL_CHAIN = [
    {
        "provider": "gemini",
        "model": "gemini-1.5-pro",
        "api_key_env": "GEMINI_API_KEY",
        "key": GEMINI_API_KEY,
    },
    {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
        "key": GROQ_API_KEY,
    },
    {
        "provider": "openrouter",
        "model": "anthropic/claude-3.5-haiku",
        "api_key_env": "OPENROUTER_KEY",
        "key": OPENROUTER_KEY,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "key": OPENAI_API_KEY,
    },
]

# ─────────────────────────────────────────────
# TTS / VOICE SECRETS
# ─────────────────────────────────────────────
ELEVEN_API_KEY              = os.environ.get("ELEVEN_API_KEY", "")
ELEVENLABS_VOICE_ID_MALE    = os.environ.get("ELEVENLABS_VOICE_ID_MALE", "")
ELEVENLABS_VOICE_ID_FEMALE  = os.environ.get("ELEVENLABS_VOICE_ID_FEMALE", "")
CAMB_AI_KEY_1               = os.environ.get("CAMB_AI_KEY_1", "")
DEEPGRAM_API_KEY            = os.environ.get("DEEPGRAM_API_KEY", "")
ASSEMBLYAI                  = os.environ.get("ASSEMBLYAI", "")

TTS_PROVIDER_CHAIN = [
    {
        "provider": "elevenlabs",
        "api_key_env": "ELEVEN_API_KEY",
        "key": ELEVEN_API_KEY,
        "voice_male": ELEVENLABS_VOICE_ID_MALE,
        "voice_female": ELEVENLABS_VOICE_ID_FEMALE,
        "base_url": "https://api.elevenlabs.io/v1",
    },
    {
        "provider": "camb_ai",
        "api_key_env": "CAMB_AI_KEY_1",
        "key": CAMB_AI_KEY_1,
        "base_url": "https://client.camb.ai/apis",
    },
    {
        "provider": "edge_tts",
        "api_key_env": None,
        "key": None,
        "voice_male": "en-US-GuyNeural",
        "voice_female": "en-US-AriaNeural",
    },
]

# ─────────────────────────────────────────────
# VISUAL / STOCK IMAGE SECRETS
# ─────────────────────────────────────────────
PEXELS_API_KEY              = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY             = os.environ.get("PIXABAY_API_KEY", "")
UNSPLASH_ACCESS_KEY         = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_ID                 = os.environ.get("UNSPLASH_ID", "")
UNSPLASH_SECRET_KEY         = os.environ.get("UNSPLASH_SECRET_KEY", "")
FREEPIK_API_KEY             = os.environ.get("FREEPIK_API_KEY", "")
GETIMG_API_KEY              = os.environ.get("GETIMG_API_KEY", "")
REPLICATE_API_TOKEN         = os.environ.get("REPLICATE_API_TOKEN", "")
HF_API_TOKEN                = os.environ.get("HF_API_TOKEN", "")
COVERR_API_ID               = os.environ.get("COVERR_API_ID", "")
COVERR_API_KEY              = os.environ.get("COVERR_API_KEY", "")
VECTEEZY_ID                 = os.environ.get("VECTEEZY_ID", "")
VECTEEZY_SECRET_KEY         = os.environ.get("VECTEEZY_SECRET_KEY", "")
INTERNET_ARCHIVE_ACCESS_KEY = os.environ.get("INTERNET_ARCHIVE_ACCESS_KEY", "")
INTERNET_ARCHIVE_SECRET_KEY = os.environ.get("INTERNET_ARCHIVE_SECRET_KEY", "")
NASA_API_KEY                = os.environ.get("NASA_API_KEY", "")
REMOVE_BG_API               = os.environ.get("REMOVE_BG_API", "")

VISUAL_SOURCE_CHAIN = [
    # ── Keyed stock providers (rate-limited but high quality) ──────
    {
        "provider":    "pexels",
        "api_key_env": "PEXELS_API_KEY",
        "key":         PEXELS_API_KEY,
        "base_url":    "https://api.pexels.com/v1",
        "type":        "stock",
    },
    {
        "provider":    "pixabay",
        "api_key_env": "PIXABAY_API_KEY",
        "key":         PIXABAY_API_KEY,
        "base_url":    "https://pixabay.com/api",
        "type":        "stock",
    },
    {
        "provider":    "unsplash",
        "api_key_env": "UNSPLASH_ACCESS_KEY",
        "key":         UNSPLASH_ACCESS_KEY,
        "base_url":    "https://api.unsplash.com",
        "type":        "stock",
    },
    {
        "provider":    "coverr",
        "api_key_env": "COVERR_API_KEY",
        "key":         COVERR_API_KEY,
        "base_url":    "https://api.coverr.co",
        "type":        "video",
    },
    {
        "provider":    "internet_archive",
        "api_key_env": "INTERNET_ARCHIVE_ACCESS_KEY",
        "key":         INTERNET_ARCHIVE_ACCESS_KEY,
        "base_url":    "https://archive.org",
        "type":        "stock",
    },
    # ── Zero-API-key free providers (unlimited, always available) ──
    # Positioned BEFORE AI generation so they are tried first when
    # keyed stock providers are exhausted or rate-limited.
    {
        "provider":    "wikimedia",
        "api_key_env": None,
        "key":         "no_key_required",   # sentinel — always active
        "base_url":    "https://commons.wikimedia.org",
        "type":        "stock",
    },
    {
        "provider":    "openverse",
        "api_key_env": None,
        "key":         "no_key_required",   # sentinel — always active
        "base_url":    "https://api.openverse.org",
        "type":        "stock",
    },
    # ── AI generation providers (last resort, uses API credits) ───
    {
        "provider":    "getimg",
        "api_key_env": "GETIMG_API_KEY",
        "key":         GETIMG_API_KEY,
        "base_url":    "https://api.getimg.ai/v1",
        "type":        "ai_generation",
    },
    {
        "provider":    "replicate",
        "api_key_env": "REPLICATE_API_TOKEN",
        "key":         REPLICATE_API_TOKEN,
        "base_url":    "https://api.replicate.com/v1",
        "type":        "ai_generation",
    },
    {
        "provider":    "huggingface",
        "api_key_env": "HF_API_TOKEN",
        "key":         HF_API_TOKEN,
        "base_url":    "https://api-inference.huggingface.co",
        "type":        "ai_generation",
    },
]

# ─────────────────────────────────────────────
# SEARCH / TREND SECRETS
# ─────────────────────────────────────────────
SERPAPI         = os.environ.get("SERPAPI", "")
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "")
ZENSERP         = os.environ.get("ZENSERP", "")
NEWS_API        = os.environ.get("NEWS_API", "")
FREESOUND_API   = os.environ.get("FREESOUND_API", "")
FREESOUND_ID    = os.environ.get("FREESOUND_ID", "")

SEARCH_PROVIDER_CHAIN = [
    {
        "provider": "tavily",
        "api_key_env": "TAVILY_API_KEY",
        "key": TAVILY_API_KEY,
        "base_url": "https://api.tavily.com",
    },
    {
        "provider": "serpapi",
        "api_key_env": "SERPAPI",
        "key": SERPAPI,
        "base_url": "https://serpapi.com",
    },
    {
        "provider": "zenserp",
        "api_key_env": "ZENSERP",
        "key": ZENSERP,
        "base_url": "https://app.zenserp.com/api/v2",
    },
    {
        "provider": "newsapi",
        "api_key_env": "NEWS_API",
        "key": NEWS_API,
        "base_url": "https://newsapi.org/v2",
    },
]

# ─────────────────────────────────────────────
# YOUTUBE UPLOAD SECRETS (3 credential packs)
# ─────────────────────────────────────────────
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YT_CHANNEL_ID   = os.environ.get("YT_CHANNEL_ID", "")

YOUTUBE_CREDENTIAL_PACKS = [
    {
        "pack_id":       1,
        "client_id":     os.environ.get("YT_CLIENT_ID_1", ""),
        "client_secret": os.environ.get("YT_CLIENT_SECRET_1", ""),
        "refresh_token": os.environ.get("YT_REFRESH_TOKEN_1", ""),
    },
    {
        "pack_id":       2,
        "client_id":     os.environ.get("YT_CLIENT_ID_2", ""),
        "client_secret": os.environ.get("YT_CLIENT_SECRET_2", ""),
        "refresh_token": os.environ.get("YT_REFRESH_TOKEN_2", ""),
    },
    {
        "pack_id":       3,
        "client_id":     os.environ.get("YT_CLIENT_ID_3", ""),
        "client_secret": os.environ.get("YT_CLIENT_SECRET_3", ""),
        "refresh_token": os.environ.get("YT_REFRESH_TOKEN_3", ""),
    },
]

ACTIVE_YT_PACKS = [
    p for p in YOUTUBE_CREDENTIAL_PACKS
    if p["client_id"] and p["client_secret"] and p["refresh_token"]
]

# ─────────────────────────────────────────────
# AUDIO / SFX SECRETS
# ─────────────────────────────────────────────
FREESOUND_CREDENTIALS = {
    "api_key":   FREESOUND_API,
    "client_id": FREESOUND_ID,
    "base_url":  "https://freesound.org/apiv2",
}

# ─────────────────────────────────────────────
# RUNTIME BEHAVIOR TUNING
# ─────────────────────────────────────────────
MAX_IMAGES_PER_SCENE        = 3
MAX_VISUAL_ASSETS_LONG      = 55
MIN_VISUAL_ASSETS_LONG      = 35
SCENE_DURATION_MIN_SEC      = 3
SCENE_DURATION_MAX_SEC      = 6
LONG_VIDEO_MIN_MINUTES      = 8
LONG_VIDEO_MAX_MINUTES      = 12
SHORT_VIDEO_MIN_SEC         = 35
SHORT_VIDEO_MAX_SEC         = 50
SHORT_CUT_INTERVAL_SEC      = 2.0
API_REQUEST_TIMEOUT_SEC     = 30
API_RETRY_ATTEMPTS          = 3
API_RETRY_BACKOFF_SEC       = 2
MAX_STORY_CANDIDATES        = 40
MIN_STORY_CANDIDATES        = 20

VIDEO_WIDTH                 = 1920
VIDEO_HEIGHT                = 1080
SHORT_WIDTH                 = 1080
SHORT_HEIGHT                = 1920
VIDEO_FPS                   = 24
VIDEO_BITRATE               = "4000k"
AUDIO_BITRATE               = "192k"
AUDIO_SAMPLE_RATE           = 44100

FFMPEG_THREADS              = 2
FFMPEG_PRESET               = "faster"
FFMPEG_CRF                  = 23

# ─────────────────────────────────────────────
# VALIDATION HELPER
# ─────────────────────────────────────────────
def validate_critical_secrets() -> dict:
    return {
        "writing_available": any(p["key"] for p in WRITING_MODEL_CHAIN),
        "tts_available":     bool(ELEVEN_API_KEY or CAMB_AI_KEY_1) or True,
        "visuals_available": any(p["key"] for p in VISUAL_SOURCE_CHAIN),
        "search_available":  any(p["key"] for p in SEARCH_PROVIDER_CHAIN),
        "youtube_available": bool(ACTIVE_YT_PACKS),
        "active_yt_packs":   len(ACTIVE_YT_PACKS),
        "writing_primary":   next((p["provider"] for p in WRITING_MODEL_CHAIN if p["key"]), "none"),
        "tts_primary":       next((p["provider"] for p in TTS_PROVIDER_CHAIN if p.get("key")), "edge_tts"),
        "visual_primary":    next((p["provider"] for p in VISUAL_SOURCE_CHAIN if p["key"]), "wikimedia"),
        "search_primary":    next((p["provider"] for p in SEARCH_PROVIDER_CHAIN if p["key"]), "none"),
    }

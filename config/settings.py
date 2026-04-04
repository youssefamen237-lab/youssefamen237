"""
config/settings.py
==================
Global constants for MindCraft Psychology automation pipeline.
All values are either hard-coded project defaults or read from
environment variables via api_keys.py.  No logic lives here —
only configuration primitives.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Bootstrap ──────────────────────────────────────────────────────────────
# Load .env when running locally; GitHub Actions injects env vars directly.
load_dotenv()

# ── Project Root ───────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════════
# VIDEO DIMENSIONS & TIMING
# ══════════════════════════════════════════════════════════════════════════

# YouTube Shorts aspect ratio (9:16 vertical)
VIDEO_WIDTH: int  = 1080
VIDEO_HEIGHT: int = 1920
VIDEO_FPS: int    = 30

# Frame durations (seconds)
FRAME_HOOK_DURATION:   float = 1.5   # Frame 1 — hook / pattern interrupt
FRAME_BODY_DURATION:   float = 5.5   # Frame 2 — psychological fact (5–6 s)
FRAME_CTA_DURATION:    float = 1.0   # Frame 3 — call to action

# Total Short duration (sum of the three frames)
SHORT_TOTAL_DURATION:  float = FRAME_HOOK_DURATION + FRAME_BODY_DURATION + FRAME_CTA_DURATION
# => 8.0 seconds (within the 7–8 s target)

# Slow-zoom magnitude — 1.0 = no zoom, 1.08 = 8% zoom over the clip
SLOW_ZOOM_FACTOR: float = 1.08

# Weekly compilation: max clips to stitch (= 4 Shorts/day × 7 days)
COMPILATION_MAX_CLIPS: int = 28


# ══════════════════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════════════════

# Assets bundled in the repo
ASSETS_DIR:    Path = BASE_DIR / "assets"
FONTS_DIR:     Path = ASSETS_DIR / "fonts"
CTA_DIR:       Path = ASSETS_DIR / "cta"

BEBAS_NEUE_FONT: Path = FONTS_DIR / "BebasNeue-Regular.ttf"
CTA_VIDEO_PATH:  Path = CTA_DIR  / "cta_frame.mp4"

# Runtime output (gitignored)
OUTPUT_DIR:          Path = BASE_DIR / Path(os.getenv("OUTPUT_DIR",          "output"))
OUTPUT_AUDIO_DIR:    Path = BASE_DIR / Path(os.getenv("OUTPUT_AUDIO_DIR",    "output/audio"))
OUTPUT_CLIPS_DIR:    Path = BASE_DIR / Path(os.getenv("OUTPUT_CLIPS_DIR",    "output/clips"))
OUTPUT_SHORTS_DIR:   Path = BASE_DIR / Path(os.getenv("OUTPUT_SHORTS_DIR",   "output/shorts"))
OUTPUT_COMPILATIONS: Path = BASE_DIR / Path(os.getenv("OUTPUT_COMPILATIONS_DIR", "output/compilations"))

# SQLite database
DB_PATH: Path = BASE_DIR / Path(os.getenv("DB_PATH", "database/mindcraft.db"))

# YouTube OAuth token cache directory (gitignored)
TOKENS_DIR: Path = BASE_DIR / ".tokens"


# ══════════════════════════════════════════════════════════════════════════
# TYPOGRAPHY & COLOURS
# ══════════════════════════════════════════════════════════════════════════

# Caption colours (RGB tuples for Pillow)
COLOR_HOOK_TEXT:  tuple = (255, 230, 0)    # Yellow — hook frame
COLOR_BODY_TEXT:  tuple = (255, 255, 255)  # White  — body frame
COLOR_CTA_TEXT:   tuple = (255, 255, 255)  # White  — CTA frame
COLOR_TEXT_SHADOW: tuple = (0, 0, 0)       # Black drop-shadow behind all text
COLOR_HOOK_BG:    tuple = (0, 0, 0, 180)   # Semi-transparent black band (RGBA)

# Font sizes (px at 1080×1920)
FONT_SIZE_HOOK: int = 90    # Large, punchy hook text
FONT_SIZE_BODY: int = 72    # Body fact — readable on mobile
FONT_SIZE_CTA:  int = 60    # CTA overlay

# Caption position — centred horizontally, 55% down the frame
CAPTION_Y_RATIO: float = 0.55

# Max characters per caption line before forced wrap
CAPTION_MAX_CHARS_PER_LINE: int = 22

# Text shadow offset (px)
SHADOW_OFFSET: tuple = (4, 4)

# Text stroke width (px) — thin outline for legibility on any background
TEXT_STROKE_WIDTH: int = 2
TEXT_STROKE_COLOR: tuple = (0, 0, 0)


# ══════════════════════════════════════════════════════════════════════════
# CHANNEL IDENTITY
# ══════════════════════════════════════════════════════════════════════════

CHANNEL_NAME:  str = "MindCraft Psychology"
CHANNEL_NICHE: str = os.getenv("CHANNEL_NICHE", "psychology facts")
CHANNEL_VOICE: str = os.getenv("CHANNEL_VOICE", "en-US-GuyNeural")

# Target countries for metadata / keyword optimisation
TARGET_COUNTRIES: list[str] = ["US", "GB", "CA", "AU"]

# YouTube category ID — Education = 27
YT_CATEGORY_ID: str = "27"

# Default tags appended to every upload
YT_DEFAULT_TAGS: list[str] = [
    "psychology", "psychologyfacts", "mindset", "mentalhealth",
    "brainscience", "psychologytips", "behavioralpsychology",
    "cognitiveScience", "shorts", "youtubeshorts",
]

# CTA text rendered on Frame 3
CTA_TEXT: str = "Follow for daily psychology secrets"

# Daily upload quota
DAILY_SHORTS_COUNT: int = int(os.getenv("DAILY_SHORTS_COUNT", "4"))


# ══════════════════════════════════════════════════════════════════════════
# API ENDPOINTS & MODEL NAMES
# ══════════════════════════════════════════════════════════════════════════

# Gemini
GEMINI_MODEL:           str = "gemini-1.5-flash"          # free-tier model
GEMINI_MAX_OUTPUT_TOKENS: int = 1024
GEMINI_TEMPERATURE:     float = 0.85

# Groq (fallback)
GROQ_MODEL:             str = "llama3-8b-8192"            # free-tier model
GROQ_MAX_TOKENS:        int = 1024
GROQ_TEMPERATURE:       float = 0.85

# Tavily
TAVILY_MAX_RESULTS:     int = 5
TAVILY_SEARCH_DEPTH:    str = "basic"                     # "basic" stays free-tier

# Pexels
PEXELS_API_BASE:        str = "https://api.pexels.com/videos/search"
PEXELS_RESULTS_PER_PAGE: int = 10
PEXELS_MIN_CLIP_DURATION: int = 8   # seconds — must be ≥ Short total duration

# Pixabay (fallback)
PIXABAY_API_BASE:       str = "https://pixabay.com/api/videos/"
PIXABAY_RESULTS_PER_PAGE: int = 10

# Search queries for human-interaction stock footage
VISUAL_SEARCH_QUERIES: list[str] = [
    "people talking psychology",
    "human interaction social",
    "person thinking mindset",
    "friends conversation emotion",
    "crowd behavior social dynamics",
    "brain activity thinking",
]


# ══════════════════════════════════════════════════════════════════════════
# RETRY & RESILIENCE
# ══════════════════════════════════════════════════════════════════════════

# Tenacity retry settings used by utils/retry.py
RETRY_MAX_ATTEMPTS:   int   = 3
RETRY_WAIT_MIN_SEC:   float = 2.0
RETRY_WAIT_MAX_SEC:   float = 10.0
RETRY_MULTIPLIER:     float = 1.5   # exponential backoff multiplier


# ══════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE:  Path = BASE_DIR / "logs" / "pipeline.log"


# ══════════════════════════════════════════════════════════════════════════
# SCRIPT GENERATION — PROMPT SCHEMA
# ══════════════════════════════════════════════════════════════════════════
# The LLM must return exactly this JSON structure.
# script_generator.py validates against this schema via Pydantic.

SCRIPT_JSON_SCHEMA: dict = {
    "hook": "string — 1 punchy sentence, max 12 words, open loop pattern interrupt",
    "body": "string — 1–2 sentences, the psychological fact, max 30 words",
    "cta":  "string — fixed: 'Follow for daily psychology secrets'",
    "title": "string — YouTube title, max 60 chars, SEO-optimised",
    "description": "string — YouTube description, 2–3 sentences, includes hashtags",
    "tags": "array of strings — 10 relevant YouTube tags",
    "topic": "string — the broad psychology topic this fact belongs to",
}

SCRIPT_SYSTEM_PROMPT: str = (
    "You are a viral psychology content writer for YouTube Shorts. "
    "You write for a Tier-1 English-speaking audience (US, UK, Canada). "
    "Your hooks use pattern interrupts and open loops. "
    "Your body sentences are mind-blowing yet factual. "
    "Always return ONLY a valid JSON object — no markdown, no preamble, no explanation. "
    f"The JSON must match this schema exactly: {SCRIPT_JSON_SCHEMA}"
)

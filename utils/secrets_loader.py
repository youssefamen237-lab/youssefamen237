"""
utils/secrets_loader.py – Quizzaro Secrets Loader
===================================================
Loads every required secret from environment variables.
Never reads from files. Never hardcodes values.
Raises a descriptive error if a critical secret is missing.
"""

from __future__ import annotations

import os
from typing import Optional


# Secrets that must be present for the system to operate at all
CRITICAL_SECRETS = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "PEXELS_API_KEY",
    "FREESOUND_API",
    "FREESOUND_ID",
    "YOUTUBE_API_KEY",
    "YT_CHANNEL_ID",
    "YT_CLIENT_ID_1",
    "YT_CLIENT_SECRET_1",
    "YT_REFRESH_TOKEN_1",
    "YT_CLIENT_ID_2",
    "YT_CLIENT_SECRET_2",
    "YT_REFRESH_TOKEN_2",
    "YT_CLIENT_ID_3",
    "YT_CLIENT_SECRET_3",
    "YT_REFRESH_TOKEN_3",
]

# Full list of all known secrets (non-critical ones fall back to "")
ALL_SECRET_KEYS = [
    "API_FOOTBALL_KEY", "ASSEMBLYAI", "CAMB_AI_KEY_1",
    "COVERR_API_ID", "COVERR_API_KEY", "ELEVEN_API_KEY",
    "FOOTBALL_DATA_ORG", "FOOTBALL_DATA_TOKEN", "FREEPIK_API_KEY",
    "FREESOUND_API", "FREESOUND_ID", "GEMINI_API_KEY",
    "GETIMG_API_KEY", "GROQ_API_KEY", "HF_API_TOKEN",
    "INTERNET_ARCHIVE_ACCESS_KEY", "INTERNET_ARCHIVE_SECRET_KEY",
    "NASA_API_KEY", "NEWS_API", "NOAA_API_KEY",
    "OPENAI_API_KEY", "OPENROUTER_KEY", "PEXELS_API_KEY",
    "PIXABAY_API_KEY", "REMOVE_BG_API", "REPLICATE_API_TOKEN",
    "SERPAPI", "TAVILY_API_KEY", "UNSPLASH_ACCESS_KEY",
    "UNSPLASH_ID", "UNSPLASH_SECRET_KEY", "VECTEEZY_ID",
    "VECTEEZY_SECRET_KEY", "YOUTUBE_API_KEY", "YT_CHANNEL_ID",
    "YT_CLIENT_ID_1", "YT_CLIENT_ID_2", "YT_CLIENT_ID_3",
    "YT_CLIENT_SECRET_1", "YT_CLIENT_SECRET_2", "YT_CLIENT_SECRET_3",
    "YT_REFRESH_TOKEN_1", "YT_REFRESH_TOKEN_2", "YT_REFRESH_TOKEN_3",
    "ZENSERP",
]


class SecretsLoader:

    @staticmethod
    def load_all() -> dict[str, str]:
        secrets: dict[str, str] = {}
        missing_critical: list[str] = []

        for key in ALL_SECRET_KEYS:
            value = os.environ.get(key, "")
            secrets[key] = value

        for key in CRITICAL_SECRETS:
            if not secrets.get(key):
                missing_critical.append(key)

        if missing_critical:
            raise EnvironmentError(
                f"[SecretsLoader] Missing critical secrets: {missing_critical}\n"
                "Ensure all secrets are configured in GitHub Actions → Settings → Secrets."
            )

        return secrets

    @staticmethod
    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, default)

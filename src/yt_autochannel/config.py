from __future__ import annotations

import os
from typing import List

from pydantic import BaseModel, Field


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return float(v.strip())
    except ValueError:
        return default


def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None:
        return default
    return v


def env_list(name: str, default: List[str]) -> List[str]:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return [x.strip() for x in v.split(",") if x.strip()]


class Settings(BaseModel):
    # Core
    run_enabled: bool = Field(default_factory=lambda: env_bool("RUN_ENABLED", True))
    dry_run: bool = Field(default_factory=lambda: env_bool("DRY_RUN", False))
    allow_paid_providers: bool = Field(default_factory=lambda: env_bool("ALLOW_PAID_PROVIDERS", False))

    # Paths
    repo_root: str = Field(default_factory=lambda: os.path.abspath(os.getenv("GITHUB_WORKSPACE", os.getcwd())))
    assets_dir: str = "assets"
    data_dir: str = "data"
    output_dir: str = "output"
    artifacts_dir: str = "artifacts"
    logs_dir: str = "logs"

    # Publishing policy
    timezone: str = Field(default_factory=lambda: env_str("TIMEZONE", "Africa/Cairo"))
    daily_shorts: int = Field(default_factory=lambda: env_int("DAILY_SHORTS", 4))
    weekly_longs: int = Field(default_factory=lambda: env_int("WEEKLY_LONGS", 3))

    # Daily hard cap (uploads)
    daily_upload_cap: int = Field(default_factory=lambda: env_int("DAILY_UPLOAD_CAP", 6))

    # Time slots (local time) for shorts; format HH:MM
    shorts_time_slots_local: List[str] = Field(
        default_factory=lambda: env_list("SHORTS_TIME_SLOTS_LOCAL", ["10:15", "14:20", "18:25", "22:30"])
    )
    # jitter in seconds (+/-)
    shorts_jitter_seconds: int = Field(default_factory=lambda: env_int("SHORTS_JITTER_SECONDS", 600))

    # Long schedule (local time)
    long_time_local: str = Field(default_factory=lambda: env_str("LONG_TIME_LOCAL", "16:00"))
    # days of week for longs (Mon=0..Sun=6)
    long_days_of_week: List[int] = Field(default_factory=lambda: [0, 2, 4])  # Mon, Wed, Fri
    long_jitter_seconds: int = Field(default_factory=lambda: env_int("LONG_JITTER_SECONDS", 900))

    # Short timing
    countdown_seconds: int = Field(default_factory=lambda: env_int("COUNTDOWN_SECONDS", 3))
    answer_seconds: float = Field(default_factory=lambda: env_float("ANSWER_SECONDS", 1.0))

    # TTS
    tts_edge_voice_male: str = Field(default_factory=lambda: env_str("EDGE_VOICE_MALE", "en-US-GuyNeural"))
    tts_edge_voice_female: str = Field(default_factory=lambda: env_str("EDGE_VOICE_FEMALE", "en-US-JennyNeural"))
    ab_test_days: int = Field(default_factory=lambda: env_int("AB_TEST_DAYS", 7))

    # Music
    music_enabled_default: bool = Field(default_factory=lambda: env_bool("MUSIC_ENABLED", True))
    music_target_db: float = Field(default_factory=lambda: env_float("MUSIC_TARGET_DB", -27.0))

    # Rendering
    short_resolution: str = Field(default_factory=lambda: env_str("SHORT_RES", "1080x1920"))
    long_resolution: str = Field(default_factory=lambda: env_str("LONG_RES", "1920x1080"))
    fps: int = Field(default_factory=lambda: env_int("FPS", 30))

    # Brand / text layout
    brand_primary: str = Field(default_factory=lambda: env_str("BRAND_PRIMARY", "#00D1FF"))
    brand_secondary: str = Field(default_factory=lambda: env_str("BRAND_SECONDARY", "#FFFFFF"))
    brand_accent: str = Field(default_factory=lambda: env_str("BRAND_ACCENT", "#FFD166"))

    # Font: system font path (DejaVu is present on ubuntu-latest)
    font_path: str = Field(
        default_factory=lambda: env_str("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )

    # Anti-duplicate
    fuzzy_threshold: int = Field(default_factory=lambda: env_int("FUZZY_THRESHOLD", 88))
    dupe_lookback_days: int = Field(default_factory=lambda: env_int("DUPE_LOOKBACK_DAYS", 180))
    answer_cooldown_days: int = Field(default_factory=lambda: env_int("ANSWER_COOLDOWN_DAYS", 14))

    # Safety
    safety_blocklist_file: str = Field(default_factory=lambda: env_str("SAFETY_BLOCKLIST_FILE", "blocklist.txt"))

    # YouTube / OAuth
    yt_channel_id: str = Field(default_factory=lambda: env_str("YT_CHANNEL_ID", ""))
    yt_client_id: str = Field(default_factory=lambda: env_str("YT_CLIENT_ID_1", ""))
    yt_client_secret: str = Field(default_factory=lambda: env_str("YT_CLIENT_SECRET_1", ""))
    yt_refresh_token: str = Field(default_factory=lambda: env_str("YT_REFRESH_TOKEN_1", ""))

    # Analytics (optional)
    analytics_enabled: bool = Field(default_factory=lambda: env_bool("ANALYTICS_ENABLED", False))

    # Debug
    verbose: bool = Field(default_factory=lambda: env_bool("VERBOSE", True))


def load_settings() -> Settings:
    return Settings()

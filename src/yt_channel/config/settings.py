from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v.strip())
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None:
        return default
    return v


def _env_list(name: str, default: List[str]) -> List[str]:
    v = os.getenv(name)
    if v is None:
        return list(default)
    parts = [p.strip() for p in v.split(",")]
    return [p for p in parts if p]


def _repo_root() -> Path:
    # Resolve from this file: src/yt_channel/config/settings.py -> repo root
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _deep_get(d: Dict[str, Any], keys: Tuple[str, ...], default: Any) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


@dataclass(frozen=True)
class Settings:
    # Global
    repo_root: Path = field(default_factory=_repo_root)
    run_enabled: bool = field(default_factory=lambda: _env_bool("RUN_ENABLED", True))
    dry_run: bool = field(default_factory=lambda: _env_bool("DRY_RUN", False))
    allow_paid_providers: bool = field(default_factory=lambda: _env_bool("ALLOW_PAID_PROVIDERS", False))
    timezone: str = field(default_factory=lambda: _env_str("TIMEZONE", "UTC"))

    # Output
    out_dir: Path = field(init=False)
    artifacts_dir: Path = field(init=False)
    state_dir: Path = field(init=False)

    # Video production
    shorts_per_day: int = field(default_factory=lambda: _env_int("SHORTS_PER_DAY", 4))
    longs_per_week: int = field(default_factory=lambda: _env_int("LONGS_PER_WEEK", 3))
    daily_hard_cap_uploads: int = field(default_factory=lambda: _env_int("DAILY_HARD_CAP_UPLOADS", 6))

    shorts_resolution: str = field(default_factory=lambda: _env_str("SHORTS_RESOLUTION", "1080x1920"))
    shorts_fps: int = field(default_factory=lambda: _env_int("SHORTS_FPS", 30))
    shorts_countdown_seconds: int = field(default_factory=lambda: _env_int("SHORTS_COUNTDOWN_SECONDS", 3))
    shorts_answer_seconds: float = field(default_factory=lambda: _env_float("SHORTS_ANSWER_SECONDS", 1.0))

    long_resolution: str = field(default_factory=lambda: _env_str("LONG_RESOLUTION", "1920x1080"))
    long_fps: int = field(default_factory=lambda: _env_int("LONG_FPS", 30))
    long_target_minutes_min: float = field(default_factory=lambda: _env_float("LONG_TARGET_MIN", 8.0))
    long_target_minutes_max: float = field(default_factory=lambda: _env_float("LONG_TARGET_MAX", 12.0))
    long_countdown_seconds: int = field(default_factory=lambda: _env_int("LONG_COUNTDOWN_SECONDS", 7))
    long_answer_seconds: float = field(default_factory=lambda: _env_float("LONG_ANSWER_SECONDS", 2.0))

    # Music
    music_enabled_default: bool = field(default_factory=lambda: _env_bool("MUSIC_ENABLED_DEFAULT", True))
    music_volume_db: float = field(default_factory=lambda: _env_float("MUSIC_VOLUME_DB", -28.0))

    # Templates
    shorts_templates: List[str] = field(default_factory=lambda: _env_list(
        "SHORTS_TEMPLATES",
        ["classic", "mcq", "true_false", "two_step", "zoom_reveal"],
    ))

    # Scheduling
    shorts_time_slots_utc: List[str] = field(default_factory=lambda: _env_list(
        "SHORTS_TIME_SLOTS_UTC",
        ["09:15", "13:15", "17:15", "21:15"],
    ))
    long_days_utc: List[str] = field(default_factory=lambda: _env_list(
        "LONG_DAYS_UTC",
        ["TUE", "THU", "SAT"],
    ))
    long_time_slot_utc: str = field(default_factory=lambda: _env_str("LONG_TIME_SLOT_UTC", "19:30"))
    schedule_jitter_minutes: int = field(default_factory=lambda: _env_int("SCHEDULE_JITTER_MINUTES", 12))

    # Question bank
    question_bank_dir: Path = field(init=False)
    datasets_dir: Path = field(init=False)
    banned_keywords_file: Path = field(init=False)

    # Assets
    assets_dir: Path = field(init=False)
    user_assets_dir: Path = field(init=False)
    backgrounds_dir: Path = field(init=False)
    music_dir: Path = field(init=False)
    fonts_dir: Path = field(init=False)

    # Providers
    tts_provider_chain: List[str] = field(default_factory=lambda: _env_list(
        "TTS_PROVIDER_CHAIN",
        ["edge", "espeak"],
    ))
    tts_voice_female: str = field(default_factory=lambda: _env_str("TTS_VOICE_FEMALE", "en-US-JennyNeural"))
    tts_voice_male: str = field(default_factory=lambda: _env_str("TTS_VOICE_MALE", "en-US-GuyNeural"))

    bg_provider_chain: List[str] = field(default_factory=lambda: _env_list(
        "BG_PROVIDER_CHAIN",
        ["local", "generated", "pexels"],
    ))
    music_provider_chain: List[str] = field(default_factory=lambda: _env_list(
        "MUSIC_PROVIDER_CHAIN",
        ["local", "generated", "freesound"],
    ))

    # SEO
    max_hashtags: int = field(default_factory=lambda: _env_int("MAX_HASHTAGS", 5))
    min_hashtags: int = field(default_factory=lambda: _env_int("MIN_HASHTAGS", 3))

    # YouTube
    yt_channel_id: str = field(default_factory=lambda: _env_str("YT_CHANNEL_ID", ""))
    yt_category_id_shorts: str = field(default_factory=lambda: _env_str("YT_CATEGORY_ID_SHORTS", "24"))
    yt_category_id_long: str = field(default_factory=lambda: _env_str("YT_CATEGORY_ID_LONG", "24"))

    yt_client_id: str = field(default_factory=lambda: _env_str("YT_CLIENT_ID", os.getenv("YT_CLIENT_ID_1", "")))
    yt_client_secret: str = field(default_factory=lambda: _env_str("YT_CLIENT_SECRET", os.getenv("YT_CLIENT_SECRET_1", "")))
    yt_refresh_token: str = field(default_factory=lambda: _env_str("YT_REFRESH_TOKEN", os.getenv("YT_REFRESH_TOKEN_1", "")))

    # Analytics
    analytics_enabled: bool = field(default_factory=lambda: _env_bool("ANALYTICS_ENABLED", True))
    analytics_days_back: int = field(default_factory=lambda: _env_int("ANALYTICS_DAYS_BACK", 30))

    # Advanced dedupe
    fuzzy_threshold: int = field(default_factory=lambda: _env_int("FUZZY_THRESHOLD", 88))
    answer_cooldown_days: int = field(default_factory=lambda: _env_int("ANSWER_COOLDOWN_DAYS", 30))

    # Remote APIs (optional)
    pexels_api_key: str = field(default_factory=lambda: _env_str("PEXELS_API_KEY", ""))
    pixabay_api_key: str = field(default_factory=lambda: _env_str("PIXABAY_API_KEY", ""))
    unsplash_access_key: str = field(default_factory=lambda: _env_str("UNSPLASH_ACCESS_KEY", ""))

    freesound_token: str = field(default_factory=lambda: _env_str("FREESOUND_API", ""))

    # LLM
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", False))
    llm_provider_chain: List[str] = field(default_factory=lambda: _env_list("LLM_PROVIDER_CHAIN", ["none"]))
    openai_api_key: str = field(default_factory=lambda: _env_str("OPENAI_API_KEY", ""))
    gemini_api_key: str = field(default_factory=lambda: _env_str("GEMINI_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: _env_str("GROQ_API_KEY", ""))
    openrouter_key: str = field(default_factory=lambda: _env_str("OPENROUTER_KEY", ""))

    def __post_init__(self) -> None:
        object.__setattr__(self, "out_dir", self.repo_root / "output_videos")
        object.__setattr__(self, "artifacts_dir", self.repo_root / "artifacts")
        object.__setattr__(self, "state_dir", self.repo_root / "state")

        object.__setattr__(self, "question_bank_dir", self.repo_root / "question_bank")
        object.__setattr__(self, "datasets_dir", self.question_bank_dir / "datasets")
        object.__setattr__(self, "banned_keywords_file", self.repo_root / "config" / "blocklist.txt")

        object.__setattr__(self, "assets_dir", self.repo_root / "assets")
        object.__setattr__(self, "user_assets_dir", self.repo_root / "user_assets")
        object.__setattr__(self, "backgrounds_dir", self.assets_dir / "backgrounds")
        object.__setattr__(self, "music_dir", self.assets_dir / "music")
        object.__setattr__(self, "fonts_dir", self.assets_dir / "fonts")

    # -----------------
    # Compatibility aliases
    # -----------------
    # Some modules refer to older/internal attribute names.
    # Keep these aliases to avoid runtime AttributeError.
    @property
    def jitter_minutes(self) -> int:
        return int(self.schedule_jitter_minutes)

    @property
    def short_countdown_seconds(self) -> int:
        return int(self.shorts_countdown_seconds)

    @property
    def short_answer_seconds(self) -> float:
        return float(self.shorts_answer_seconds)

    @staticmethod
    def from_yaml_defaults() -> "Settings":
        """Load defaults from config/defaults.yml, then allow env overrides."""
        repo_root = _repo_root()
        defaults_path = repo_root / "config" / "defaults.yml"
        d = _load_yaml(defaults_path)

        def get_bool(path: Tuple[str, ...], fallback: bool) -> bool:
            v = _deep_get(d, path, fallback)
            return bool(v) if isinstance(v, bool) else fallback

        def get_int(path: Tuple[str, ...], fallback: int) -> int:
            v = _deep_get(d, path, fallback)
            try:
                return int(v)
            except Exception:
                return fallback

        def get_float(path: Tuple[str, ...], fallback: float) -> float:
            v = _deep_get(d, path, fallback)
            try:
                return float(v)
            except Exception:
                return fallback

        def get_str(path: Tuple[str, ...], fallback: str) -> str:
            v = _deep_get(d, path, fallback)
            return str(v) if isinstance(v, (str, int, float)) else fallback

        def get_list(path: Tuple[str, ...], fallback: List[str]) -> List[str]:
            v = _deep_get(d, path, fallback)
            if isinstance(v, list):
                return [str(x) for x in v]
            return list(fallback)

        # Build a Settings with YAML defaults; env still overrides via helper fns inside Settings,
        # so we provide environment variables from YAML by setting os.environ only if missing.
        env_map: Dict[str, Any] = {
            "RUN_ENABLED": get_bool(("global", "run_enabled"), True),
            "DRY_RUN": get_bool(("global", "dry_run"), False),
            "ALLOW_PAID_PROVIDERS": get_bool(("global", "allow_paid_providers"), False),
            "SHORTS_PER_DAY": get_int(("production", "shorts_per_day"), 4),
            "LONGS_PER_WEEK": get_int(("production", "longs_per_week"), 3),
            "DAILY_HARD_CAP_UPLOADS": get_int(("production", "daily_hard_cap_uploads"), 6),
            "SHORTS_TIME_SLOTS_UTC": ",".join(get_list(("schedule", "shorts_time_slots_utc"), ["09:15", "13:15", "17:15", "21:15"])),
            "LONG_DAYS_UTC": ",".join(get_list(("schedule", "long_days_utc"), ["TUE", "THU", "SAT"])),
            "LONG_TIME_SLOT_UTC": get_str(("schedule", "long_time_slot_utc"), "19:30"),
            "SCHEDULE_JITTER_MINUTES": get_int(("schedule", "jitter_minutes"), 12),
            "MUSIC_ENABLED_DEFAULT": get_bool(("music", "enabled_default"), True),
            "MUSIC_VOLUME_DB": get_float(("music", "volume_db"), -28.0),
            "TTS_VOICE_FEMALE": get_str(("tts", "voice_female"), "en-US-JennyNeural"),
            "TTS_VOICE_MALE": get_str(("tts", "voice_male"), "en-US-GuyNeural"),
        }
        for k, v in env_map.items():
            if os.getenv(k) is None:
                os.environ[k] = str(v)
        return Settings()

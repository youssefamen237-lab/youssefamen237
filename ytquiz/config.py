from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from ytquiz.utils import TimeWindow, env_bool, env_float, env_int


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class Config:
    dry_run: bool

    channel_id: str
    oauth_clients: list[OAuthClient]

    shorts_per_day: int
    templates_count: int
    long_enabled: bool
    long_days: list[int]
    long_questions: int

    short_time_windows: list[TimeWindow]
    long_time_window: TimeWindow
    jitter_seconds: int

    answer_cooldown_days: int
    similarity_window: int

    voice_ab_days: int
    voice_explore_pct: float
    music_test_pct: float

    daily_upload_cap: int
    analytics_lookback_days: int

    root_dir: Path
    assets_dir: Path
    backgrounds_dir: Path
    music_dir: Path
    brand_dir: Path
    data_dir: Path
    datasets_dir: Path
    out_dir: Path
    cache_dir: Path

    piper_voice_female: str
    piper_voice_male: str
    piper_data_dir: Path

    overlay_font_file: Path
    ffmpeg_font_file: Path

    video_size: tuple[int, int]
    fps: int
    crf: int
    answer_reveal_seconds: float

    made_for_kids: bool
    category_id: str

    kill_switch: bool

    @staticmethod
    def from_env() -> "Config":
        root = Path(os.getenv("PROJECT_ROOT", ".")).resolve()
        assets = root / "assets"
        data = root / "data"
        out = root / "out"
        cache = root / ".cache"
        piper_dir = cache / "piper"

        channel_id = os.getenv("YT_CHANNEL_ID", "").strip()
        if not channel_id:
            raise RuntimeError("Missing env: YT_CHANNEL_ID")

        clients: list[OAuthClient] = []
        for idx in (1, 2):
            cid = os.getenv(f"YT_CLIENT_ID_{idx}", "").strip()
            cs = os.getenv(f"YT_CLIENT_SECRET_{idx}", "").strip()
            rt = os.getenv(f"YT_REFRESH_TOKEN_{idx}", "").strip()
            if cid and cs and rt:
                clients.append(OAuthClient(client_id=cid, client_secret=cs, refresh_token=rt))

        if not clients:
            raise RuntimeError("No OAuth clients found (need YT_CLIENT_ID_1/SECRET_1/REFRESH_TOKEN_1 at minimum)")

        short_windows = TimeWindow.parse_csv(
            os.getenv(
                "SHORT_SLOTS",
                "14:30-17:30,18:30-21:30,22:30-01:30,03:30-06:30,08:30-10:30,11:30-13:30",
            )
        )
        long_window = TimeWindow.parse_one(os.getenv("LONG_SLOT", "17:00-21:00"))

        long_days = _parse_weekdays(os.getenv("LONG_DAYS_UTC", "TUE,SAT"))

        font_path = Path(os.getenv("FONT_FILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

        return Config(
            dry_run=env_bool("DRY_RUN", False),
            channel_id=channel_id,
            oauth_clients=clients,
            shorts_per_day=env_int("SHORTS_PER_DAY", 4, 1, 8),
            templates_count=env_int("TEMPLATES_COUNT", 5, 3, 8),
            long_enabled=env_bool("LONG_ENABLED", True),
            long_days=long_days,
            long_questions=env_int("LONG_QUESTIONS", 38, 10, 80),
            short_time_windows=short_windows,
            long_time_window=long_window,
            jitter_seconds=env_int("SCHEDULE_JITTER_SECONDS", 420, 0, 1800),
            answer_cooldown_days=env_int("ANSWER_COOLDOWN_DAYS", 30, 1, 365),
            similarity_window=env_int("SIMILARITY_WINDOW", 250, 50, 5000),
            voice_ab_days=env_int("VOICE_AB_DAYS", 7, 3, 30),
            voice_explore_pct=env_float("VOICE_EXPLORE_PCT", 0.10, 0.0, 0.5),
            music_test_pct=env_float("MUSIC_TEST_PCT", 0.25, 0.0, 0.8),
            daily_upload_cap=env_int("DAILY_UPLOAD_CAP", 6, 1, 20),
            analytics_lookback_days=env_int("ANALYTICS_LOOKBACK_DAYS", 7, 1, 30),
            root_dir=root,
            assets_dir=assets,
            backgrounds_dir=assets / "backgrounds",
            music_dir=assets / "music",
            brand_dir=assets / "brand",
            data_dir=data,
            datasets_dir=data / "datasets",
            out_dir=out,
            cache_dir=cache,
            piper_voice_female=os.getenv("PIPER_VOICE_FEMALE", "en_US-amy-medium").strip() or "en_US-amy-medium",
            piper_voice_male=os.getenv("PIPER_VOICE_MALE", "en_US-ryan-medium").strip() or "en_US-ryan-medium",
            piper_data_dir=piper_dir,
            overlay_font_file=font_path,
            ffmpeg_font_file=font_path,
            video_size=(1080, 1920),
            fps=env_int("VIDEO_FPS", 30, 24, 60),
            crf=env_int("VIDEO_CRF", 23, 16, 35),
            answer_reveal_seconds=env_float("ANSWER_REVEAL_SECONDS", 2.0, 1.0, 5.0),
            made_for_kids=env_bool("MADE_FOR_KIDS", False),
            category_id=os.getenv("YOUTUBE_CATEGORY_ID", "24").strip() or "24",
            kill_switch=env_bool("KILL_SWITCH", False),
        )

    def with_overrides(self, **kwargs) -> "Config":
        return replace(self, **kwargs)


def _parse_weekdays(s: str) -> list[int]:
    s = (s or "").strip().upper()
    if not s:
        return []
    mapping = {
        "MON": 0,
        "TUE": 1,
        "WED": 2,
        "THU": 3,
        "FRI": 4,
        "SAT": 5,
        "SUN": 6,
    }
    out: list[int] = []
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        if p not in mapping:
            continue
        out.append(mapping[p])
    return sorted(set(out))

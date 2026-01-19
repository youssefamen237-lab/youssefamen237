from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


@dataclass(frozen=True)
class YouTubeAuthProfile:
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    state_path: Path
    out_dir: Path
    tmp_dir: Path

    shorts_per_run: int
    countdown_seconds: int
    answer_seconds: int
    fps: int
    width: int
    height: int

    font_bold_path: str

    groq_api_key: Optional[str]
    gemini_api_key: Optional[str]
    hf_api_token: Optional[str]

    yt_profiles: list[YouTubeAuthProfile]

    notify_subscribers: bool
    immediate_first_short_public: bool
    schedule_gap_hours: int
    category_id: str

    max_used_questions: int


def load_config() -> AppConfig:
    repo_root = Path(__file__).resolve().parents[1]
    state_path = repo_root / "state" / "state.json"
    out_dir = repo_root / "out"
    tmp_dir = repo_root / "tmp"

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    font_bold_path = _env(
        "FONT_BOLD_PATH",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ) or "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    profiles: list[YouTubeAuthProfile] = []
    cid1 = _env("YT_CLIENT_ID_1")
    cs1 = _env("YT_CLIENT_SECRET_1")
    rt1 = _env("YT_REFRESH_TOKEN_1")
    if cid1 and cs1 and rt1:
        profiles.append(YouTubeAuthProfile(client_id=cid1, client_secret=cs1, refresh_token=rt1))

    cid2 = _env("YT_CLIENT_ID_2")
    cs2 = _env("YT_CLIENT_SECRET_2")
    rt2 = _env("YT_REFRESH_TOKEN_2")
    if cid2 and cs2 and rt2:
        profiles.append(YouTubeAuthProfile(client_id=cid2, client_secret=cs2, refresh_token=rt2))

    shorts_per_run = _env_int("SHORTS_PER_RUN", 4)

    countdown_seconds = _env_int("COUNTDOWN_SECONDS", 10)
    answer_seconds = _env_int("ANSWER_SECONDS", 2)
    fps = _env_int("FPS", 30)
    width = _env_int("WIDTH", 1080)
    height = _env_int("HEIGHT", 1920)

    notify_subscribers = (_env("NOTIFY_SUBSCRIBERS", "false") or "false").lower() == "true"
    immediate_first_short_public = (_env("IMMEDIATE_FIRST_SHORT_PUBLIC", "true") or "true").lower() == "true"
    schedule_gap_hours = _env_int("SCHEDULE_GAP_HOURS", 6)

    category_id = _env("YT_CATEGORY_ID", "27") or "27"  # 27 = Education

    return AppConfig(
        repo_root=repo_root,
        state_path=state_path,
        out_dir=out_dir,
        tmp_dir=tmp_dir,
        shorts_per_run=shorts_per_run,
        countdown_seconds=countdown_seconds,
        answer_seconds=answer_seconds,
        fps=fps,
        width=width,
        height=height,
        font_bold_path=font_bold_path,
        groq_api_key=_env("GROQ_API_KEY"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        hf_api_token=_env("HF_API_TOKEN"),
        yt_profiles=profiles,
        notify_subscribers=notify_subscribers,
        immediate_first_short_public=immediate_first_short_public,
        schedule_gap_hours=schedule_gap_hours,
        category_id=category_id,
        max_used_questions=_env_int("MAX_USED_QUESTIONS", 5000),
    )

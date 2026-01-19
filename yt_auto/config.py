from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yt_auto.utils import env_bool, env_int, env_str


@dataclass(frozen=True)
class YouTubeOAuth:
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class Config:
    project_root: Path
    out_dir: Path
    state_path: Path
    backgrounds_dir: Path

    min_days_between_repeats: int

    countdown_seconds: int
    answer_reveal_seconds: int
    fps: int

    short_w: int
    short_h: int
    long_w: int
    long_h: int

    fontfile: str

    language: str
    category_id_short: str
    category_id_long: str
    privacy_short: str
    privacy_long: str
    made_for_kids: bool

    llm_order: list[str]
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_model: str
    openrouter_key: str
    openrouter_model: str

    allow_paid_providers: bool
    openai_api_key: str
    openai_model: str

    tts_order: list[str]
    eleven_api_key: str
    eleven_voice_id: str
    edge_voice: str
    tts_speed: str

    youtube_oauths: list[YouTubeOAuth]
    youtube_channel_id: str

    github_token: str


def load_config() -> Config:
    root = Path(".").resolve()
    out_dir = root / "out"
    state_path = root / "state" / "state.json"
    backgrounds_dir = root / "assets" / "backgrounds"

    min_days = env_int("MIN_DAYS_BETWEEN_REPEATS", 15)

    countdown_seconds = env_int("COUNTDOWN_SECONDS", 10)
    answer_reveal_seconds = env_int("ANSWER_REVEAL_SECONDS", 1)
    fps = env_int("VIDEO_FPS", 30)

    short_w = env_int("SHORT_W", 1080)
    short_h = env_int("SHORT_H", 1920)
    long_w = env_int("LONG_W", 1920)
    long_h = env_int("LONG_H", 1080)

    fontfile = env_str("FFMPEG_FONTFILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

    language = env_str("CONTENT_LANGUAGE", "en")
    category_id_short = env_str("YOUTUBE_CATEGORY_SHORT", "24")
    category_id_long = env_str("YOUTUBE_CATEGORY_LONG", "24")
    privacy_short = env_str("YOUTUBE_PRIVACY_SHORT", "public")
    privacy_long = env_str("YOUTUBE_PRIVACY_LONG", "public")
    made_for_kids = env_bool("YOUTUBE_MADE_FOR_KIDS", False)

    llm_order_raw = env_str("LLM_PROVIDER_ORDER", "gemini,groq,openrouter").strip()
    llm_order = [x.strip().lower() for x in llm_order_raw.split(",") if x.strip()]

    gemini_api_key = env_str("GEMINI_API_KEY", "").strip()
    gemini_model = env_str("GEMINI_MODEL", "gemini-1.5-flash").strip()

    groq_api_key = env_str("GROQ_API_KEY", "").strip()
    groq_model = env_str("GROQ_MODEL", "llama-3.1-70b-versatile").strip()

    openrouter_key = env_str("OPENROUTER_KEY", "").strip()
    openrouter_model = env_str("OPENROUTER_MODEL", "meta-llama/llama-3.1-70b-instruct").strip()

    allow_paid = env_bool("ALLOW_PAID_PROVIDERS", False)
    openai_api_key = env_str("OPENAI_API_KEY", "").strip()
    openai_model = env_str("OPENAI_MODEL", "gpt-4o-mini").strip()

    tts_order_raw = env_str("TTS_PROVIDER_ORDER", "edge,elevenlabs").strip()
    tts_order = [x.strip().lower() for x in tts_order_raw.split(",") if x.strip()]

    eleven_api_key = env_str("ELEVEN_API_KEY", "").strip()
    eleven_voice_id = env_str("ELEVEN_VOICE_ID", "").strip()
    edge_voice = env_str("EDGE_TTS_VOICE", "en-US-JennyNeural").strip()
    tts_speed = env_str("TTS_SPEED", "+0%").strip()

    youtube_channel_id = env_str("YT_CHANNEL_ID", "").strip()

    oauths: list[YouTubeOAuth] = []
    cid1 = env_str("YT_CLIENT_ID_1", "").strip()
    csec1 = env_str("YT_CLIENT_SECRET_1", "").strip()
    rt1 = env_str("YT_REFRESH_TOKEN_1", "").strip()
    if cid1 and csec1 and rt1:
        oauths.append(YouTubeOAuth(client_id=cid1, client_secret=csec1, refresh_token=rt1))

    cid2 = env_str("YT_CLIENT_ID_2", "").strip()
    csec2 = env_str("YT_CLIENT_SECRET_2", "").strip()
    rt2 = env_str("YT_REFRESH_TOKEN_2", "").strip()
    if cid2 and csec2 and rt2:
        oauths.append(YouTubeOAuth(client_id=cid2, client_secret=csec2, refresh_token=rt2))

    github_token = env_str("GITHUB_TOKEN", "").strip()

    return Config(
        project_root=root,
        out_dir=out_dir,
        state_path=state_path,
        backgrounds_dir=backgrounds_dir,
        min_days_between_repeats=min_days,
        countdown_seconds=countdown_seconds,
        answer_reveal_seconds=answer_reveal_seconds,
        fps=fps,
        short_w=short_w,
        short_h=short_h,
        long_w=long_w,
        long_h=long_h,
        fontfile=fontfile,
        language=language,
        category_id_short=category_id_short,
        category_id_long=category_id_long,
        privacy_short=privacy_short,
        privacy_long=privacy_long,
        made_for_kids=made_for_kids,
        llm_order=llm_order,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
        openrouter_key=openrouter_key,
        openrouter_model=openrouter_model,
        allow_paid_providers=allow_paid,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        tts_order=tts_order,
        eleven_api_key=eleven_api_key,
        eleven_voice_id=eleven_voice_id,
        edge_voice=edge_voice,
        tts_speed=tts_speed,
        youtube_oauths=oauths,
        youtube_channel_id=youtube_channel_id,
        github_token=github_token,
    )

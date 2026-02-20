import os
from dataclasses import dataclass
from pathlib import Path


def _pick(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


@dataclass
class Config:
    root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = root / "data"
    assets_dir: Path = root / "assets"
    output_dir: Path = root / "output"

    youtube_client_id: str = _pick("YT_CLIENT_ID_3", "YT_CLIENT_ID_2", "YT_CLIENT_ID_1", "YT_CLIENT_ID")
    youtube_client_secret: str = _pick("YT_CLIENT_SECRET_3", "YT_CLIENT_SECRET_2", "YT_CLIENT_SECRET_1", "YT_CLIENT_SECRET")
    youtube_refresh_token: str = _pick("YT_REFRESH_TOKEN_3", "YT_REFRESH_TOKEN_2", "YT_REFRESH_TOKEN_1", "YT_REFRESH_TOKEN")
    youtube_api_key: str = _pick("YOUTUBE_API_KEY")

    gemini_api_key: str = _pick("GEMINI_API_KEY")
    groq_api_key: str = _pick("GROQ_API_KEY")
    openai_api_key: str = _pick("OPENAI_API_KEY")
    openrouter_key: str = _pick("OPENROUTER_KEY")

    eleven_api_key: str = _pick("ELEVEN_API_KEY")
    pexels_api_key: str = _pick("PEXELS_API_KEY")
    pixabay_api_key: str = _pick("PIXABAY_API_KEY")
    unsplash_access_key: str = _pick("UNSPLASH_ACCESS_KEY")


CONFIG = Config()
CONFIG.output_dir.mkdir(exist_ok=True)
CONFIG.data_dir.mkdir(exist_ok=True)

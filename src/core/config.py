import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = root / "data"
    assets_dir: Path = root / "assets"
    output_dir: Path = root / "output"

    youtube_client_id: str = os.getenv("YT_CLIENT_ID_3") or os.getenv("YT_CLIENT_ID") or ""
    youtube_client_secret: str = os.getenv("YT_CLIENT_SECRET_3") or os.getenv("YT_CLIENT_SECRET") or ""
    youtube_refresh_token: str = os.getenv("YT_REFRESH_TOKEN_3") or os.getenv("YT_REFRESH_TOKEN") or ""
    youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openrouter_key: str = os.getenv("OPENROUTER_KEY", "")

    eleven_api_key: str = os.getenv("ELEVEN_API_KEY", "")
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
    pixabay_api_key: str = os.getenv("PIXABAY_API_KEY", "")
    unsplash_access_key: str = os.getenv("UNSPLASH_ACCESS_KEY", "")


CONFIG = Config()
CONFIG.output_dir.mkdir(exist_ok=True)
CONFIG.data_dir.mkdir(exist_ok=True)

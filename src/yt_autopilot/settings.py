\
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class Secrets:
    yt_channel_id: Optional[str]
    yt_client_id_1: Optional[str]
    yt_client_secret_1: Optional[str]
    yt_refresh_token_1: Optional[str]
    yt_client_id_2: Optional[str]
    yt_client_secret_2: Optional[str]
    yt_refresh_token_2: Optional[str]
    yt_client_id_3: Optional[str]
    yt_client_secret_3: Optional[str]
    yt_refresh_token_3: Optional[str]

    gemini_api_key: Optional[str]
    groq_api_key: Optional[str]
    football_data_token: Optional[str]


def load_secrets() -> Secrets:
    return Secrets(
        yt_channel_id=os.getenv("YT_CHANNEL_ID"),
        yt_client_id_1=os.getenv("YT_CLIENT_ID_1"),
        yt_client_secret_1=os.getenv("YT_CLIENT_SECRET_1"),
        yt_refresh_token_1=os.getenv("YT_REFRESH_TOKEN_1"),
        yt_client_id_2=os.getenv("YT_CLIENT_ID_2"),
        yt_client_secret_2=os.getenv("YT_CLIENT_SECRET_2"),
        yt_refresh_token_2=os.getenv("YT_REFRESH_TOKEN_2"),
        yt_client_id_3=os.getenv("YT_CLIENT_ID_3"),
        yt_client_secret_3=os.getenv("YT_CLIENT_SECRET_3"),
        yt_refresh_token_3=os.getenv("YT_REFRESH_TOKEN_3"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        football_data_token=os.getenv("FOOTBALL_DATA_TOKEN") or os.getenv("FOOTBALL_DATA_ORG") or os.getenv("API_FOOTBALL_KEY"),
    )


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    config_path = config_path or (DATA_DIR / "channel_config.json")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    overrides_path = DATA_DIR / "runtime_overrides.json"
    if overrides_path.exists():
        try:
            overrides_doc = json.loads(overrides_path.read_text(encoding="utf-8"))
            overrides = overrides_doc.get("overrides") or {}
            cfg = _deep_merge(cfg, overrides)
        except Exception:
            pass
    return cfg

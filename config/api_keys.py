"""
config/api_keys.py
==================
Single source of truth for every API key and credential path used
across the pipeline.  All values are read from environment variables
(populated via .env locally, or GitHub Actions Secrets in CI).

Rules
-----
- No key is ever hard-coded here or anywhere else in the codebase.
- Every key has a `_get()` helper that raises a clear, actionable
  error when the variable is missing — fast failure beats a cryptic
  AttributeError ten steps later in the pipeline.
- YouTube OAuth paths are grouped into a list of `YouTubeClient`
  dataclasses so auth.py can iterate them cleanly.
- Call `validate_all()` at pipeline startup to surface every missing
  variable in one shot rather than discovering them one by one.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


# ── Internal helper ────────────────────────────────────────────────────────

def _require(var: str) -> str:
    """
    Return the value of env var `var`.
    Raises EnvironmentError with a fix hint if it is absent or empty.
    """
    value = os.getenv(var, "").strip()
    if not value:
        raise EnvironmentError(
            f"[MindCraft] Required environment variable '{var}' is not set.\n"
            f"  → Add it to your .env file (local) or GitHub Secrets (CI).\n"
            f"  → See .env.example for the full list of required variables."
        )
    return value


def _optional(var: str, default: str = "") -> str:
    """Return env var value or a safe default — never raises."""
    return os.getenv(var, default).strip()


# ══════════════════════════════════════════════════════════════════════════
# RESEARCH
# ══════════════════════════════════════════════════════════════════════════

def get_tavily_key() -> str:
    return _require("TAVILY_API_KEY")


# ══════════════════════════════════════════════════════════════════════════
# LLM — PRIMARY (Gemini) + FALLBACK (Groq)
# ══════════════════════════════════════════════════════════════════════════

def get_gemini_key() -> str:
    return _require("GEMINI_API_KEY")


def get_groq_key() -> str:
    return _require("GROQ_API_KEY")


# ══════════════════════════════════════════════════════════════════════════
# STOCK VISUALS
# ══════════════════════════════════════════════════════════════════════════

def get_pexels_key() -> str:
    return _require("PEXELS_API_KEY")


def get_pixabay_key() -> str:
    return _require("PIXABAY_API_KEY")


# ══════════════════════════════════════════════════════════════════════════
# YOUTUBE OAUTH — rotating client credentials
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class YouTubeClient:
    """
    Immutable descriptor for one YouTube OAuth client.

    Attributes
    ----------
    index           : 1-based integer — matches YT_CLIENT_SECRET_N env vars.
    client_secret   : Path to the client_secret JSON downloaded from
                      Google Cloud Console.
    token_path      : Path where the cached OAuth token will be stored
                      after first authorisation.
    label           : Human-readable label used in logs.
    """
    index: int
    client_secret: Path
    token_path: Path
    label: str


def _load_yt_client(index: int) -> Optional[YouTubeClient]:
    """
    Attempt to load YouTube client `index` (1-based).
    Returns None — without raising — if that client is not configured,
    so the pipeline gracefully uses only the clients that exist.
    """
    secret_var = f"YT_CLIENT_SECRET_{index}"
    token_var  = f"YT_TOKEN_PATH_{index}"
    label_var  = f"YT_CHANNEL_LABEL_{index}"

    secret_path = os.getenv(secret_var, "").strip()
    token_path  = os.getenv(token_var,  "").strip()
    label       = os.getenv(label_var,  f"Client_{index}").strip()

    if not secret_path:
        return None   # this client slot is unconfigured — skip silently

    return YouTubeClient(
        index=index,
        client_secret=Path(secret_path),
        token_path=Path(token_path) if token_path else Path(f".tokens/token_{index}.json"),
        label=label,
    )


def get_youtube_clients() -> list[YouTubeClient]:
    """
    Return a list of all configured YouTube OAuth clients (1–3).
    Raises EnvironmentError if no client is configured at all.
    """
    clients = [c for i in range(1, 4) if (c := _load_yt_client(i)) is not None]
    if not clients:
        raise EnvironmentError(
            "[MindCraft] No YouTube OAuth clients are configured.\n"
            "  → Set at least YT_CLIENT_SECRET_1 and YT_TOKEN_PATH_1 in your .env."
        )
    return clients


# ══════════════════════════════════════════════════════════════════════════
# STARTUP VALIDATION
# ══════════════════════════════════════════════════════════════════════════

# Keys that MUST exist for any pipeline run to proceed.
# Visuals keys are also required — the pipeline cannot render without them.
_REQUIRED_KEYS: list[tuple[str, str]] = [
    ("TAVILY_API_KEY",  "Research / trend fetching"),
    ("GEMINI_API_KEY",  "Primary script generation (LLM)"),
    ("GROQ_API_KEY",    "Fallback script generation (LLM)"),
    ("PEXELS_API_KEY",  "Primary stock footage source"),
    ("PIXABAY_API_KEY", "Fallback stock footage source"),
]


def validate_all(raise_on_first: bool = False) -> list[str]:
    """
    Check every required environment variable.

    Parameters
    ----------
    raise_on_first : If True, raise immediately on the first missing key
                     (strict mode).  If False (default), collect all
                     missing keys and raise once with the full list.

    Returns
    -------
    List of missing variable names (empty list = all good).

    Raises
    ------
    EnvironmentError  : When one or more required keys are missing.
    """
    missing: list[str] = []

    for var, description in _REQUIRED_KEYS:
        value = os.getenv(var, "").strip()
        if not value:
            if raise_on_first:
                raise EnvironmentError(
                    f"[MindCraft] Missing required key: {var} ({description})"
                )
            missing.append(f"  • {var}  ← {description}")

    # Also validate that at least one YouTube client exists
    try:
        get_youtube_clients()
    except EnvironmentError as exc:
        if raise_on_first:
            raise
        missing.append(f"  • YT_CLIENT_SECRET_1  ← {exc}")

    if missing:
        lines = "\n".join(missing)
        raise EnvironmentError(
            f"[MindCraft] {len(missing)} required environment variable(s) are missing:\n"
            f"{lines}\n\n"
            f"  → Copy .env.example → .env and fill in all values."
        )

    return []

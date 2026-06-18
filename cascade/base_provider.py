"""
cascade/base_provider.py

Shared foundation for the entire Cascade System.
Every provider in every category (LLM, TTS, footage, images, AI video,
thumbnails) inherits BaseProvider and returns ProviderResult.

This file has zero external dependencies so it is always importable even
if optional libraries (google-generativeai, elevenlabs, etc.) are absent.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Unified result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProviderResult:
    """
    Standardised return value for every provider.execute() call.

    Attributes
    ──────────
    success       True when the provider returned usable, non-empty data.
    data          The payload.  Concrete type depends on the cascade category:
                    LLM        → str (text) or dict (JSON)
                    TTS        → bytes (audio PCM/MP3) or str (local file path)
                    Footage    → str (local .mp4 path) + metadata dict
                    Images     → bytes or str (local image path)
                    AI Images  → bytes or str (local image path)
                    AI Video   → str (local .mp4 path)
                    Thumbnails → bytes or str (local .jpg path)
    provider_used Exact provider_name of the instance that produced the result.
    error         Human-readable description of the failure when success=False.
    metadata      Optional structured context: token counts, file size, duration,
                  model name, source URL, licence, etc.
    """
    success: bool
    data: Any
    provider_used: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # allows `if result:` shorthand
        return self.success

    @classmethod
    def failure(cls, provider_name: str, error: str) -> "ProviderResult":
        """Convenience constructor for a clean failure result."""
        return cls(success=False, data=None, provider_used=provider_name, error=error)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """
    Abstract base that every cascade provider must subclass.

    Contract
    ────────
    • is_available() must be fast — no network I/O.  Checks only for the
      presence of required environment variables and in-process quota state.

    • execute(**kwargs) must NEVER raise an unhandled exception.
      All errors must be caught internally and returned as a ProviderResult
      with success=False.  The CascadeManager trusts this contract to avoid
      wrapping every call in a broad try/except.

    Class-level attributes
    ──────────────────────
    provider_name   Unique slug used in logs and Redis circuit-breaker keys.
    is_free_tier    True for providers that require no API key and have no quota
                    (edge-tts, local Pillow generator, AI Horde, etc.).
    cascade_category One of: 'llm', 'tts', 'footage', 'images', 'ai_images',
                    'ai_video', 'thumbnails'.
    """

    provider_name: str = "base"
    is_free_tier: bool = False
    cascade_category: str = "unknown"

    # ── Mandatory overrides ───────────────────────────────────────────────────

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider can accept requests right now."""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        Perform the provider's operation.
        Must never raise — return ProviderResult.failure() on any error.
        """
        ...

    # ── Optional hook ─────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """
        Optional lightweight ping to confirm the API is reachable.
        Default implementation delegates to is_available().
        Override to perform an actual API call when needed.
        """
        return self.is_available()

    # ── Shared utilities available to all subclasses ──────────────────────────

    @staticmethod
    def strip_json_markdown(text: str) -> str:
        """
        Remove ```json ... ``` or ``` ... ``` fences that some LLMs wrap
        around JSON output.  Returns the inner content, or the original text
        if no fence is found.
        """
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def env_present(*var_names: str) -> bool:
        """
        Return True only if ALL named environment variables are set and
        contain a non-empty, non-whitespace value.
        Used inside is_available() implementations.
        """
        import os
        return all(bool(os.getenv(v, "").strip()) for v in var_names)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.provider_name!r} "
            f"category={self.cascade_category!r} "
            f"free={self.is_free_tier}>"
        )

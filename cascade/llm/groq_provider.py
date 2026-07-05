"""
cascade/llm/groq_provider.py

LLM Provider: Groq  (Llama 3.3 70B Versatile, with live fallbacks)
Priority: 2nd — extremely fast inference, generous free tier

Capabilities
────────────
  • Text generation
  • JSON mode (response_format={"type":"json_object"})
  • Very high throughput (tokens/s)

Model selection
────────────────
Groq periodically retires model IDs (llama-3.1-70b-versatile was
decommissioned in 2025; llama3-70b-8192 before that). Decommissioned
models return HTTP 400 with code="model_decommissioned" or
"invalid_request_error". This error is now detected and treated as
"try next model" rather than "return failure", which was the old
behaviour that prematurely exhausted the retry budget, opened the
circuit breaker after 3 fast failures, and locked out Groq for the
rest of the batch even while llama-3.3-70b-versatile was healthy.

Required GitHub Secret
──────────────────────
  GROQ_API_KEY
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

# Current active Groq models, tried in priority order.
# llama-3.1-70b-versatile and llama3-70b-8192 were removed because
# Groq decommissioned them; they returned 400 model_decommissioned
# on every call, causing the cascade to waste retry budget and
# open the circuit breaker on a non-transient error.
_MODELS: List[str] = [
    "llama-3.3-70b-versatile",   # primary: best quality, active
    "llama-3.1-8b-instant",      # fast fallback, active
    "gemma2-9b-it",               # Google Gemma fallback, active on Groq
]

# Error patterns that mean "this model is permanently gone — try the next
# one in the list" rather than "return failure for this whole provider".
_DECOMMISSIONED_PATTERNS = (
    "model_decommissioned", "invalid_request_error",
    "is no longer supported", "has been decommissioned",
)

# Rate-limit / quota patterns — also skip to next model
_RATE_PATTERNS = ("rate_limit", "429", "quota", "too many", "tokens per")


class GroqProvider(BaseProvider):
    """
    Groq cloud LLM provider using Llama 3.3 70B with live model fallbacks.
    Client is created lazily to avoid import errors when the secret is absent.
    """

    provider_name = "groq"
    is_free_tier = False
    cascade_category = "llm"

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("GROQ_API_KEY")

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=os.environ["GROQ_API_KEY"])
        return self._client

    # ── Core execution ────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        kwargs expected
        ───────────────
        prompt          str   — user prompt
        system_prompt   str   — optional system instructions
        response_format str   — "text" (default) or "json"
        max_tokens      int   — default 1 000
        temperature     float — default 0.7
        """
        prompt: str = kwargs.get("prompt", "")
        system_prompt: Optional[str] = kwargs.get("system_prompt")
        response_format: str = kwargs.get("response_format", "text")
        max_tokens: int = int(kwargs.get("max_tokens", 1_000))
        temperature: float = float(kwargs.get("temperature", 0.7))

        if not prompt.strip():
            return ProviderResult.failure(
                self.provider_name, "Empty prompt received.", retriable=False
            )

        is_json = response_format == "json"
        messages = self._build_messages(prompt, system_prompt, is_json)
        client = self._get_client()

        for model in _MODELS:
            try:
                call_kwargs: dict = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": min(temperature, 0.4) if is_json else temperature,
                }
                if is_json:
                    call_kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**call_kwargs)

                raw_text: str = response.choices[0].message.content or ""
                if not raw_text.strip():
                    logger.warning("groq_empty_response", model=model)
                    continue

                meta = {
                    "model": model,
                    "provider": self.provider_name,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

                if is_json:
                    clean = self.strip_json_markdown(raw_text)
                    try:
                        data = json.loads(clean)
                    except json.JSONDecodeError as je:
                        return ProviderResult.failure(
                            self.provider_name,
                            f"Groq returned non-parseable JSON ({model}): {je} | raw={clean[:200]}",
                        )
                    return ProviderResult(
                        success=True, data=data,
                        provider_used=self.provider_name, metadata=meta,
                    )
                return ProviderResult(
                    success=True, data=raw_text.strip(),
                    provider_used=self.provider_name, metadata=meta,
                )

            except Exception as exc:
                err_lower = str(exc).lower()

                if any(p in err_lower for p in _DECOMMISSIONED_PATTERNS):
                    # Permanently unavailable model — skip to next without counting
                    # this as a provider-level failure (no circuit-breaker credit burned).
                    logger.warning(
                        "groq_model_decommissioned_trying_next",
                        model=model, error=str(exc)[:120],
                    )
                    continue

                if any(p in err_lower for p in _RATE_PATTERNS):
                    logger.warning(
                        "groq_rate_limit_trying_next_model",
                        model=model, error=str(exc)[:120],
                    )
                    continue

                # Unrecognised / non-transient error — fail fast, let cascade try next provider
                return ProviderResult.failure(
                    self.provider_name, f"Groq error ({model}): {exc}"
                )

        return ProviderResult.failure(
            self.provider_name,
            f"All Groq models exhausted: {_MODELS}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        prompt: str, system_prompt: Optional[str], is_json: bool
    ) -> List[dict]:
        default_system = (
            "You must respond with valid JSON only. No markdown fences, no explanation."
            if is_json
            else "You are a helpful, concise assistant."
        )
        return [
            {
                "role": "system",
                "content": (system_prompt or default_system)
                + ("\n\nRespond ONLY with valid JSON." if is_json else ""),
            },
            {"role": "user", "content": prompt},
        ]

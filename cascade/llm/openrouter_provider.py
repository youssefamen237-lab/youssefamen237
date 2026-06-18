"""
cascade/llm/openrouter_provider.py

LLM Provider: OpenRouter
Priority: 3rd — access to multiple models including free-tier options

OpenRouter is an OpenAI-compatible gateway that provides access to dozens
of LLM models.  This provider tries models in priority order within a
single execute() call, enabling deep fallback without touching the
CascadeManager's inter-provider routing.

Model priority (tried in order)
────────────────────────────────
  1. google/gemini-flash-1.5-8b        — fast, cheap, reliable
  2. meta-llama/llama-3.1-8b-instruct:free — always available on free tier
  3. mistralai/mistral-7b-instruct:free    — reliable free tier backup

Required GitHub Secret
──────────────────────
  OPENROUTER_KEY
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_MODELS: List[str] = [
    "google/gemini-flash-1.5-8b",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

# OpenRouter recommends these headers for request attribution
_EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/youtube-automation-system",
    "X-Title": "YouTube Nature Automation",
}


class OpenRouterProvider(BaseProvider):
    """
    OpenRouter gateway LLM provider.
    Uses the openai Python SDK pointed at the OpenRouter API endpoint.
    """

    provider_name = "openrouter"
    is_free_tier = False
    cascade_category = "llm"

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("OPENROUTER_KEY")

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ["OPENROUTER_KEY"],
                base_url=_OPENROUTER_BASE_URL,
                default_headers=_EXTRA_HEADERS,
            )
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
            return ProviderResult.failure(self.provider_name, "Empty prompt received.")

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
                # Only add json_object format for non-free models that reliably support it
                if is_json and ":free" not in model:
                    call_kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**call_kwargs)

                raw_text: str = (response.choices[0].message.content or "").strip()
                if not raw_text:
                    logger.warning(
                        "openrouter_empty_response",
                        model=model,
                        finish_reason=response.choices[0].finish_reason,
                    )
                    continue

                meta = {
                    "model": model,
                    "provider": self.provider_name,
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }

                if is_json:
                    clean = self.strip_json_markdown(raw_text)
                    try:
                        data = json.loads(clean)
                    except json.JSONDecodeError as je:
                        logger.warning(
                            "openrouter_json_parse_error",
                            model=model,
                            error=str(je),
                            raw_preview=clean[:200],
                        )
                        # Try next model rather than returning failure immediately
                        continue
                    return ProviderResult(
                        success=True, data=data,
                        provider_used=self.provider_name, metadata=meta,
                    )
                else:
                    return ProviderResult(
                        success=True, data=raw_text,
                        provider_used=self.provider_name, metadata=meta,
                    )

            except Exception as exc:
                err_str = str(exc).lower()
                if any(kw in err_str for kw in ("rate", "429", "quota", "capacity", "overload")):
                    logger.warning(
                        "openrouter_rate_error_next_model",
                        model=model,
                        error=str(exc),
                    )
                    continue
                # Non-retriable for this model — try next
                logger.warning(
                    "openrouter_model_error_next_model",
                    model=model,
                    error=str(exc),
                )
                continue

        return ProviderResult.failure(
            self.provider_name,
            f"All OpenRouter models failed: {_MODELS}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        prompt: str, system_prompt: Optional[str], is_json: bool
    ) -> List[dict]:
        json_instruction = "\n\nYou must respond with valid JSON only. No markdown, no explanation." if is_json else ""
        return [
            {
                "role": "system",
                "content": (system_prompt or "You are a helpful, concise assistant.") + json_instruction,
            },
            {"role": "user", "content": prompt},
        ]

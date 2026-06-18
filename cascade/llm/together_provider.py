"""
cascade/llm/together_provider.py

LLM Provider: Together AI  (Meta Llama 3.1 70B Instruct Turbo)
Priority: 4th — fast inference, competitive pricing, reliable uptime

Together AI exposes an OpenAI-compatible API, so we use the openai SDK
pointed at their endpoint.

Required GitHub Secret
──────────────────────
  TOGETHER_AI    (API key — note: not TOGETHER_API_KEY)
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"

# Models tried in order within this provider
_MODELS: List[str] = [
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
]


class TogetherProvider(BaseProvider):
    """
    Together AI LLM provider via their OpenAI-compatible endpoint.
    """

    provider_name = "together"
    is_free_tier = False
    cascade_category = "llm"

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("TOGETHER_AI")

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ["TOGETHER_AI"],
                base_url=_TOGETHER_BASE_URL,
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

                response = client.chat.completions.create(**call_kwargs)

                raw_text: str = (response.choices[0].message.content or "").strip()
                if not raw_text:
                    logger.warning("together_empty_response", model=model)
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
                            "together_json_parse_error",
                            model=model,
                            error=str(je),
                            raw_preview=clean[:200],
                        )
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
                if any(kw in err_str for kw in ("rate", "429", "quota", "capacity", "overload", "busy")):
                    logger.warning(
                        "together_rate_error_next_model",
                        model=model,
                        error=str(exc),
                    )
                    continue
                logger.warning(
                    "together_model_error_next_model",
                    model=model,
                    error=str(exc),
                )
                continue

        return ProviderResult.failure(
            self.provider_name,
            f"All Together AI models failed: {_MODELS}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        prompt: str, system_prompt: Optional[str], is_json: bool
    ) -> List[dict]:
        json_suffix = (
            "\n\nIMPORTANT: Your entire response must be valid JSON. "
            "No markdown fences, no explanations, no extra text." if is_json else ""
        )
        return [
            {
                "role": "system",
                "content": (system_prompt or "You are a helpful, concise assistant.") + json_suffix,
            },
            {"role": "user", "content": prompt},
        ]

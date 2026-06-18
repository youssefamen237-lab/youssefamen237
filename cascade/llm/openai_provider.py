"""
cascade/llm/openai_provider.py

LLM Provider: OpenAI  (GPT-4o-mini)
Priority: 5th (last resort) — most reliable but has cost implications

Used only when all four higher-priority providers (Gemini, Groq,
OpenRouter, Together) have been exhausted.  GPT-4o-mini offers the
best JSON-mode reliability of all providers and serves as the safety net.

Required GitHub Secret
──────────────────────
  OPENAI_API_KEY
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

# Try the cheapest capable model first, fall back to slightly older version
_MODELS: List[str] = [
    "gpt-4o-mini",
    "gpt-3.5-turbo",
]


class OpenAIProvider(BaseProvider):
    """
    OpenAI GPT-4o-mini provider.
    Last resort in the LLM cascade — prioritises reliability over cost.
    """

    provider_name = "openai"
    is_free_tier = False
    cascade_category = "llm"

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("OPENAI_API_KEY")

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
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
                if is_json:
                    # OpenAI has first-class json_object support
                    call_kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**call_kwargs)

                raw_text: str = (response.choices[0].message.content or "").strip()
                finish_reason: str = response.choices[0].finish_reason or ""

                if not raw_text:
                    logger.warning(
                        "openai_empty_response",
                        model=model,
                        finish_reason=finish_reason,
                    )
                    continue

                if finish_reason == "length":
                    logger.warning(
                        "openai_truncated_response",
                        model=model,
                        hint="Increase max_tokens or shorten the prompt.",
                    )
                    # Still attempt to use the partial result

                meta = {
                    "model": model,
                    "provider": self.provider_name,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "finish_reason": finish_reason,
                }

                if is_json:
                    clean = self.strip_json_markdown(raw_text)
                    try:
                        data = json.loads(clean)
                    except json.JSONDecodeError as je:
                        # OpenAI json_object mode should never produce invalid JSON,
                        # but handle gracefully just in case
                        return ProviderResult.failure(
                            self.provider_name,
                            f"OpenAI returned non-parseable JSON ({model}): {je} | raw={clean[:200]}",
                        )
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
                if any(kw in err_str for kw in ("rate_limit", "429", "quota", "insufficient_quota")):
                    logger.warning(
                        "openai_quota_error",
                        model=model,
                        error=str(exc),
                    )
                    continue
                # For any other error on a model, log and try next
                logger.warning(
                    "openai_model_error",
                    model=model,
                    error=str(exc),
                )
                continue

        return ProviderResult.failure(
            self.provider_name,
            f"All OpenAI models failed or quota exhausted: {_MODELS}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        prompt: str, system_prompt: Optional[str], is_json: bool
    ) -> List[dict]:
        json_suffix = (
            "\n\nYour entire response must be a single valid JSON object. "
            "No markdown, no preamble, no explanation outside the JSON." if is_json else ""
        )
        return [
            {
                "role": "system",
                "content": (system_prompt or "You are a helpful, concise assistant.") + json_suffix,
            },
            {"role": "user", "content": prompt},
        ]

"""
cascade/llm/groq_provider.py

LLM Provider: Groq  (Llama 3.3 70B Versatile)
Priority: 2nd — extremely fast inference, generous free tier

Capabilities
────────────
  • Text generation
  • JSON mode (response_format={"type":"json_object"})
  • Very high throughput (tokens/s)

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

# Model priority within this provider (try in order on quota/rate errors)
_MODELS: List[str] = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
]


class GroqProvider(BaseProvider):
    """
    Groq cloud LLM provider using Llama 3.3 70B.
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
                else:
                    return ProviderResult(
                        success=True, data=raw_text.strip(),
                        provider_used=self.provider_name, metadata=meta,
                    )

            except Exception as exc:
                err_str = str(exc).lower()
                if any(kw in err_str for kw in ("rate_limit", "429", "quota", "too many")):
                    logger.warning(
                        "groq_rate_limit_trying_next_model",
                        model=model,
                        error=str(exc),
                    )
                    continue
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
        messages = [
            {
                "role": "system",
                "content": (system_prompt or default_system)
                + ("\n\nRespond ONLY with valid JSON." if is_json else ""),
            },
            {"role": "user", "content": prompt},
        ]
        return messages

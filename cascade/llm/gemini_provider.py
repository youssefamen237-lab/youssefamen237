"""
cascade/llm/gemini_provider.py

LLM Provider: Google Gemini 1.5 Flash
Priority: 1st (highest — most generous free tier, fastest, highest token limits)

Capabilities
────────────
  • Text generation
  • Native JSON mode via response_mime_type="application/json"
  • System instruction support

Rate limits (free tier as of mid-2025)
────────────────────────────────────────
  15 RPM  |  1 000 000 TPM  |  1 500 requests/day

Required GitHub Secret
──────────────────────
  GEMINI_API_KEY
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_MODEL_NAME = "gemini-1.5-flash"
_FALLBACK_MODEL = "gemini-1.5-flash-8b"   # smaller, used if flash quota hits


class GeminiProvider(BaseProvider):
    """
    Google Gemini 1.5 Flash provider.
    Initialises the genai SDK lazily on first execute() call to avoid
    import-time errors when the secret is absent.
    """

    provider_name = "gemini"
    is_free_tier = False
    cascade_category = "llm"

    def __init__(self) -> None:
        self._configured = False

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.env_present("GEMINI_API_KEY")

    # ── Lazy SDK configuration ────────────────────────────────────────────────

    def _ensure_configured(self) -> None:
        if self._configured:
            return
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        self._configured = True

    # ── Core execution ────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        kwargs expected
        ───────────────
        prompt          str   — the user/main prompt
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

        try:
            return self._call_api(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            return ProviderResult.failure(
                self.provider_name, f"Gemini API error: {exc}"
            )

    def _call_api(
        self,
        prompt: str,
        system_prompt: Optional[str],
        response_format: str,
        max_tokens: int,
        temperature: float,
    ) -> ProviderResult:
        import google.generativeai as genai

        self._ensure_configured()

        is_json = response_format == "json"

        if is_json:
            gen_config = genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=max_tokens,
                temperature=min(temperature, 0.4),   # lower temp for JSON
            )
            effective_system = (
                (system_prompt or "")
                + "\n\nYou must respond with valid JSON only. No markdown, no explanation."
            ).strip()
        else:
            gen_config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            effective_system = system_prompt or "You are a helpful assistant."

        # Try primary model, fall back to smaller model on quota errors
        for model_name in [_MODEL_NAME, _FALLBACK_MODEL]:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=gen_config,
                    system_instruction=effective_system,
                )
                response = model.generate_content(prompt)

                # Check for blocked / empty response
                if not response.candidates:
                    logger.warning(
                        "gemini_no_candidates",
                        model=model_name,
                        finish_reason=str(
                            response.prompt_feedback if hasattr(response, "prompt_feedback") else "unknown"
                        ),
                    )
                    continue

                raw_text: str = response.text
                if not raw_text.strip():
                    logger.warning("gemini_empty_response", model=model_name)
                    continue

                # Token usage
                usage = response.usage_metadata if hasattr(response, "usage_metadata") else None
                meta = {
                    "model": model_name,
                    "provider": self.provider_name,
                    "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                    "completion_tokens": getattr(usage, "candidates_token_count", 0),
                    "total_tokens": getattr(usage, "total_token_count", 0),
                }

                if is_json:
                    clean = self.strip_json_markdown(raw_text)
                    try:
                        data = json.loads(clean)
                    except json.JSONDecodeError as je:
                        return ProviderResult.failure(
                            self.provider_name,
                            f"Gemini returned non-parseable JSON ({model_name}): {je} | raw={clean[:200]}",
                        )
                    return ProviderResult(
                        success=True,
                        data=data,
                        provider_used=self.provider_name,
                        metadata=meta,
                    )
                else:
                    return ProviderResult(
                        success=True,
                        data=raw_text.strip(),
                        provider_used=self.provider_name,
                        metadata=meta,
                    )

            except Exception as model_exc:
                err_str = str(model_exc).lower()
                # Quota / rate-limit errors → try fallback model
                if any(kw in err_str for kw in ("quota", "rate", "429", "resource_exhausted")):
                    logger.warning(
                        "gemini_quota_error_trying_fallback",
                        model=model_name,
                        error=str(model_exc),
                    )
                    continue
                # Non-retriable error
                return ProviderResult.failure(
                    self.provider_name, f"Gemini error ({model_name}): {model_exc}"
                )

        return ProviderResult.failure(
            self.provider_name,
            "Both Gemini models (flash + flash-8b) returned empty or quota-exceeded responses.",
        )

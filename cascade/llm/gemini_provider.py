"""
cascade/llm/gemini_provider.py

LLM Provider: Google Gemini
Priority: 1st (highest — most generous free tier, fastest, highest token limits)

Capabilities
────────────
  • Text generation
  • Native JSON mode via response_mime_type="application/json"
  • System instruction support

Model selection
────────────────
  Google periodically retires older model IDs (e.g. gemini-1.5-flash and
  gemini-1.5-flash-8b were retired in 2025). To stay resilient against
  future retirements without requiring a code change every time, this
  provider tries, in order:
    1. _MODEL_NAME      — current primary model
    2. _FALLBACK_MODEL   — current smaller/faster model
    3. Dynamic discovery — if BOTH hardcoded models 404 ("not found" /
       "not supported"), calls genai.list_models() and uses the first
       model that supports generateContent. This third tier is what
       makes the provider self-healing the next time Google retires a
       model name, instead of silently falling through to Groq forever.

Required GitHub Secret
──────────────────────
  GEMINI_API_KEY
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)

_MODEL_NAME = "gemini-2.0-flash"
_FALLBACK_MODEL = "gemini-2.0-flash-lite"   # smaller/faster, used if primary quota hits

# Cache the discovered model name for the lifetime of this process so we
# only call list_models() once even if every request hits this fallback.
_discovered_model_cache: Optional[str] = None

# ─────────────────────────────────────────────────────────────────────────────
# Error classification
# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: these patterns are matched with regex word boundaries, NOT plain
# substring containment. A previous version used `"rate" in err_str`, which
# produced false positives because "generateContent" itself contains the
# substring "rate" (...geneRATEContent...). Every 404 "model not found" error
# from Gemini was therefore misclassified as a rate-limit error, silently
# retried, and eventually tripped the circuit breaker for an unrelated
# reason. Word-boundary regex matching eliminates this entire class of bug.

_QUOTA_PATTERNS = [
    r"\bquota\b", r"\b429\b", r"\brate[ _-]?limit\b", r"\bresource_exhausted\b",
    r"\btoo many requests\b",
]
_MODEL_NOT_FOUND_PATTERNS = [
    r"\b404\b", r"\bnot found\b", r"\bis not supported for\b",
    r"\bmodel not found\b",
]
# "limit: 0" in a 429 response means this API key's Google Cloud project has
# ZERO free-tier quota provisioned for this model — not a temporary
# per-minute exhaustion. No amount of waiting or retrying will ever
# succeed; this is a permanent, account-level configuration problem
# (commonly caused by a billing account being linked to the project
# without the free tier being separately enabled, or the project/region
# not being eligible for the Gemini free tier at all). Detected separately
# from ordinary quota exhaustion so we can force_open the circuit
# immediately instead of waiting for 3 separate strikes across 3 videos.
_ZERO_QUOTA_PATTERNS = [
    r"\blimit:\s*0\b", r"\blimit\s*=\s*0\b",
]


def _matches_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


class GeminiProvider(BaseProvider):
    """
    Google Gemini provider.
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
            return ProviderResult.failure(
                self.provider_name, "Empty prompt received.", retriable=False
            )

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

        candidate_models = [_MODEL_NAME, _FALLBACK_MODEL]
        saw_model_not_found = False
        saw_zero_quota = False
        last_error_text = ""

        attempt_index = 0
        while attempt_index < len(candidate_models):
            model_name = candidate_models[attempt_index]
            attempt_index += 1
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
                last_error_text = str(model_exc)

                if _matches_any(_MODEL_NOT_FOUND_PATTERNS, err_str):
                    saw_model_not_found = True
                    logger.warning(
                        "gemini_model_not_found_trying_next",
                        model=model_name,
                        error=str(model_exc),
                    )
                    continue

                if _matches_any(_QUOTA_PATTERNS, err_str):
                    if _matches_any(_ZERO_QUOTA_PATTERNS, err_str):
                        saw_zero_quota = True
                    logger.warning(
                        "gemini_quota_error_trying_fallback",
                        model=model_name,
                        zero_quota=_matches_any(_ZERO_QUOTA_PATTERNS, err_str),
                        error=str(model_exc),
                    )
                    continue

                # Genuinely unrecognised error — do not burn the outer
                # cascade's retry budget on something that is unlikely to
                # be transient (e.g. malformed request, safety block).
                return ProviderResult.failure(
                    self.provider_name,
                    f"Gemini error ({model_name}): {model_exc}",
                    retriable=False,
                )

        # Both hardcoded models failed. If the failures were specifically
        # "model not found" (not quota), the model IDs above are stale —
        # discover a currently-valid model instead of giving up. This makes
        # the provider self-healing across future Google model retirements.
        if saw_model_not_found:
            discovered = self._discover_working_model()
            if discovered and discovered not in candidate_models:
                logger.warning(
                    "gemini_using_discovered_model",
                    discovered_model=discovered,
                    hint=(
                        f"Hardcoded models {candidate_models} are no longer "
                        f"available. Update _MODEL_NAME in gemini_provider.py "
                        f"to '{discovered}' to avoid this discovery call on "
                        f"every future request."
                    ),
                )
                try:
                    model = genai.GenerativeModel(
                        model_name=discovered,
                        generation_config=gen_config,
                        system_instruction=effective_system,
                    )
                    response = model.generate_content(prompt)
                    if response.candidates and response.text.strip():
                        raw_text = response.text
                        meta = {"model": discovered, "provider": self.provider_name}
                        if is_json:
                            clean = self.strip_json_markdown(raw_text)
                            data = json.loads(clean)
                            return ProviderResult(
                                success=True, data=data,
                                provider_used=self.provider_name, metadata=meta,
                            )
                        return ProviderResult(
                            success=True, data=raw_text.strip(),
                            provider_used=self.provider_name, metadata=meta,
                        )
                except Exception as disc_exc:
                    last_error_text = str(disc_exc)

            # Every hardcoded + discovered model is unavailable — this is a
            # deterministic configuration problem, not a transient one.
            return ProviderResult.failure(
                self.provider_name,
                f"All Gemini model names are unavailable for this API key "
                f"(tried {candidate_models} + dynamic discovery). "
                f"Last error: {last_error_text}",
                retriable=False,
            )

        if saw_zero_quota:
            logger.error(
                "gemini_permanent_zero_quota",
                action_required=(
                    "This Gemini API key's Google Cloud project has a "
                    "free-tier quota limit of ZERO for this model — this is "
                    "a permanent project-level configuration issue, not a "
                    "temporary rate limit, and will never succeed no matter "
                    "how long it waits. Common causes: a billing account is "
                    "linked to the project without the Generative Language "
                    "API free tier being separately enabled, or the "
                    "project/region is not eligible for the free tier. Fix: "
                    "generate a fresh GEMINI_API_KEY from a clean Google AI "
                    "Studio project (https://aistudio.google.com/apikey) "
                    "with no billing account attached, or enable the free "
                    "tier explicitly in Google Cloud Console for this "
                    "project, then update the GEMINI_API_KEY GitHub Secret."
                ),
            )

        # Both hardcoded models exhausted their quota. The inner loop above
        # already represents the complete attempt for this call — retrying
        # the SAME two models again via the outer cascade's 1-2s backoff is
        # pointless (Google's own retry_delay hints in the 429 response are
        # 7-14s, far longer than our backoff anyway). retriable=False stops
        # the outer cascade from wasting that time and force-opens the
        # circuit immediately, which is also correct here: whether this is
        # a permanent zero-quota project or an ordinary per-minute window,
        # the 300s circuit reset window is long enough for a real per-minute
        # quota to naturally clear, so Gemini will be retried automatically
        # on the next production run regardless of which case this was.
        return ProviderResult.failure(
            self.provider_name,
            f"Both Gemini models ({_MODEL_NAME} + {_FALLBACK_MODEL}) "
            f"returned empty or quota-exceeded responses. Last error: {last_error_text}",
            retriable=False,
        )

    # ── Dynamic model discovery (self-healing fallback) ──────────────────────

    def _discover_working_model(self) -> Optional[str]:
        """
        Query the Gemini API for currently-available models and return the
        first one that supports generateContent. Used only as a last resort
        when both hardcoded model names return 404. Result is cached for the
        lifetime of this process.
        """
        global _discovered_model_cache
        if _discovered_model_cache is not None:
            return _discovered_model_cache

        import google.generativeai as genai
        try:
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", []) or []
                if "generateContent" in methods:
                    # Model names come back as "models/gemini-2.0-flash" — strip prefix
                    name = m.name.split("/", 1)[-1]
                    _discovered_model_cache = name
                    logger.info("gemini_model_discovered", model=name)
                    return name
        except Exception as exc:
            logger.error("gemini_model_discovery_failed", error=str(exc))
        return None

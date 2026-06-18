"""
cascade/llm/llm_cascade.py

LLM Cascade Coordinator — the single import point for all LLM calls.

Every engine in the system (script_writer, fact_research, metadata_generator,
growth_manager, cos, etc.) calls this module exclusively.  No engine imports
an individual provider directly.

Provider cascade order
──────────────────────
  1. Gemini 1.5 Flash    (primary  — generous free tier, native JSON mode)
  2. Groq Llama 3.3 70B  (2nd     — ultra-fast inference)
  3. OpenRouter multi    (3rd     — free-tier model access)
  4. Together Llama 70B  (4th     — fast paid inference)
  5. OpenAI GPT-4o-mini  (last    — most reliable, cost backstop)

Public interface
────────────────
  generate_text(prompt, system_prompt, max_tokens, temperature) → str
  generate_json(prompt, system_prompt, max_tokens)              → dict
  get_llm()                                                     → LLMCascade singleton
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

import structlog

from cascade.base_provider import ProviderResult
from cascade.cascade_manager import CascadeManager, CircuitBreaker
from cascade.llm.gemini_provider import GeminiProvider
from cascade.llm.groq_provider import GroqProvider
from cascade.llm.openai_provider import OpenAIProvider
from cascade.llm.openrouter_provider import OpenRouterProvider
from cascade.llm.together_provider import TogetherProvider

logger = structlog.get_logger(__name__)

# Shared circuit breaker instance so failures persist across multiple
# LLMCascade.generate_*() calls within the same process/workflow run
_SHARED_BREAKER = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300)


class LLMCascade:
    """
    Singleton LLM facade.
    Wraps CascadeManager with the five production providers and exposes two
    clean, semantic methods used by every engine in the system.
    """

    def __init__(self) -> None:
        self._manager = CascadeManager(
            providers=[
                GeminiProvider(),
                GroqProvider(),
                OpenRouterProvider(),
                TogetherProvider(),
                OpenAIProvider(),
            ],
            category="llm",
            max_retries_per_provider=2,
            circuit_breaker=_SHARED_BREAKER,
        )

    # ═════════════════════════════════════════════════════════════════════════
    # Core public methods — used by every engine
    # ═════════════════════════════════════════════════════════════════════════

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1_000,
        temperature: float = 0.7,
    ) -> str:
        """
        Generate a plain-text response.

        Raises RuntimeError if every provider in the cascade fails.
        The caller is responsible for deciding how to handle that error
        (log + skip the job vs. mark the queue entry as failed).
        """
        result: ProviderResult = self._manager.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            response_format="text",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not result.success:
            raise RuntimeError(
                f"LLM cascade exhausted for text generation. "
                f"Error: {result.error}"
            )
        text = result.data
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(
                f"LLM cascade returned empty text (provider={result.provider_used})."
            )
        logger.info(
            "llm_text_generated",
            provider=result.provider_used,
            tokens=result.metadata.get("total_tokens", "?"),
            chars=len(text),
        )
        return text.strip()

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1_500,
    ) -> Dict[str, Any]:
        """
        Generate a structured JSON response and return it as a Python dict.

        Always uses a lower temperature (0.3) for deterministic JSON output.
        Raises RuntimeError if every provider fails or if none returns valid JSON.
        """
        result: ProviderResult = self._manager.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            response_format="json",
            max_tokens=max_tokens,
            temperature=0.3,
        )
        if not result.success:
            raise RuntimeError(
                f"LLM cascade exhausted for JSON generation. "
                f"Error: {result.error}"
            )
        data = result.data
        # Providers should return a dict; if somehow a string slipped through, parse it
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as je:
                raise RuntimeError(
                    f"LLM cascade returned a string that is not valid JSON "
                    f"(provider={result.provider_used}): {je}"
                )
        if not isinstance(data, dict):
            raise RuntimeError(
                f"LLM cascade returned unexpected type {type(data).__name__} "
                f"instead of dict (provider={result.provider_used})."
            )
        logger.info(
            "llm_json_generated",
            provider=result.provider_used,
            tokens=result.metadata.get("total_tokens", "?"),
            keys=list(data.keys())[:6],
        )
        return data

    # ═════════════════════════════════════════════════════════════════════════
    # Convenience wrappers used by specific engines
    # ═════════════════════════════════════════════════════════════════════════

    def generate_script_segments(
        self,
        topic_name: str,
        category: str,
        facts: list,
        hook_type: str,
        video_type: str = "short",
        target_duration_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        Generate a complete video script broken into sentence-level segments.

        Returns a dict matching the schema stored in video_queue.script:
        {
          "hook": "...",
          "segments": [
            {
              "sentence": "...",
              "search_query": "...",
              "visual_type": "action|close_up|wide|comparison|text_only",
              "fact_index": 0
            },
            ...
          ],
          "cta_placeholder": "...",
          "full_text": "..."
        }
        """
        facts_block = "\n".join(
            f"  [{i}] {f.get('fact_text', str(f))}" for i, f in enumerate(facts)
        )
        duration_hint = (
            "18–44 seconds (Shorts)" if video_type == "short" else "5–8 minutes (long-form)"
        )

        system = (
            "You are a professional YouTube script writer specialising in nature and science "
            "content optimised for high viewer retention. "
            "You write in simple, clear English at a B1–B2 level suitable for a global audience. "
            "Every sentence must be self-contained so it can be matched to a single video clip."
        )

        prompt = f"""Write a YouTube {video_type} script about: {topic_name} (category: {category})

Target duration: {duration_hint}
Hook type required: {hook_type}

Available facts (use 2–4 of the most compelling ones):
{facts_block}

Return ONLY a JSON object with this exact structure:
{{
  "hook": "<single powerful opening sentence that stops the scroll>",
  "segments": [
    {{
      "sentence": "<one sentence of narration>",
      "search_query": "<2–4 word footage search term e.g. 'orca jumping ocean'>",
      "visual_type": "<one of: action, close_up, wide, comparison, text_only>",
      "fact_index": <integer index into the facts array above, or -1 if not from a fact>
    }}
  ],
  "cta_placeholder": "<REPLACE_WITH_CTA>",
  "full_text": "<all sentences joined with spaces>"
}}

Rules:
- The hook must be the most alarming or curious sentence.
- Each segment sentence must be short enough to fit one video clip (3–5 seconds of narration).
- search_query must be specific enough to find real footage (e.g. "orca hunting shark" not "ocean").
- Do not add any text outside the JSON object.
"""
        return self.generate_json(prompt=prompt, system_prompt=system, max_tokens=1_200)

    def generate_video_title(
        self,
        topic_name: str,
        category: str,
        title_type: str,
        template: str,
    ) -> str:
        """
        Generate a YouTube video title by filling a template pattern.
        Returns a single title string, NOT a JSON object.
        """
        prompt = (
            f"Fill in this YouTube title template for a nature/science video.\n\n"
            f"Template: {template}\n"
            f"Topic: {topic_name}\n"
            f"Category: {category}\n"
            f"Title type: {title_type}\n\n"
            f"Rules:\n"
            f"- Replace all [PLACEHOLDER] tokens with real, specific values.\n"
            f"- The title must create strong curiosity or urgency.\n"
            f"- Maximum 70 characters.\n"
            f"- No clickbait lies — every claim must be accurate.\n"
            f"- Return ONLY the final title string. No quotes, no explanation."
        )
        return self.generate_text(
            prompt=prompt,
            system_prompt="You are an expert YouTube title writer for nature channels.",
            max_tokens=80,
            temperature=0.6,
        )

    def generate_video_description(
        self,
        topic_name: str,
        category: str,
        title: str,
        key_facts: list,
    ) -> str:
        """Generate a YouTube video description (150–300 words)."""
        facts_str = " ".join(f"• {f}" for f in key_facts[:3])
        prompt = (
            f"Write a YouTube video description for the following video.\n\n"
            f"Title: {title}\n"
            f"Topic: {topic_name}\n"
            f"Category: {category}\n"
            f"Key facts to mention: {facts_str}\n\n"
            f"Requirements:\n"
            f"- 150 to 300 words.\n"
            f"- First sentence must be a strong hook that mirrors the title energy.\n"
            f"- Second paragraph: 2–3 interesting facts from the video.\n"
            f"- End with: 'Follow for a new nature fact every day.'\n"
            f"- Do NOT include hashtags (they are added separately).\n"
            f"- Write in plain English, no markdown formatting."
        )
        return self.generate_text(
            prompt=prompt,
            system_prompt="You write compelling YouTube video descriptions for nature channels.",
            max_tokens=400,
            temperature=0.65,
        )

    def verify_fact_consistency(
        self, fact_text: str, topic: str, source_names: list
    ) -> Dict[str, Any]:
        """
        Ask the LLM to assess whether a fact sounds plausible and consistent
        with scientific consensus.  Returns a dict:
        {
          "plausible": true/false,
          "confidence": 0–100,
          "concern": "..." or null
        }
        """
        sources_str = ", ".join(source_names) if source_names else "none provided"
        prompt = (
            f"Evaluate this scientific fact for plausibility.\n\n"
            f"Topic: {topic}\n"
            f"Fact: {fact_text}\n"
            f"Sources cited: {sources_str}\n\n"
            f"Return a JSON object:\n"
            f"{{\n"
            f'  "plausible": true or false,\n'
            f'  "confidence": integer 0–100 (how confident you are it is accurate),\n'
            f'  "concern": "describe any scientific concern" or null\n'
            f"}}"
        )
        try:
            return self.generate_json(
                prompt=prompt,
                system_prompt="You are a science fact-checker with expertise in biology, astronomy, and natural history.",
                max_tokens=200,
            )
        except RuntimeError:
            # If fact verification itself fails, return a neutral result so
            # the pipeline can continue with human review flagging
            return {"plausible": True, "confidence": 50, "concern": "Fact verification LLM call failed — manual review recommended."}

    # ═════════════════════════════════════════════════════════════════════════
    # Diagnostics
    # ═════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """Return cascade health status for the war room dashboard."""
        return {
            "category": "llm",
            "provider_count": self._manager.provider_count(),
            "available_providers": self._manager.get_available_providers(),
            "circuit_status": self._manager.get_circuit_status(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_llm_instance: Optional[LLMCascade] = None


def get_llm() -> LLMCascade:
    """
    Return the process-level singleton LLMCascade.
    All engines call this function — never instantiate LLMCascade directly.
    """
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMCascade()
    return _llm_instance

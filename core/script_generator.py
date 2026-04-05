"""
core/script_generator.py
========================
Generates video scripts for MindCraft Psychology Shorts.

Pipeline
--------
1. Accept a TopicSeed from research.py.
2. Build a structured LLM prompt using the seed + channel identity.
3. Call Gemini API (primary) → parse JSON → validate with Pydantic.
4. If Gemini fails at any step, transparently fall back to Groq.
5. Check generated hook+body against SQLite dedup table.
   If duplicate → regenerate up to MAX_REGEN_ATTEMPTS times.
6. Persist the unique script to the DB and return the full ScriptResult.

All external calls are wrapped with @with_retry (exponential backoff).
The primary→fallback handoff is handled by utils/fallback.py.

Usage
-----
    from core.research import ResearchEngine
    from core.script_generator import ScriptGenerator

    engine    = ResearchEngine()
    generator = ScriptGenerator()

    seeds   = engine.get_topic_seeds(count=1)
    script  = generator.generate(seed=seeds[0])
    # script.script_id  → UUID in DB
    # script.hook       → "If someone does this while talking…"
    # script.body       → "Their brain is triggering mirror neurons…"
"""

import json
import re
import time
from typing import Optional

import google.generativeai as genai
from groq import Groq
from pydantic import BaseModel, Field, field_validator, ValidationError

from config.api_keys import get_gemini_key, get_groq_key
from config.settings import (
    CTA_TEXT,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    GROQ_MAX_TOKENS,
    GROQ_MODEL,
    GROQ_TEMPERATURE,
    SCRIPT_SYSTEM_PROMPT,
    YT_DEFAULT_TAGS,
)
from core.research import TopicSeed
from database.db import Database
from utils.fallback import run_with_fallback, validate_script_result
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger(__name__)

# Maximum times we'll ask the LLM to try again if a duplicate is detected
MAX_REGEN_ATTEMPTS: int = 5


# ══════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMA — validated output contract
# ══════════════════════════════════════════════════════════════════════════

class ScriptResult(BaseModel):
    """
    Validated, typed container for one generated Short script.
    Pydantic enforces types and applies coercions / validators
    before anything downstream touches the data.
    """
    script_id:   str = Field(default="", description="UUID assigned after DB insert")
    hook:        str = Field(..., min_length=5,  max_length=200)
    body:        str = Field(..., min_length=10, max_length=500)
    cta:         str = Field(default=CTA_TEXT)
    title:       str = Field(..., min_length=5,  max_length=100)
    description: str = Field(..., min_length=10, max_length=1000)
    tags:        list[str] = Field(..., min_length=1)
    topic:       str = Field(..., min_length=2)
    llm_provider: str = Field(default="gemini")

    @field_validator("hook")
    @classmethod
    def hook_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("hook cannot be blank")
        return v

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("body cannot be blank")
        return v

    @field_validator("tags")
    @classmethod
    def merge_default_tags(cls, v: list[str]) -> list[str]:
        """Ensure the Pydantic model always carries channel-level tags."""
        combined = list(dict.fromkeys(v + YT_DEFAULT_TAGS))  # dedup, order preserved
        return combined[:20]   # YouTube allows max 500 chars total; 20 tags is safe

    @field_validator("cta")
    @classmethod
    def enforce_cta(cls, v: str) -> str:
        """Always use the canonical CTA regardless of what the LLM returned."""
        return CTA_TEXT


# ══════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════

def _build_user_prompt(seed: TopicSeed, attempt: int = 1) -> str:
    """
    Construct the user-turn prompt sent to the LLM.

    Injects the topic seed context and adds a uniqueness nudge on
    re-generation attempts so the LLM doesn't produce the same hook twice.
    """
    uniqueness_note = (
        f"\n\nIMPORTANT: This is regeneration attempt {attempt}. "
        "The previous script was rejected as a duplicate. "
        "You MUST use a completely different hook angle and opening phrase."
    ) if attempt > 1 else ""

    context_block = seed.to_prompt_context()

    return (
        f"{context_block}\n\n"
        f"Write one complete YouTube Shorts script for MindCraft Psychology "
        f"based on this topic. The script must follow the 3-frame structure:\n"
        f"  Frame 1 (hook)  — 1 punchy sentence, max 12 words, open loop / "
        f"pattern interrupt. Start with 'If someone…', 'The moment you…', "
        f"'Most people don't know…', 'Scientists found…', or similar.\n"
        f"  Frame 2 (body)  — 1-2 sentences, the mind-blowing psychological "
        f"fact, max 30 words, factually accurate.\n"
        f"  Frame 3 (cta)   — exactly: '{CTA_TEXT}'\n\n"
        f"Return ONLY a valid JSON object. No markdown fences, no preamble."
        f"{uniqueness_note}"
    )


# ══════════════════════════════════════════════════════════════════════════
# JSON PARSER
# ══════════════════════════════════════════════════════════════════════════

def _parse_llm_json(raw: str) -> dict:
    """
    Extract and parse the JSON object from a raw LLM string response.

    LLMs sometimes wrap output in ```json ... ``` fences despite instructions.
    This function strips fences, then parses.  Raises ValueError on failure.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    # Find the outermost {...} block in case there is surrounding text
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(
            f"No JSON object found in LLM response. Raw (first 300 chars): "
            f"{raw[:300]}"
        )

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc}. Raw snippet: {raw[:300]}") from exc


# ══════════════════════════════════════════════════════════════════════════
# GEMINI CALLER
# ══════════════════════════════════════════════════════════════════════════

class _GeminiCaller:
    """Thin wrapper around the Gemini SDK for script generation."""

    def __init__(self) -> None:
        genai.configure(api_key=get_gemini_key())
        self._model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SCRIPT_SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=GEMINI_TEMPERATURE,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",  # Gemini 1.5+ supports this
            ),
        )

    @with_retry()
    def generate(self, user_prompt: str) -> dict:
        """
        Call Gemini and return a parsed dict.
        Decorated with @with_retry so transient API errors are retried
        before the fallback chain gives up on this provider entirely.
        """
        logger.debug("Calling Gemini model '%s' …", GEMINI_MODEL)
        response = self._model.generate_content(user_prompt)

        raw_text = response.text
        logger.debug("Gemini raw response (first 200 chars): %s", raw_text[:200])

        parsed = _parse_llm_json(raw_text)
        parsed["llm_provider"] = "gemini"
        return parsed


# ══════════════════════════════════════════════════════════════════════════
# GROQ CALLER (fallback)
# ══════════════════════════════════════════════════════════════════════════

class _GroqCaller:
    """Thin wrapper around the Groq SDK for script generation."""

    def __init__(self) -> None:
        self._client = Groq(api_key=get_groq_key())

    @with_retry()
    def generate(self, user_prompt: str) -> dict:
        """
        Call Groq (llama3-8b) and return a parsed dict.
        The system prompt is passed as a system message so the same
        SCRIPT_SYSTEM_PROMPT constant is used as in the Gemini path.
        """
        logger.debug("Calling Groq model '%s' …", GROQ_MODEL)
        completion = self._client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system",  "content": SCRIPT_SYSTEM_PROMPT},
                {"role": "user",    "content": user_prompt},
            ],
            max_tokens=GROQ_MAX_TOKENS,
            temperature=GROQ_TEMPERATURE,
            response_format={"type": "json_object"},   # Groq supports this
        )

        raw_text = completion.choices[0].message.content
        logger.debug("Groq raw response (first 200 chars): %s", raw_text[:200])

        parsed = _parse_llm_json(raw_text)
        parsed["llm_provider"] = "groq"
        return parsed


# ══════════════════════════════════════════════════════════════════════════
# SCRIPT GENERATOR — public interface
# ══════════════════════════════════════════════════════════════════════════

class ScriptGenerator:
    """
    Orchestrates LLM calls, JSON validation, and SQLite deduplication
    to produce a unique, production-ready ScriptResult for each Short.

    Parameters
    ----------
    db : Database instance.  Defaults to a new Database() using DB_PATH.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db     = db or Database()
        self._gemini = _GeminiCaller()
        self._groq   = _GroqCaller()

        # Ensure schema exists (idempotent)
        self._db.init()

    # ── Public ─────────────────────────────────────────────────────────────

    def generate(self, seed: TopicSeed) -> ScriptResult:
        """
        Generate and persist a unique script for the given TopicSeed.

        Deduplication loop
        ------------------
        After each LLM response we check db.script_exists(hook, body).
        If a match is found we ask the LLM to regenerate with a uniqueness
        note in the prompt, up to MAX_REGEN_ATTEMPTS times.
        If all attempts produce duplicates, GenerationError is raised.

        Parameters
        ----------
        seed : TopicSeed from ResearchEngine.get_topic_seeds().

        Returns
        -------
        ScriptResult with a populated script_id (UUID from DB).

        Raises
        ------
        GenerationError : All LLM attempts + regen cycles failed.
        """
        logger.info(
            "Generating script for topic: '%s' (source=%s)",
            seed.keyword, seed.source,
        )

        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_REGEN_ATTEMPTS + 1):
            try:
                script_dict = self._call_llm_with_fallback(seed, attempt)
                result      = self._validate(script_dict)

                # ── Deduplication check ────────────────────────────────────
                if self._db.script_exists(result.hook, result.body):
                    logger.warning(
                        "Duplicate detected on attempt %d/%d — regenerating …",
                        attempt, MAX_REGEN_ATTEMPTS,
                    )
                    # Small backoff before re-prompting to avoid hammering API
                    time.sleep(1.5)
                    continue

                # ── Unique — persist and return ────────────────────────────
                script_id = self._db.insert_script(
                    hook=result.hook,
                    body=result.body,
                    cta=result.cta,
                    title=result.title,
                    description=result.description,
                    tags=result.tags,
                    topic=result.topic,
                    source_trend=seed.keyword,
                    llm_provider=result.llm_provider,
                )
                result.script_id = script_id

                logger.info(
                    "Script generated and saved: id=%s provider=%s topic='%s'",
                    script_id, result.llm_provider, result.topic,
                )
                return result

            except Exception as exc:
                last_error = exc
                logger.error(
                    "Script generation attempt %d/%d failed: %s",
                    attempt, MAX_REGEN_ATTEMPTS, exc,
                )
                if attempt < MAX_REGEN_ATTEMPTS:
                    time.sleep(2 ** attempt)   # brief backoff between full regen cycles

        raise GenerationError(
            f"All {MAX_REGEN_ATTEMPTS} script generation attempts failed "
            f"for topic '{seed.keyword}'. Last error: {last_error}"
        )

    def generate_batch(self, seeds: list[TopicSeed]) -> list[ScriptResult]:
        """
        Generate one script per seed.  Failures on individual seeds are
        logged and skipped rather than crashing the entire batch.

        Returns a (possibly shorter) list of successful ScriptResults.
        """
        results: list[ScriptResult] = []
        for i, seed in enumerate(seeds, 1):
            logger.info("Batch: generating script %d/%d …", i, len(seeds))
            try:
                results.append(self.generate(seed))
            except GenerationError as exc:
                logger.error("Batch: skipping seed '%s' — %s", seed.keyword, exc)
        return results

    # ── Private helpers ────────────────────────────────────────────────────

    def _call_llm_with_fallback(self, seed: TopicSeed, attempt: int) -> dict:
        """
        Build the prompt and call Gemini → Groq via run_with_fallback().
        Returns a raw dict (not yet Pydantic-validated).
        """
        user_prompt = _build_user_prompt(seed, attempt)

        return run_with_fallback(
            primary=lambda: self._gemini.generate(user_prompt),
            fallback=lambda: self._groq.generate(user_prompt),
            primary_name="Gemini",
            fallback_name="Groq",
            validator=validate_script_result,
        )

    def _validate(self, raw_dict: dict) -> ScriptResult:
        """
        Parse raw LLM dict into a ScriptResult via Pydantic.
        Raises ValueError (caught by the generation loop) on schema mismatch.
        """
        try:
            return ScriptResult(**raw_dict)
        except ValidationError as exc:
            # Convert Pydantic's verbose error into a plain ValueError
            # so the retry/fallback machinery handles it uniformly
            fields = [e["loc"][0] for e in exc.errors()]
            raise ValueError(
                f"Script validation failed on fields {fields}: {exc.errors()}"
            ) from exc


# ══════════════════════════════════════════════════════════════════════════
# CUSTOM EXCEPTION
# ══════════════════════════════════════════════════════════════════════════

class GenerationError(RuntimeError):
    """
    Raised when ScriptGenerator.generate() cannot produce a unique,
    valid script after exhausting all retry and regen attempts.
    """
    pass


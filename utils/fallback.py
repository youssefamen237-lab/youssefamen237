"""
utils/fallback.py
=================
Generic primary → fallback execution chain used throughout the pipeline.

Why this exists
---------------
Every external dependency has a free-tier limit or can be unavailable.
Rather than duplicating try/except blocks in every module, this utility
provides a single, composable pattern:

    result = run_with_fallback(
        primary=lambda: call_gemini(prompt),
        fallback=lambda: call_groq(prompt),
        primary_name="Gemini",
        fallback_name="Groq",
    )

If the primary raises any exception, the fallback is tried automatically.
If both fail, a FallbackExhaustedError is raised with the full error context.

Usage patterns
--------------
1. Two-provider LLM chain (Gemini → Groq):
       run_with_fallback(primary=gemini_fn, fallback=groq_fn)

2. Multi-provider chain (3+ options):
       run_with_fallback_chain([pexels_fn, pixabay_fn, local_fn], names=[...])

3. Validate + fallback: pass a `validator` callable that inspects the result
   and raises ValueError if it looks wrong — this triggers the fallback too.
"""

from typing import Any, Callable, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Custom exception ───────────────────────────────────────────────────────

class FallbackExhaustedError(RuntimeError):
    """
    Raised when every provider in a fallback chain has failed.
    Carries the individual error from each provider for diagnostics.
    """
    def __init__(self, errors: dict[str, Exception]) -> None:
        self.errors = errors
        details = "; ".join(
            f"{name}: {type(exc).__name__}({exc})"
            for name, exc in errors.items()
        )
        super().__init__(
            f"All providers failed. Errors — {details}"
        )


# ── Core two-provider helper ───────────────────────────────────────────────

def run_with_fallback(
    primary: Callable[[], Any],
    fallback: Callable[[], Any],
    primary_name: str = "Primary",
    fallback_name: str = "Fallback",
    validator: Optional[Callable[[Any], None]] = None,
) -> Any:
    """
    Call `primary()`.  If it raises (or if `validator` rejects its result),
    call `fallback()`.  If both fail, raise FallbackExhaustedError.

    Parameters
    ----------
    primary      : Zero-argument callable for the preferred provider.
    fallback     : Zero-argument callable for the backup provider.
    primary_name : Label used in log messages.
    fallback_name: Label used in log messages.
    validator    : Optional callable that receives the result and raises
                   ValueError / AssertionError if the result is invalid.
                   This lets you treat a bad response (e.g. malformed JSON)
                   as a failure that triggers the fallback.

    Returns
    -------
    The result from whichever provider succeeded first.

    Raises
    ------
    FallbackExhaustedError : Both providers raised an exception.
    """
    errors: dict[str, Exception] = {}

    # ── Try primary ────────────────────────────────────────────────────────
    try:
        logger.debug("Calling primary provider: %s", primary_name)
        result = primary()

        if validator:
            validator(result)       # raises if result is structurally wrong

        logger.info("Provider '%s' succeeded.", primary_name)
        return result

    except Exception as exc:
        logger.warning(
            "Provider '%s' failed (%s: %s). Switching to fallback '%s' …",
            primary_name, type(exc).__name__, str(exc)[:200], fallback_name,
        )
        errors[primary_name] = exc

    # ── Try fallback ───────────────────────────────────────────────────────
    try:
        logger.debug("Calling fallback provider: %s", fallback_name)
        result = fallback()

        if validator:
            validator(result)

        logger.info("Fallback provider '%s' succeeded.", fallback_name)
        return result

    except Exception as exc:
        logger.error(
            "Fallback provider '%s' also failed (%s: %s).",
            fallback_name, type(exc).__name__, str(exc)[:200],
        )
        errors[fallback_name] = exc

    raise FallbackExhaustedError(errors)


# ── Multi-provider chain (3+ providers) ───────────────────────────────────

def run_with_fallback_chain(
    providers: list[Callable[[], Any]],
    names: Optional[list[str]] = None,
    validator: Optional[Callable[[Any], None]] = None,
) -> Any:
    """
    Try each provider in order until one succeeds.

    Parameters
    ----------
    providers : Ordered list of zero-argument callables.
    names     : Optional human-readable names parallel to providers.
                Defaults to ["Provider_1", "Provider_2", …].
    validator : Same semantics as in run_with_fallback().

    Returns
    -------
    Result from the first successful provider.

    Raises
    ------
    FallbackExhaustedError : Every provider failed.
    ValueError             : providers list is empty.
    """
    if not providers:
        raise ValueError("run_with_fallback_chain: providers list cannot be empty.")

    if names is None:
        names = [f"Provider_{i + 1}" for i in range(len(providers))]

    if len(names) != len(providers):
        raise ValueError(
            "run_with_fallback_chain: 'names' must have the same length as 'providers'."
        )

    errors: dict[str, Exception] = {}

    for provider, name in zip(providers, names):
        try:
            logger.debug("Trying provider: %s", name)
            result = provider()

            if validator:
                validator(result)

            logger.info("Provider '%s' succeeded.", name)
            return result

        except Exception as exc:
            logger.warning(
                "Provider '%s' failed (%s: %s).",
                name, type(exc).__name__, str(exc)[:200],
            )
            errors[name] = exc

    raise FallbackExhaustedError(errors)


# ── Convenience: result validator for JSON script dicts ───────────────────

def validate_script_result(result: Any) -> None:
    """
    Validator for script_generator.py results.
    Pass this as the `validator` argument to run_with_fallback() so that
    a structurally incomplete LLM response triggers the fallback provider
    instead of propagating garbage downstream.

    Raises
    ------
    ValueError : result is not a dict or is missing required keys.
    """
    required_keys = {"hook", "body", "cta", "title", "description", "tags", "topic"}

    if not isinstance(result, dict):
        raise ValueError(
            f"Script result must be a dict, got {type(result).__name__}."
        )

    missing = required_keys - result.keys()
    if missing:
        raise ValueError(
            f"Script result missing required keys: {sorted(missing)}"
        )

    if not isinstance(result.get("tags"), list) or len(result["tags"]) == 0:
        raise ValueError("Script result 'tags' must be a non-empty list.")

    # Soft length guards (log warnings, don't fail — LLMs occasionally overshoot)
    hook_len = len(result.get("hook", "").split())
    if hook_len > 20:
        logger.warning(
            "Hook is %d words (target ≤12): '%s'",
            hook_len, result["hook"][:80],
        )

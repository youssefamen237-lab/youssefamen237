"""
cascade/cascade_manager.py

Generic cascade routing engine used by every category in the system
(LLM, TTS, footage, images, AI images, AI video, thumbnails).

Features
────────
  Circuit Breaker    Skip a provider that has failed N times recently.
                     Auto-resets after a configurable timeout.
  Per-provider retry Retry up to max_retries times with exponential back-off
                     before declaring a provider failed and moving to the next.
  Structured logging Every skip, retry, success, and failure is logged with
                     full context for post-mortem analysis.
  Graceful exhaustion When all providers fail, returns a rich ProviderResult
                     containing the full attempt log rather than raising.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import structlog

from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    In-process circuit breaker.  State is local to the current process
    (i.e. not shared across GitHub Actions jobs), which is intentional —
    each workflow run starts with a clean slate.

    States
    ──────
    CLOSED   Fewer than failure_threshold consecutive failures → provider is used.
    OPEN     failure_threshold reached → provider is skipped until reset_timeout.
    (No HALF-OPEN state: the circuit simply auto-resets after the timeout.)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: int = 300,
    ) -> None:
        self._threshold = failure_threshold
        self._timeout = reset_timeout_seconds
        self._failures: Dict[str, int] = {}
        self._first_failure_at: Dict[str, float] = {}

    def is_open(self, provider_name: str) -> bool:
        """Return True if the circuit is open and the provider should be skipped."""
        failures = self._failures.get(provider_name, 0)
        if failures < self._threshold:
            return False
        elapsed = time.time() - self._first_failure_at.get(provider_name, 0.0)
        if elapsed > self._timeout:
            self._reset(provider_name)
            logger.info(
                "circuit_breaker_auto_reset",
                provider=provider_name,
                elapsed_seconds=round(elapsed),
            )
            return False
        return True

    def record_failure(self, provider_name: str) -> None:
        """Increment the failure counter.  Sets the first-failure timestamp on first call."""
        if provider_name not in self._failures:
            self._failures[provider_name] = 0
            self._first_failure_at[provider_name] = time.time()
        self._failures[provider_name] += 1
        new_count = self._failures[provider_name]
        if new_count >= self._threshold:
            logger.warning(
                "circuit_breaker_opened",
                provider=provider_name,
                failures=new_count,
                threshold=self._threshold,
                will_reset_in_seconds=self._timeout,
            )

    def record_success(self, provider_name: str) -> None:
        """Clear the failure record on a successful response."""
        if provider_name in self._failures:
            self._reset(provider_name)

    def _reset(self, provider_name: str) -> None:
        self._failures.pop(provider_name, None)
        self._first_failure_at.pop(provider_name, None)

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Return the current state of all tracked providers."""
        return {
            name: {
                "failures": count,
                "is_open": self.is_open(name),
                "seconds_since_first_failure": round(
                    time.time() - self._first_failure_at.get(name, time.time())
                ),
            }
            for name, count in self._failures.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# CascadeManager
# ─────────────────────────────────────────────────────────────────────────────

class CascadeManager:
    """
    Routes a request through an ordered list of providers, falling back to
    the next provider whenever one is unavailable, circuit-open, or fails.

    Usage
    ─────
        cascade = CascadeManager(
            providers=[GeminiProvider(), GroqProvider(), OpenRouterProvider()],
            category="llm",
            max_retries_per_provider=2,
        )
        result = cascade.execute(prompt="...", response_format="text")
        if result.success:
            print(result.data)
        else:
            print(result.error)   # full audit trail
    """

    def __init__(
        self,
        providers: List[BaseProvider],
        category: str,
        max_retries_per_provider: int = 2,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        if not providers:
            raise ValueError(
                f"CascadeManager for '{category}' requires at least one provider."
            )
        self.providers = providers
        self.category = category
        self.max_retries = max_retries_per_provider
        self.breaker = circuit_breaker or CircuitBreaker()
        self._attempt_log: List[Dict[str, Any]] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def execute(self, **kwargs: Any) -> ProviderResult:
        """
        Try each provider in priority order.
        Returns the first successful ProviderResult.
        Returns a failure ProviderResult (success=False) when all are exhausted.
        Never raises.
        """
        self._attempt_log = []

        for provider in self.providers:
            pname = provider.provider_name

            # ── Circuit breaker gate ──────────────────────────────────────────
            if self.breaker.is_open(pname):
                logger.info(
                    "cascade_skip_circuit_open",
                    category=self.category,
                    provider=pname,
                )
                self._attempt_log.append(
                    {"provider": pname, "skipped": "circuit_open"}
                )
                continue

            # ── Availability gate ─────────────────────────────────────────────
            try:
                available = provider.is_available()
            except Exception as chk_exc:
                logger.warning(
                    "cascade_availability_check_error",
                    category=self.category,
                    provider=pname,
                    error=str(chk_exc),
                )
                available = False

            if not available:
                logger.info(
                    "cascade_skip_unavailable",
                    category=self.category,
                    provider=pname,
                )
                self._attempt_log.append(
                    {"provider": pname, "skipped": "unavailable"}
                )
                continue

            # ── Execute with per-provider retry ───────────────────────────────
            logger.info(
                "cascade_trying_provider",
                category=self.category,
                provider=pname,
            )
            result = self._attempt_with_retry(provider, **kwargs)

            if result.success:
                self.breaker.record_success(pname)
                self._attempt_log.append(
                    {"provider": pname, "outcome": "success"}
                )
                logger.info(
                    "cascade_success",
                    category=self.category,
                    provider=pname,
                )
                return result

            # Provider failed all retries
            self.breaker.record_failure(pname)
            self._attempt_log.append(
                {"provider": pname, "outcome": "failed", "error": result.error}
            )
            logger.warning(
                "cascade_provider_exhausted",
                category=self.category,
                provider=pname,
                error=result.error,
            )

        # All providers exhausted
        audit = " | ".join(
            "{provider}:{info}".format(
                provider=a["provider"],
                info=a.get("error", a.get("skipped", "unknown")),
            )
            for a in self._attempt_log
        )
        logger.error(
            "cascade_all_providers_exhausted",
            category=self.category,
            attempts=self._attempt_log,
        )
        return ProviderResult(
            success=False,
            data=None,
            provider_used="none",
            error=f"All {self.category} providers exhausted. [{audit}]",
            metadata={"attempts": self._attempt_log},
        )

    def get_attempt_log(self) -> List[Dict[str, Any]]:
        """Return a copy of the detailed attempt log from the last execute() call."""
        return list(self._attempt_log)

    def get_available_providers(self) -> List[str]:
        """Return names of providers whose circuit is currently closed."""
        return [
            p.provider_name
            for p in self.providers
            if not self.breaker.is_open(p.provider_name)
        ]

    def get_circuit_status(self) -> Dict[str, Any]:
        """Return circuit breaker state for all providers."""
        return self.breaker.get_status()

    def provider_count(self) -> int:
        return len(self.providers)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _attempt_with_retry(
        self, provider: BaseProvider, **kwargs: Any
    ) -> ProviderResult:
        """
        Call provider.execute() up to self.max_retries times.
        Uses exponential back-off between attempts (1 s → 2 s → 4 s … capped at 16 s).
        Returns the last ProviderResult regardless of success or failure.
        """
        last_result = ProviderResult.failure(
            provider.provider_name, "No attempts completed."
        )
        wait_seconds = 1.0

        for attempt in range(1, self.max_retries + 1):
            try:
                result = provider.execute(**kwargs)
            except Exception as exc:
                # provider.execute() violated the no-raise contract; handle it here
                result = ProviderResult.failure(
                    provider.provider_name,
                    f"Unhandled exception on attempt {attempt}/{self.max_retries}: {exc}",
                )

            if result.success:
                return result

            last_result = result
            logger.debug(
                "cascade_retry",
                provider=provider.provider_name,
                attempt=attempt,
                max_retries=self.max_retries,
                wait_seconds=wait_seconds,
                error=result.error,
            )

            if attempt < self.max_retries:
                time.sleep(wait_seconds)
                wait_seconds = min(wait_seconds * 2.0, 16.0)

        return last_result

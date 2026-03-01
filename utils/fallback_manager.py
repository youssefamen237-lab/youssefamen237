"""
utils/fallback_manager.py – Quizzaro Fallback Manager
======================================================
Tracks which services have failed in the current run and selects
the next available provider. Used by AIEngine and TTSEngine.
"""
from __future__ import annotations
from loguru import logger


class FallbackManager:

    def __init__(self) -> None:
        # Maps service_name → set of failed provider names
        self._failed: dict[str, set[str]] = {}

    def mark_failed(self, service: str, provider: str) -> None:
        self._failed.setdefault(service, set()).add(provider)
        logger.warning(f"[Fallback] Marked '{provider}' as failed for service '{service}'")

    def is_failed(self, service: str, provider: str) -> bool:
        return provider in self._failed.get(service, set())

    def reset(self, service: str) -> None:
        self._failed.pop(service, None)

    def all_failed(self, service: str, providers: list[str]) -> bool:
        failed = self._failed.get(service, set())
        return all(p in failed for p in providers)

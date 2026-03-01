"""
core/question_bank.py – Quizzaro Question Bank
================================================
Thin orchestrator that wires AIEngine + ContentFetcher + AntiDuplicate
into the ContentEngine and exposes a single clean interface:

    bank = QuestionBank(ai_engine, content_fetcher, anti_duplicate)
    question: QuestionObject = bank.get_next_question()

Also reads strategy_config.json to honour the ProjectManager's
preferred categories, templates, and target audiences.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from loguru import logger

from core.anti_duplicate import AntiDuplicate
from core.content_engine import ContentEngine, QuestionObject

STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")


class QuestionBank:

    def __init__(self, ai_engine, content_fetcher, anti_duplicate: AntiDuplicate) -> None:
        self._ai = ai_engine
        self._fetcher = content_fetcher
        self._anti_dup = anti_duplicate
        self._engine = self._build_engine()

    def _build_engine(self) -> ContentEngine:
        return ContentEngine(
            gemini_key=self._ai._gemini_key,
            groq_key=self._ai._groq_key,
            openrouter_key=self._ai._openrouter_key,
            news_api_key=self._fetcher._news_key,
            youtube_api_key=self._fetcher._yt_key,
        )

    def _load_strategy(self) -> dict:
        if STRATEGY_CONFIG_PATH.exists():
            try:
                with open(STRATEGY_CONFIG_PATH, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_next_question(self, max_attempts: int = 12) -> QuestionObject:
        """
        Return the next unique, validated QuestionObject.
        Respects top_categories and top_audiences from strategy_config.json
        when available; falls back to full random pool otherwise.
        """
        strategy = self._load_strategy()

        top_categories = strategy.get("top_categories", [])
        top_audiences = strategy.get("top_audiences", [])
        top_templates = strategy.get("top_templates", [])
        bad_templates = set(strategy.get("underperforming_templates", []))
        bad_categories = set(strategy.get("underperforming_categories", []))

        # Inject strategy preferences into the engine if available
        if top_categories:
            from core.content_engine import CATEGORIES
            # Bias 60% towards top performers, 40% random exploration
            self._engine.__dict__.setdefault("_strategy_categories", top_categories)

        if top_templates:
            from core.content_engine import TEMPLATES
            preferred = [t for t in top_templates if t not in bad_templates]
            if preferred:
                self._engine.__dict__["_strategy_templates"] = preferred

        logger.info("[QuestionBank] Fetching next question …")
        question = self._engine.get_next_question(max_attempts=max_attempts)
        return question

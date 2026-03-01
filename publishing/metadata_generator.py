"""
publishing/metadata_generator.py – Quizzaro Metadata Generator
===============================================================
Generates unique, SEO-optimised YouTube titles for every Short.
Uses AI with a strict prompt to prevent misleading metadata.
Falls back to a deterministic template pool if AI fails.
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime

from loguru import logger

TITLE_TEMPLATES = [
    "🧠 {question_short} | Can YOU Answer? #Shorts",
    "⚡ Only Geniuses Get This Right! #{category} #Shorts",
    "🤔 {question_short}? 99% FAIL This Quiz! #Shorts",
    "🏆 How Smart Are You? {category} Quiz #Shorts",
    "💡 {question_short} | Comment Before It Reveals! #Shorts",
    "🎯 Quick {difficulty} Quiz! {category} #Shorts",
    "🔥 Test Your Brain! {question_short} #Shorts",
    "⏳ 5 Second Challenge | {category} Trivia #Shorts",
    "🌍 Did You Know This? {category} #Facts #Shorts",
    "🥇 {question_short} | Drop Your Answer! #Shorts",
]


class MetadataGenerator:

    def __init__(self, ai_engine) -> None:
        self._ai = ai_engine

    def generate(self, question_object) -> dict:
        """
        Generate title for a QuestionObject (dataclass or dict).
        Returns {"title": str}.
        """
        from dataclasses import asdict
        if hasattr(question_object, "__dataclass_fields__"):
            q = asdict(question_object)
        else:
            q = question_object

        title = self._ai_title(q) or self._fallback_title(q)
        return {"title": title[:100]}

    def _ai_title(self, q: dict) -> str | None:
        question_text = q.get("question_text", "")
        category = q.get("category", "trivia")
        difficulty = q.get("difficulty", "medium")
        template = q.get("template", "quiz")

        prompt = f"""Write ONE YouTube Short title for this trivia video.

Question: {question_text}
Category: {category}
Difficulty: {difficulty}
Template: {template.replace('_', ' ')}

Rules:
- Maximum 90 characters including spaces
- Must contain exactly one emoji at the start
- Must end with #Shorts
- Must be attention-grabbing and curiosity-inducing
- Must NOT be misleading or clickbait
- Must NOT ask a different question than what's in the video
- English only
- Output ONLY the title string, nothing else"""

        try:
            raw = self._ai.generate_raw(prompt).strip()
            # Strip any quotes or extra lines the model might add
            raw = re.sub(r'^["\']|["\']$', "", raw.split("\n")[0].strip())
            if 10 < len(raw) <= 100 and "#Shorts" in raw:
                return raw
        except Exception as exc:
            logger.warning(f"[MetaGen] AI title failed: {exc}")
        return None

    def _fallback_title(self, q: dict) -> str:
        template_str = random.choice(TITLE_TEMPLATES)
        question_text = q.get("question_text", "What's the answer?")
        # Shorten question to ~40 chars for use in title
        short_q = question_text[:40].rstrip() + ("…" if len(question_text) > 40 else "")
        title = template_str.format(
            question_short=short_q,
            category=q.get("category", "Trivia").title(),
            difficulty=q.get("difficulty", "Medium").title(),
        )
        return title[:100]

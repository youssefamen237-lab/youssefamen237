from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from ..generators.types import QuizItem
from ..utils.text import clamp_text, shuffle_copy

SHORT_TITLE_TEMPLATES = [
    "Can you answer this in 3 seconds? 🤯",
    "Only geniuses get this one 😳",
    "Quick quiz: can you solve it?",
    "Don’t blink… 3 seconds only!",
    "Most people get this wrong 😅",
    "Be honest… did you know this?",
    "Comment before the answer shows!",
    "This one is harder than it looks 👀",
    "Easy or impossible? You decide!",
    "Let’s test your brain 🧠",
]

SHORT_DESC_TEMPLATES = [
    "{q}\n\n{cta}\n\nSubscribe for daily quizzes!",
    "Try this one!\n\n{q}\n\n{cta}\n\nNew shorts every day. Subscribe!",
    "{q}\n\n{cta}\n\nIf you enjoy quick trivia, subscribe 🔥",
    "3-second challenge!\n\n{q}\n\n{cta}\n\nMore quizzes daily. Subscribe ✅",
]

LONG_TITLE_TEMPLATES = [
    "Ultimate Trivia Challenge (Try Not To Pause!)",
    "General Knowledge Quiz Compilation (Hard Mode)",
    "Can You Beat This Trivia Test? (No Cheating!)",
    "BIG Trivia Compilation: 5+ Minutes of Questions!",
    "The Best Quick Trivia Questions (Compilation)",
]

LONG_DESC_TEMPLATES = [
    "Welcome to the trivia compilation!\n\n{cta}\n\nSubscribe for more quizzes every week!",
    "A full quiz compilation with lots of questions.\n\n{cta}\n\nNew videos every week. Subscribe!",
    "Try to answer before the reveal.\n\n{cta}\n\nLike & subscribe for more!",
]

CTA_POOL = [
    "Comment your score at the end!",
    "How many did you get right? Comment below!",
    "Write your score in the comments!",
    "Play with a friend and compare scores!",
]


def _pick_hashtags(cfg: Dict[str, Any], extra: Optional[List[str]] = None, k: int = 4) -> List[str]:
    base = list(cfg.get("seo", {}).get("base_hashtags") or [])
    if extra:
        base.extend(extra)
    base = list(dict.fromkeys(base))
    random.shuffle(base)
    return base[:k]


def _pick_tags(cfg: Dict[str, Any], *, kind: str, k: int = 10) -> List[str]:
    pool_name = "short_tags_pool" if kind == "short" else "long_tags_pool"
    pool = list(cfg.get("seo", {}).get(pool_name) or [])
    pool = list(dict.fromkeys(pool))
    random.shuffle(pool)
    return pool[:k]


def build_short_metadata(cfg: Dict[str, Any], item: QuizItem) -> Dict[str, Any]:
    q = item.question.strip()
    cta = item.cta.strip()

    title = random.choice(SHORT_TITLE_TEMPLATES)
    # Occasionally include a short hint of the question
    if random.random() < 0.35:
        hint = clamp_text(q, 42)
        title = f"{title} | {hint}"

    title = clamp_text(title, 95)

    desc_tpl = random.choice(SHORT_DESC_TEMPLATES)
    description = desc_tpl.format(q=q, cta=cta)

    hashtags = _pick_hashtags(cfg, extra=["#trivias", "#quiztime"], k=random.randint(3, 6))
    description = description + "\n\n" + " ".join(hashtags)

    tags = _pick_tags(cfg, kind="short", k=random.randint(8, 14))

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": "24",
    }


def build_long_metadata(cfg: Dict[str, Any], items: List[QuizItem]) -> Dict[str, Any]:
    title = random.choice(LONG_TITLE_TEMPLATES)
    title = clamp_text(title, 95)

    cta = random.choice(CTA_POOL)
    desc_tpl = random.choice(LONG_DESC_TEMPLATES)
    description = desc_tpl.format(cta=cta)

    hashtags = _pick_hashtags(cfg, extra=["#trivia", "#quiz"], k=random.randint(3, 6))
    description = description + "\n\n" + " ".join(hashtags)

    tags = _pick_tags(cfg, kind="long", k=random.randint(10, 18))

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": "24",
    }

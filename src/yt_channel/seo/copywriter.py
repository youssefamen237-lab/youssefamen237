from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..state.db import StateDB


@dataclass(frozen=True)
class SEOResult:
    title: str
    description: str
    hashtags: List[str]
    tags: List[str]
    title_style_id: str


def _clean_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _title_prefix(title: str, n: int = 12) -> str:
    t = re.sub(r"[^a-z0-9]+", "", title.lower())
    return t[:n]


def _enforce_title_length(title: str, min_len: int = 30, max_len: int = 60) -> str:
    t = title.strip()
    if len(t) > max_len:
        t = t[:max_len].rstrip()
        if t and t[-1] in {",", "-", "|"}:
            t = t[:-1].rstrip()
    if len(t) < min_len:
        t = t + " " + "Trivia"
        t = t[:max_len].rstrip()
    return t


def _extract_country(question_text: str) -> Optional[str]:
    m = re.search(r"capital of ([^?]+)\?", question_text, flags=re.I)
    if m:
        return _clean_space(m.group(1))
    m = re.search(r"currency code for ([^?]+)\?", question_text, flags=re.I)
    if m:
        return _clean_space(m.group(1))
    m = re.search(r"capital of ([^\n]+)", question_text, flags=re.I)
    if m:
        return _clean_space(m.group(1))
    return None


def _extract_flag(question_text: str) -> Optional[str]:
    # Grab any flag emoji present
    m = re.search(r"([\U0001F1E6-\U0001F1FF]{2})", question_text)
    if m:
        return m.group(1)
    return None


class Copywriter:
    def __init__(self, *, rng: random.Random, db: StateDB) -> None:
        self.rng = rng
        self.db = db

        self.title_styles_short: List[Tuple[str, str]] = [
            ("t1", "Quick Quiz: {focus} 🤔"),
            ("t2", "Can You Guess {focus}?"),
            ("t3", "Trivia Challenge: {focus} ⚡"),
            ("t4", "Guess It Fast: {focus}"),
            ("t5", "Test Your Knowledge: {focus}"),
            ("t6", "Mini Trivia: {focus}"),
            ("t7", "3 Seconds to Answer: {focus}"),
            ("t8", "One Question Quiz: {focus} 🎯"),
            ("t9", "How Well Do You Know {focus}?"),
            ("t10", "Fast Facts Quiz: {focus}"),
        ]

        self.title_styles_long: List[Tuple[str, str]] = [
            ("L1", "Ultimate Trivia Challenge — {focus}"),
            ("L2", "Play Along: {focus} Quiz"),
            ("L3", "Can You Beat This Trivia Score? {focus}"),
            ("L4", "New Trivia Episode: {focus}"),
        ]

        self.desc_templates_short: List[str] = [
            "Think you can get it in 3 seconds?\nSubscribe for daily trivia!",
            "A quick quiz to test your knowledge.\nMore trivia shorts every day!",
            "Can you answer before the timer ends?\nSubscribe for more quick quizzes!",
            "Short, fun, and fast — try this one.\nFollow for daily trivia challenges!",
            "One question. One timer. One answer.\nSubscribe for more trivia!",
        ]

        self.desc_templates_long: List[str] = [
            "Play along and keep score — how many can you get right?\nSubscribe for new trivia episodes.",
            "A full-length trivia episode with multiple rounds.\nComment your score and subscribe!",
            "Ready for a longer challenge?\nSubscribe and come back for the next episode.",
        ]

        self.hashtag_pool_short = [
            "#shorts",
            "#trivia",
            "#quiz",
            "#geography",
            "#generalknowledge",
            "#guess",
            "#education",
            "#funfacts",
        ]

        self.hashtag_pool_long = [
            "#trivia",
            "#quiz",
            "#generalknowledge",
            "#geography",
            "#challenge",
            "#learn",
        ]

        self.tag_pool_common = [
            "trivia",
            "quiz",
            "general knowledge",
            "guess",
            "challenge",
            "fun",
            "education",
            "short quiz",
        ]

        self.tag_pool_geo = [
            "geography trivia",
            "capitals quiz",
            "flags quiz",
            "countries",
            "world capitals",
            "flag guessing",
            "maps",
        ]

        self.tag_pool_math = [
            "quick math",
            "mental math",
            "math quiz",
            "brain teaser",
        ]

        self.tag_pool_space = [
            "space trivia",
            "planets",
            "solar system",
        ]

    def _pick_hashtags(self, *, kind: str) -> List[str]:
        pool = self.hashtag_pool_short if kind == "short" else self.hashtag_pool_long
        k = self.rng.randint(3, 5)
        # Always include #shorts for shorts
        base = ["#shorts"] if kind == "short" and "#shorts" in pool else []
        remaining = [h for h in pool if h not in base]
        self.rng.shuffle(remaining)
        tags = base + remaining[: max(0, k - len(base))]
        return tags[:5]

    def _pick_tags(self, *, topic: str) -> List[str]:
        tags = list(self.tag_pool_common)
        if topic in {"capital", "flag", "currency", "mcq_capitals", "true_false", "two_step"}:
            tags += self.tag_pool_geo
        if topic == "math":
            tags += self.tag_pool_math
        if topic == "planets":
            tags += self.tag_pool_space
        # Deduplicate
        uniq = []
        seen = set()
        for t in tags:
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(t)
        self.rng.shuffle(uniq)
        return uniq[: self.rng.randint(10, 15)]

    def _focus_text(self, *, topic: str, question_text: str) -> str:
        country = _extract_country(question_text)
        flag = _extract_flag(question_text)
        if topic in {"capital", "mcq_capitals", "true_false", "two_step"} and country:
            return f"the capital of {country}"
        if topic == "flag" and flag:
            return "this flag"
        if topic == "currency" and country:
            return f"the currency of {country}"
        if topic == "math":
            return "this quick math"
        if topic == "planets":
            return "the solar system"
        return "this trivia"

    def _avoid_repetition(self, title: str) -> bool:
        recent = self.db.recent_titles(limit=60)
        pref = _title_prefix(title)
        for rt in recent:
            if _title_prefix(rt) == pref:
                return False
        return True

    def make(self, *, kind: str, topic: str, question_text: str) -> SEOResult:
        focus = self._focus_text(topic=topic, question_text=question_text)
        styles = self.title_styles_short if kind == "short" else self.title_styles_long

        title = ""
        style_id = ""
        for _ in range(30):
            style_id, tmpl = self.rng.choice(styles)
            raw = tmpl.format(focus=focus)
            raw = _clean_space(raw)
            raw = _enforce_title_length(raw)
            if self._avoid_repetition(raw):
                title = raw
                break
        if not title:
            style_id, tmpl = styles[0]
            title = _enforce_title_length(_clean_space(tmpl.format(focus=focus)))

        desc_tmpls = self.desc_templates_short if kind == "short" else self.desc_templates_long
        description = self.rng.choice(desc_tmpls)

        hashtags = self._pick_hashtags(kind=kind)
        # Rotate hashtag sets (avoid exact same set)
        recent_sets = self.db.recent_hashtag_sets(limit=40)
        for _ in range(20):
            if hashtags not in recent_sets:
                break
            hashtags = self._pick_hashtags(kind=kind)

        description = description + "\n" + " ".join(hashtags[:5])

        tags = self._pick_tags(topic=topic)

        return SEOResult(
            title=title,
            description=description,
            hashtags=hashtags,
            tags=tags,
            title_style_id=style_id,
        )

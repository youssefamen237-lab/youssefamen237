from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from .utils.text_utils import sanitize_text


@dataclass
class SeoPack:
    title: str
    description: str
    tags: List[str]


_TITLE_TEMPLATES = [
    "Can you answer this {topic} question?",
    "Quick {topic} quiz: can you get it right?",
    "{topic} trivia challenge — 1 question!",
    "Test your {topic} knowledge in 10 seconds",
    "{topic} quiz: guess the answer fast",
    "One quick {topic} question for you",
]

_TITLE_PREFIXES = [
    "Quick Quiz",
    "Trivia Time",
    "Fast Challenge",
    "Guess It",
    "Brain Boost",
    "Mini Quiz",
]

_EMOJIS = ["", "🤔", "🎯", "🧠", "✨", "⚡"]

_DESC_OPENERS = [
    "A quick trivia question to test your knowledge.",
    "Can you get this one before the timer ends?",
    "Short, fun, and fast — one trivia question.",
    "Let’s see how quick your brain is today.",
]

_CTA_LINES = [
    "Subscribe for daily quiz shorts.",
    "New trivia every day — follow along!",
    "Drop your answer in the comments.",
    "Challenge a friend in the comments.",
]

_HASHTAG_SETS = [
    ["#trivia", "#quiz", "#shorts"],
    ["#quiz", "#trivia", "#challenge"],
    ["#trivia", "#knowledge", "#shorts"],
    ["#quiz", "#brain", "#shorts"],
    ["#trivia", "#fun", "#shorts"],
]

_BASE_TAGS = [
    "trivia",
    "quiz",
    "shorts",
    "fun",
    "knowledge",
    "challenge",
    "brain",
    "question",
    "facts",
    "learning",
]

_TOPIC_TAGS = {
    "Geography": ["geography", "countries", "capitals", "flags"],
    "Math": ["math", "mental math", "numbers"],
    "Science": ["science", "space", "planets", "facts"],
    "Animals": ["animals", "wildlife"],
    "Myths": ["true or false", "facts"],
}


def _one_emoji() -> str:
    e = random.choice(_EMOJIS)
    return e


def _clamp_title_len(title: str, min_len: int = 30, max_len: int = 60) -> str:
    title = sanitize_text(title)
    if len(title) < min_len:
        # pad by adding a short suffix
        title = f"{title} | Quick Trivia"
    if len(title) > max_len:
        title = title[:max_len].rstrip(" -|:,")
    return title


def build_seo(topic: str, question: str, for_long: bool = False) -> SeoPack:
    topic = sanitize_text(topic) or "Trivia"
    base = random.choice(_TITLE_TEMPLATES).format(topic=topic)
    prefix = random.choice(_TITLE_PREFIXES)
    emoji = _one_emoji()

    # Ensure we don't look like numbered/compiled content
    if emoji:
        raw_title = f"{prefix}: {base} {emoji}"
    else:
        raw_title = f"{prefix}: {base}"

    title = _clamp_title_len(raw_title)

    opener = random.choice(_DESC_OPENERS)
    cta = random.choice(_CTA_LINES)
    hashtags = random.choice(_HASHTAG_SETS)

    # 2 natural lines + hashtags
    desc = f"{opener}\n{cta}\n\n" + " ".join(hashtags[:5])

    tags = list(_BASE_TAGS)
    tags.extend(_TOPIC_TAGS.get(topic, []))

    # Add a couple topic-related keywords from the question (safe, basic)
    q_low = question.lower()
    for kw in ["capital", "country", "planet", "element", "currency", "ocean", "continent", "true", "false"]:
        if kw in q_low and kw not in tags:
            tags.append(kw)

    # Long-form: emphasize episode/scoreboard but no numbering
    if for_long:
        title = _clamp_title_len(f"{prefix}: {topic} Trivia Episode {emoji}".strip())
        desc = f"{opener}\nPlay along and keep score!\n\n" + " ".join(hashtags[:5])
        if "episode" not in tags:
            tags.append("episode")
        if "score" not in tags:
            tags.append("score")

    # 10-15 tags
    random.shuffle(tags)
    tags = tags[: random.randint(10, 15)]

    return SeoPack(title=title, description=desc, tags=tags)


# Back-compat wrapper expected by planner

def generate_seo(qa, template_id: str = 'classic_countdown') -> SeoPack:
    for_long = (template_id == 'long_episode')
    return build_seo(topic=getattr(qa, 'topic', 'Trivia') or 'Trivia', question=getattr(qa, 'question', ''), for_long=for_long)

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class LongTheme:
    key: str
    topic: str
    keyword: str
    thing: str
    tags: list[str]


THEMES: list[LongTheme] = [
    LongTheme(
        key="FLAGS",
        topic="Flags",
        keyword="FLAGS",
        thing="the Country",
        tags=["flags", "flag quiz", "country flags", "guess the flag", "geography", "trivia"],
    ),
    LongTheme(
        key="LOGOS",
        topic="Logos",
        keyword="LOGOS",
        thing="the Brand",
        tags=["logos", "logo quiz", "brand logos", "guess the logo", "trivia", "brands"],
    ),
    LongTheme(
        key="MOVIES",
        topic="Movies",
        keyword="MOVIES",
        thing="the Movie",
        tags=["movies", "movie quiz", "film trivia", "guess the movie", "trivia"],
    ),
    LongTheme(
        key="GK",
        topic="General Knowledge",
        keyword="GK",
        thing="the Answer",
        tags=["general knowledge", "gk", "quiz", "trivia", "brain teaser", "knowledge"],
    ),
]


def theme_by_key(key: str) -> LongTheme:
    k = (key or "").strip().upper()
    for t in THEMES:
        if t.key.upper() == k:
            return t
    return THEMES[0]


@dataclass(frozen=True)
class LongMeta:
    title: str
    description: str
    tags: list[str]
    keyword: str
    badge: str
    subline: str


_TITLE_TEMPLATES: list[str] = [
    "Can You Score {score}/{n}? | {topic} Quiz",
    "99% Fail This {topic} Challenge 😅 ({n} Qs)",
    "Guess {thing} in {timer} | {topic} (Hard Mode)",
    "Only Geniuses Get {topic} Right 🤯 | {n} Questions",
    "{topic} Quiz Marathon | Beat {score}/{n}",
    "HARD MODE: {topic} Quiz | {timer}",
    "How Many Can You Get? {topic} Quiz ({n} Questions)",
    "Fast {topic} Quiz | Comment Your Score! ({n} Qs)",
    "{topic} Challenge | {timer} Each!",
    "Ultimate {topic} Quiz | {n} Questions (No Cheating!)",
]


def pick_theme(seed: int) -> LongTheme:
    r = random.Random(seed)
    return r.choice(THEMES)


def build_long_meta(theme: LongTheme, *, n_questions: int, countdown_choices: list[int], seed: int) -> LongMeta:
    r = random.Random(seed)

    cd_min = min(countdown_choices) if countdown_choices else 8
    cd_max = max(countdown_choices) if countdown_choices else 10
    timer = f"{cd_min}-{cd_max}s" if cd_min != cd_max else f"{cd_max}s"

    # A score target that feels human (not always 10/10)
    score = max(1, min(n_questions, int(round(n_questions * r.uniform(0.65, 0.9)))))

    template = _TITLE_TEMPLATES[seed % len(_TITLE_TEMPLATES)]
    title = template.format(score=score, n=n_questions, topic=theme.topic, thing=theme.thing, timer=timer)
    title = title.replace("  ", " ").strip()
    if len(title) > 100:
        title = title[:97].rstrip() + "..."

    badge_pool = [
        "HARD MODE",
        "NO HINTS",
        "SUDDEN DEATH",
        f"{r.randint(7, 9)}/10?",
        f"{timer} TIMER",
        f"{n_questions} Qs",
    ]
    badge = r.choice(badge_pool)

    subline_pool = [
        f"{n_questions} QUESTIONS",
        f"{timer} TIMER",
        "TRY NOT TO CHEAT",
        "COMMENT YOUR SCORE",
        "QUIZ CHALLENGE",
    ]
    subline = r.choice(subline_pool)

    desc = (
        f"{theme.topic} quiz challenge!\n"
        f"\n"
        f"✅ {n_questions} questions\n"
        f"⏱️ Timer: {timer}\n"
        f"\n"
        f"Comment your score below 👇\n"
        f"Subscribe to Quizzaro for more quizzes!"
    )

    tags = _dedup_tags(
        [
            "quiz",
            "trivia",
            "challenge",
            "brain teaser",
            "quizzaro",
            "compilation",
            "daily quiz",
            *theme.tags,
        ]
    )

    return LongMeta(
        title=title,
        description=desc,
        tags=tags,
        keyword=theme.keyword,
        badge=badge,
        subline=subline,
    )


def _dedup_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for t in tags:
        tt = (t or "").strip()
        if not tt:
            continue
        k = tt.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(tt)
    # YouTube tags max is 500 chars total, but we keep it modest.
    return out[:25]

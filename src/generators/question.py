from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Tuple

from ..state import StateStore
from ..utils.text import clamp_list, normalize_text
from .llm import LLMOrchestrator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShortSpec:
    question: str
    answer: str
    category: str
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]

    def voice_script(self) -> str:
        return (
            "Quick quiz. "
            f"{self.question} "
            "You have 10 seconds. "
            "If you know the answer before time runs out, write it in the comments."
        )


_BANNED = [
    r"\blyrics\b",
    r"\bthis line\b",
    r"\bwhich song\b",
    r"\bwhat song\b",
    r"\bmovie quote\b",
    r"\bwho said\b",
    r"\bbrand slogan\b",
    r"\bpolitic\w*\b",
    r"\belection\b",
    r"\bterror\w*\b",
    r"\bviolence\b",
    r"\bsex\w*\b",
    r"\bnsfw\b",
    r"\bdrug\w*\b",
    r"\bweapon\w*\b",
]
_BANNED_RE = re.compile("|".join(_BANNED), re.IGNORECASE)


def _looks_safe(question: str, answer: str) -> bool:
    q = normalize_text(question)
    a = normalize_text(answer)
    if not q or not a:
        return False
    if len(q) < 8 or len(q) > 120:
        return False
    if len(a) < 1 or len(a) > 60:
        return False
    if "http" in q or "www" in q or "http" in a or "www" in a:
        return False
    if _BANNED_RE.search(q) or _BANNED_RE.search(a):
        return False
    if question.count("\n") > 4:
        return False
    return True


def _coerce_list(x: Any) -> list[str]:
    if isinstance(x, list):
        out = []
        for it in x:
            if isinstance(it, str) and it.strip():
                out.append(it.strip())
        return out
    if isinstance(x, str):
        return [s.strip() for s in x.split(",") if s.strip()]
    return []


def _ensure_question_mark(q: str) -> str:
    s = (q or "").strip()
    if not s:
        return s
    s = s.replace("  ", " ")
    if s.endswith("."):
        s = s[:-1].strip()
    if not s.endswith("?"):
        s = s + "?"
    return s


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for it in items:
        s = (it or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _detect_niche(question: str, category: str) -> Tuple[str, list[str], list[str]]:
    t = normalize_text(f"{question} {category}")

    space_kw = ["planet", "solar", "space", "astronomy", "galaxy", "moon", "mars", "jupiter", "saturn", "nasa", "orbit"]
    geo_kw = ["capital", "country", "flag", "continent", "geography", "city", "ocean", "mountain", "river", "map"]
    sci_kw = ["element", "chemical", "atom", "physics", "chemistry", "biology", "science", "molecule", "energy"]
    math_kw = ["math", "solve", "equation", "number", "puzzle", "riddle", "brain", "logic", "calculate", "×", "+", "-"]
    hist_kw = ["history", "ancient", "year", "century", "empire", "war", "dynasty"]

    if any(k in t for k in space_kw):
        return (
            "space",
            ["#space", "#astronomy", "#solarsystem", "#planet", "#spacefacts"],
            ["space", "astronomy", "solar system", "planet", "space facts"],
        )
    if any(k in t for k in geo_kw):
        return (
            "geography",
            ["#geography", "#countries", "#capitals", "#world", "#flags"],
            ["geography", "countries", "capital cities", "world facts", "flags"],
        )
    if any(k in t for k in sci_kw):
        return (
            "science",
            ["#science", "#facts", "#chemistry", "#physics", "#biology"],
            ["science", "facts", "chemistry", "physics", "biology"],
        )
    if any(k in t for k in math_kw):
        return (
            "brain",
            ["#math", "#puzzle", "#brain", "#braintest", "#challenge"],
            ["math", "puzzle", "brain test", "challenge", "mental math"],
        )
    if any(k in t for k in hist_kw):
        return (
            "history",
            ["#history", "#facts", "#learn", "#didyouknow", "#timeline"],
            ["history", "facts", "learn", "did you know", "timeline"],
        )

    return (
        "general",
        ["#facts", "#knowledge", "#learn", "#didyouknow", "#funfacts"],
        ["facts", "knowledge", "learn", "did you know", "fun facts"],
    )


def _build_seo(question: str, category: str) -> tuple[str, str, list[str], list[str]]:
    q = _ensure_question_mark(question)
    niche_label, niche_hashtags, niche_tags = _detect_niche(q, category)

    hashtags = _dedupe_keep_order(["#shorts", "#trivia", "#quiz", niche_hashtags[0], niche_hashtags[1]])
    hashtags = hashtags[:5]

    title = q
    suffix = " (10s Quiz)"
    if len(title) + len(suffix) <= 90:
        title = title + suffix

    desc_lines = [
        q,
        "Test your knowledge in this quick short! Comment your answer before the timer ends.",
        "",
        "🚀 Quick facts",
        "🧠 Trivia challenge",
        "⏳ 10-second timer",
        "",
        " ".join(hashtags),
    ]
    description = "\n".join(desc_lines).strip()

    tags_base = ["trivia", "quiz", "general knowledge"]
    if niche_label == "space":
        tags_base += ["space", "astronomy"]
    elif niche_label == "geography":
        tags_base += ["geography", "countries"]
    elif niche_label == "science":
        tags_base += ["science", "facts"]
    elif niche_label == "brain":
        tags_base += ["math", "puzzle"]
    elif niche_label == "history":
        tags_base += ["history", "facts"]
    else:
        tags_base += ["facts", "learn"]

    tags = _dedupe_keep_order(tags_base + niche_tags)
    tags = [t.strip() for t in tags if t.strip()]
    tags = tags[:12]
    if len(tags) < 5:
        tags = _dedupe_keep_order(tags + ["shorts", "fun facts", "daily trivia"])[:12]

    return title, description, tags, hashtags


def _local_bank(rng: random.Random) -> ShortSpec:
    capitals = [
        ("Japan", "Tokyo"),
        ("France", "Paris"),
        ("Canada", "Ottawa"),
        ("Brazil", "Brasília"),
        ("Australia", "Canberra"),
        ("Egypt", "Cairo"),
        ("Turkey", "Ankara"),
        ("Mexico", "Mexico City"),
        ("Argentina", "Buenos Aires"),
        ("South Korea", "Seoul"),
        ("India", "New Delhi"),
        ("Spain", "Madrid"),
        ("Italy", "Rome"),
        ("Norway", "Oslo"),
        ("Sweden", "Stockholm"),
        ("Finland", "Helsinki"),
        ("Greece", "Athens"),
        ("Portugal", "Lisbon"),
        ("Poland", "Warsaw"),
        ("Netherlands", "Amsterdam"),
        ("Belgium", "Brussels"),
        ("Switzerland", "Bern"),
        ("Austria", "Vienna"),
        ("Ireland", "Dublin"),
        ("Denmark", "Copenhagen"),
        ("China", "Beijing"),
        ("Thailand", "Bangkok"),
        ("Vietnam", "Hanoi"),
        ("Indonesia", "Jakarta"),
        ("South Africa", "Pretoria"),
    ]

    elements = [
        ("Hydrogen", "H"),
        ("Helium", "He"),
        ("Carbon", "C"),
        ("Oxygen", "O"),
        ("Sodium", "Na"),
        ("Potassium", "K"),
        ("Iron", "Fe"),
        ("Gold", "Au"),
        ("Silver", "Ag"),
        ("Copper", "Cu"),
        ("Mercury", "Hg"),
        ("Tin", "Sn"),
        ("Lead", "Pb"),
    ]

    planets = [
        ("largest planet in our solar system", "Jupiter"),
        ("closest planet to the Sun", "Mercury"),
        ("planet known as the Red Planet", "Mars"),
        ("planet with the most famous rings", "Saturn"),
    ]

    modes = ["capital", "element", "planet", "math"]
    mode = rng.choice(modes)

    if mode == "capital":
        country, capital = rng.choice(capitals)
        q = f"What is the capital of {country}?"
        a = capital
        cat = "Geography"
    elif mode == "element":
        element, symbol = rng.choice(elements)
        q = f"Which element has the chemical symbol '{symbol}'?"
        a = element
        cat = "Science"
    elif mode == "planet":
        prompt, ans = rng.choice(planets)
        q = f"What is the {prompt}?"
        a = ans
        cat = "Space"
    else:
        x = rng.randint(12, 99)
        y = rng.randint(3, 9)
        op = rng.choice(["+", "-", "×"])
        if op == "+":
            q = f"Solve this in your head: {x} + {y} = ?"
            a = str(x + y)
        elif op == "-":
            q = f"Solve this in your head: {x} - {y} = ?"
            a = str(x - y)
        else:
            m1 = rng.randint(3, 12)
            m2 = rng.randint(3, 12)
            q = f"Solve this in your head: {m1} × {m2} = ?"
            a = str(m1 * m2)
        cat = "Brain Teaser"

    title, description, tags, hashtags = _build_seo(q, cat)
    return ShortSpec(
        question=_ensure_question_mark(q),
        answer=str(a).strip(),
        category=cat,
        title=title,
        description=description,
        tags=tags,
        hashtags=hashtags,
    )


def generate_unique_short_spec(llm: LLMOrchestrator, state: StateStore, rng: random.Random) -> ShortSpec:
    prompt_template = (
        "You generate SAFE, non-copyrighted, English-only trivia for a 12-second YouTube Short.\n"
        "Return ONLY valid JSON with these keys exactly:\n"
        "question, answer, category\n\n"
        "Rules:\n"
        "- Audience: international (English).\n"
        "- No song lyrics, no movie quotes, no copyrighted lines, no brand slogans.\n"
        "- No politics, hate, sex, violence, weapons, drugs.\n"
        "- The question must be answerable in 10 seconds.\n"
        "- The answer must be short (1-4 words or a number).\n\n"
        "Avoid repeating any of these (do not reuse or paraphrase closely):\n"
        "{recent}\n"
    )

    used = state.data.get("used_questions", {})
    recent_qs = []
    if isinstance(used, dict):
        for v in list(used.values())[-30:]:
            if isinstance(v, dict) and isinstance(v.get("q"), str):
                recent_qs.append(v["q"])

    recent = "\n".join(f"- {q}" for q in recent_qs[-20:]) if recent_qs else "- (none)"
    prompt = prompt_template.format(recent=recent)

    for attempt in range(1, 7):
        try:
            obj = llm.generate_json(prompt, max_tokens=420)
            q = _ensure_question_mark(str(obj.get("question", "")).strip())
            a = str(obj.get("answer", "")).strip()
            cat = str(obj.get("category", "General Knowledge")).strip() or "General Knowledge"

            if not _looks_safe(q, a):
                raise ValueError("unsafe/invalid question")
            if state.is_used(q):
                raise ValueError("duplicate question")

            title, description, tags, hashtags = _build_seo(q, cat)

            tags = clamp_list(tags, 450)
            return ShortSpec(
                question=q,
                answer=a,
                category=cat,
                title=title,
                description=description,
                tags=tags,
                hashtags=hashtags,
            )
        except Exception as e:
            log.warning("Question generation attempt %d failed: %s", attempt, str(e))

    for _ in range(1, 50):
        spec = _local_bank(rng)
        if _looks_safe(spec.question, spec.answer) and not state.is_used(spec.question):
            return spec
    return _local_bank(rng)

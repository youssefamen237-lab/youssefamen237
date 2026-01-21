from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .trivia_opentdb import fetch_question as fetch_opentdb
from .types import QuizItem
from ..utils.hashing import sha256_hex
from ..utils.text import clamp_text, shuffle_copy

log = logging.getLogger("templates")

CTA_POOL = [
    "Comment your answer!",
    "Drop your guess below!",
    "Type your answer in the comments!",
    "Can you solve it? Comment!",
    "Be honest—what’s your guess?",
    "Got it? Comment now!",
    "No cheating—comment your answer!",
    "Answer fast—comment below!",
    "What do you think? Comment!",
    "Can you get it in 3 seconds? Comment!",
]

CAPITALS: List[Tuple[str, str]] = [
    ("France", "Paris"),
    ("Spain", "Madrid"),
    ("Italy", "Rome"),
    ("Germany", "Berlin"),
    ("United Kingdom", "London"),
    ("Ireland", "Dublin"),
    ("Portugal", "Lisbon"),
    ("Netherlands", "Amsterdam"),
    ("Belgium", "Brussels"),
    ("Switzerland", "Bern"),
    ("Austria", "Vienna"),
    ("Poland", "Warsaw"),
    ("Czech Republic", "Prague"),
    ("Hungary", "Budapest"),
    ("Greece", "Athens"),
    ("Turkey", "Ankara"),
    ("Egypt", "Cairo"),
    ("Morocco", "Rabat"),
    ("South Africa", "Pretoria"),
    ("Nigeria", "Abuja"),
    ("Kenya", "Nairobi"),
    ("Saudi Arabia", "Riyadh"),
    ("UAE", "Abu Dhabi"),
    ("Qatar", "Doha"),
    ("India", "New Delhi"),
    ("Pakistan", "Islamabad"),
    ("China", "Beijing"),
    ("Japan", "Tokyo"),
    ("South Korea", "Seoul"),
    ("Thailand", "Bangkok"),
    ("Vietnam", "Hanoi"),
    ("Indonesia", "Jakarta"),
    ("Australia", "Canberra"),
    ("New Zealand", "Wellington"),
    ("Canada", "Ottawa"),
    ("United States", "Washington, D.C."),
    ("Mexico", "Mexico City"),
    ("Brazil", "Brasília"),
    ("Argentina", "Buenos Aires"),
    ("Chile", "Santiago"),
    ("Colombia", "Bogotá"),
]

COMMON_WORDS = [
    "elephant","giraffe","penguin","octopus","dolphin","volcano","ocean","planet","galaxy",
    "pyramid","diamond","rainbow","thunder","library","keyboard","internet","football","basketball",
    "chocolate","sandwich","breakfast","mountain","waterfall","island","desert","forest","meteor",
]

EMOJI_PUZZLES: List[Dict[str, str]] = [
    {"q": "Emoji quiz: 🍎📱 = ?", "a": "Apple"},
    {"q": "Emoji quiz: 🕷️👨 = ?", "a": "Spider-Man"},
    {"q": "Emoji quiz: 🦇👨 = ?", "a": "Batman"},
    {"q": "Emoji quiz: 🌧️🌈 = ?", "a": "Rainbow"},
    {"q": "Emoji quiz: 🧊🍵 = ?", "a": "Iced tea"},
    {"q": "Emoji quiz: 🐼🍃 = ?", "a": "Panda"},
]

WHICH_ONE_PROMPTS: List[Tuple[str, str, str]] = [
    ("Which is bigger?", "Elephant", "Mouse"),
    ("Which is faster?", "Cheetah", "Turtle"),
    ("Which is colder?", "Antarctica", "Sahara"),
    ("Which has more letters?", "Wednesday", "Sunday"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _qid(template: str, question: str, answer: str) -> str:
    return sha256_hex(f"{template}|{question}|{answer}")[:16]


def make_true_false(max_q: int, max_a: int) -> Optional[QuizItem]:
    q = fetch_opentdb(qtype="boolean")
    if not q:
        return None
    question = f"True or False: {q['question']}"
    answer = str(q["answer"]).strip()
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("true_false", question, answer),
        template="true_false",
        question=question,
        answer=answer,
        options=["True", "False"],
        category=q.get("category"),
        difficulty=q.get("difficulty"),
        cta=cta,
        created_at_iso=_now_iso(),
        extra={"source": q.get("source")},
    )


def make_mcq_3(max_q: int, max_a: int) -> Optional[QuizItem]:
    q = fetch_opentdb(qtype="multiple")
    if not q:
        return None
    options = q.get("options") or []
    options = [str(x).strip() for x in options if str(x).strip()]
    if len(options) < 3:
        return None
    # take 3 options including correct
    correct = str(q["answer"]).strip()
    if correct not in options:
        options.append(correct)
    random.shuffle(options)
    options = options[:3]
    if correct not in options:
        options[-1] = correct
        random.shuffle(options)

    question = str(q["question"]).strip()
    answer = correct
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("mcq_3", question, answer),
        template="mcq_3",
        question=question,
        answer=answer,
        options=options,
        category=q.get("category"),
        difficulty=q.get("difficulty"),
        cta=cta,
        created_at_iso=_now_iso(),
        extra={"source": q.get("source")},
    )


def make_fill_blank(max_q: int, max_a: int) -> Optional[QuizItem]:
    country, capital = random.choice(CAPITALS)
    question = f"The capital of {country} is ____."
    answer = capital
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("fill_blank", question, answer),
        template="fill_blank",
        question=question,
        answer=answer,
        options=None,
        category="Geography",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra=None,
    )


def make_capital_city(max_q: int, max_a: int) -> Optional[QuizItem]:
    country, capital = random.choice(CAPITALS)
    question = f"What is the capital of {country}?"
    answer = capital
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("capital_city", question, answer),
        template="capital_city",
        question=question,
        answer=answer,
        options=None,
        category="Geography",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra=None,
    )


def make_quick_math(max_q: int, max_a: int) -> QuizItem:
    ops = ["+", "-", "×"]
    op = random.choice(ops)
    if op == "+":
        a = random.randint(7, 49)
        b = random.randint(7, 49)
        ans = a + b
    elif op == "-":
        a = random.randint(20, 99)
        b = random.randint(3, 19)
        ans = a - b
    else:
        a = random.randint(3, 12)
        b = random.randint(3, 12)
        ans = a * b

    question = f"Quick math: {a} {op} {b} = ?"
    answer = str(ans)
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("quick_math", question, answer),
        template="quick_math",
        question=question,
        answer=answer,
        options=None,
        category="Math",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra=None,
    )


def make_word_scramble(max_q: int, max_a: int) -> QuizItem:
    word = random.choice(COMMON_WORDS + [c for _, c in CAPITALS])
    clean = "".join([ch for ch in word if ch.isalpha()]).lower()
    if len(clean) < 4:
        clean = random.choice(COMMON_WORDS)
    chars = list(clean)
    random.shuffle(chars)
    scrambled = "".join(chars).upper()
    question = f"Unscramble: {scrambled}"
    answer = clean.title()
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("word_scramble", question, answer),
        template="word_scramble",
        question=question,
        answer=answer,
        options=None,
        category="Word",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra={"scrambled": scrambled, "word": clean},
    )


def make_emoji_logic(max_q: int, max_a: int) -> QuizItem:
    item = random.choice(EMOJI_PUZZLES)
    question = item["q"]
    answer = item["a"]
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("emoji_logic", question, answer),
        template="emoji_logic",
        question=question,
        answer=answer,
        options=None,
        category="Emoji",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra=None,
    )


def make_which_one(max_q: int, max_a: int) -> QuizItem:
    q, a, b = random.choice(WHICH_ONE_PROMPTS)
    # Randomly pick which is correct (not always factual; keep it playful)
    correct = random.choice([a, b])
    question = f"{q} {a} or {b}?"
    answer = correct
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("which_one", question, answer),
        template="which_one",
        question=question,
        answer=answer,
        options=[a, b],
        category="Fun",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra=None,
    )


def make_spot_difference(max_q: int, max_a: int) -> QuizItem:
    # Images generated later by the renderer; we just choose a simple difference descriptor.
    differences = [
        ("One star is missing", "STAR"),
        ("The circle changes color", "CIRCLE"),
        ("A square disappears", "SQUARE"),
        ("The triangle flips", "TRIANGLE"),
        ("One dot moves", "DOT"),
    ]
    desc, code = random.choice(differences)
    question = "Spot the difference!"
    answer = desc
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = random.choice(CTA_POOL)
    return QuizItem(
        qid=_qid("spot_difference", question, answer),
        template="spot_difference",
        question=question,
        answer=answer,
        options=None,
        category="Puzzle",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra={"diff_code": code},
    )


def make_sports_prediction(max_q: int, max_a: int) -> Optional[QuizItem]:
    teams = [
        "Real Madrid",
        "Barcelona",
        "Manchester City",
        "Liverpool",
        "Arsenal",
        "Chelsea",
        "Manchester United",
        "Bayern Munich",
        "PSG",
        "Inter Miami",
    ]
    a, b = random.sample(teams, k=2)
    question = f"Predict the score: {a} vs {b}"
    # playful prediction
    ga = random.randint(0, 3)
    gb = random.randint(0, 3)
    answer = f"My pick: {ga}-{gb}"
    question = clamp_text(question, max_q)
    answer = clamp_text(answer, max_a)
    cta = "Comment your prediction!"
    return QuizItem(
        qid=_qid("sports_prediction", question, answer),
        template="sports_prediction",
        question=question,
        answer=answer,
        options=None,
        category="Sports",
        difficulty=None,
        cta=cta,
        created_at_iso=_now_iso(),
        extra={"teams": [a, b], "pred": [ga, gb]},
    )

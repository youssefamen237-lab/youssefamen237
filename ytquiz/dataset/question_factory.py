from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from ytquiz.safety import is_safe_text
from ytquiz.state import StateDB
from ytquiz.utils import clamp, normalize_text, sha256_text

from ytquiz.dataset.elements import ELEMENTS
from ytquiz.dataset.science import BASIC_FACTS, OCEANS, PLANETS_ORDER


@dataclass(frozen=True)
class QuizItem:
    topic_id: str
    question_text: str
    answer_text: str
    options: list[str] | None
    correct_option_index: int | None
    hint_text: str | None
    difficulty: float
    countdown_seconds: int
    question_hash: str


def generate_short_question(
    *,
    rng: random.Random,
    state: StateDB,
    countries: list[dict[str, Any]],
    topic_id: str,
    template_id: int,
    cd_bucket: int | None,
    similarity_window: int,
    answer_cooldown_days: int,
) -> QuizItem:
    recent = state.recent_questions(limit=similarity_window)

    for _ in range(200):
        item = _generate_candidate(
            rng=rng,
            countries=countries,
            topic_id=topic_id,
            template_id=template_id,
            cd_bucket=cd_bucket,
        )
        if not is_safe_text(item.question_text) or not is_safe_text(item.answer_text):
            continue

        norm = normalize_text(item.question_text)
        qhash = sha256_text(norm)

        if state.exists_question_hash(qhash):
            continue

        if _too_similar(norm, recent):
            continue

        if state.answers_recently_used(item.answer_text, days=answer_cooldown_days) > 0 and rng.random() < 0.9:
            continue

        return QuizItem(
            topic_id=item.topic_id,
            question_text=item.question_text,
            answer_text=item.answer_text,
            options=item.options,
            correct_option_index=item.correct_option_index,
            hint_text=item.hint_text,
            difficulty=item.difficulty,
            countdown_seconds=item.countdown_seconds,
            question_hash=qhash,
        )

    raise RuntimeError("Unable to generate a unique safe question")


def generate_long_questions(
    *,
    rng: random.Random,
    state: StateDB,
    countries: list[dict[str, Any]],
    topics: list[str],
    count: int,
) -> list[QuizItem]:
    out: list[QuizItem] = []
    attempts = 0
    while len(out) < count and attempts < count * 60:
        attempts += 1
        topic_id = rng.choice(topics)
        item = generate_short_question(
            rng=rng,
            state=state,
            countries=countries,
            topic_id=topic_id,
            template_id=1,
            cd_bucket=None,
            similarity_window=400,
            answer_cooldown_days=7,
        )
        out.append(item)
    return out[:count]


@dataclass(frozen=True)
class _Candidate:
    topic_id: str
    question_text: str
    answer_text: str
    options: list[str] | None
    correct_option_index: int | None
    hint_text: str | None
    difficulty: float
    countdown_seconds: int


def _generate_candidate(
    *,
    rng: random.Random,
    countries: list[dict[str, Any]],
    topic_id: str,
    template_id: int,
    cd_bucket: int | None,
) -> _Candidate:
    if topic_id == "capitals":
        return _candidate_capitals(rng, countries, template_id, cd_bucket)
    if topic_id == "continents":
        return _candidate_continents(rng, countries, template_id, cd_bucket)
    if topic_id == "currencies":
        return _candidate_currencies(rng, countries, template_id, cd_bucket)
    if topic_id == "elements":
        return _candidate_elements(rng, template_id, cd_bucket)
    if topic_id == "science":
        return _candidate_science(rng, template_id, cd_bucket)
    if topic_id == "math":
        return _candidate_math(rng, template_id, cd_bucket)
    if topic_id == "truefalse":
        return _candidate_truefalse(rng, countries, template_id, cd_bucket)
    return _candidate_capitals(rng, countries, template_id, cd_bucket)


def _pick_countdown(difficulty: float, cd_bucket: int | None) -> int:
    base = 7 + int(round(clamp(difficulty, 0.0, 1.0) * 5.0))
    if cd_bucket is None:
        return int(clamp(base, 6, 12))
    if cd_bucket <= 1:
        return 7
    if cd_bucket == 2:
        return 9
    if cd_bucket == 3:
        return 11
    return 12


def _candidate_capitals(rng: random.Random, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> _Candidate:
    c = rng.choice(countries)
    country = str(c["country"])
    capital = str(c["capital"])

    direction = rng.choice(["country_to_capital", "capital_to_country"])
    if direction == "country_to_capital":
        q = f"What's the capital of {country}?"
        a = capital
        difficulty = 0.55
        hint = None
        if template_id == 4:
            hint = f"Hint: It starts with '{a[0]}'."
    else:
        q = f"Which country has the capital {capital}?"
        a = country
        difficulty = 0.62
        hint = None
        if template_id == 4:
            hint = f"Hint: It has {len(country)} letters."

    options = None
    correct = None
    if template_id == 2:
        pool = [str(x["capital"]) for x in rng.sample(countries, k=min(40, len(countries)))]
        opts = _pick_unique([a] + pool, 3, rng)
        rng.shuffle(opts)
        correct = opts.index(a)
        options = opts
        difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("capitals", q, a, options, correct, hint, difficulty, countdown)


def _candidate_continents(rng: random.Random, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> _Candidate:
    c = rng.choice(countries)
    country = str(c["country"])
    continent = str(c["continent"])

    q = f"Which continent is {country} in?"
    a = continent
    difficulty = 0.48
    hint = None
    if template_id == 4:
        hint = f"Hint: It has {len(continent)} letters."

    options = None
    correct = None
    if template_id == 2:
        opts = _pick_unique([a] + list({"Africa", "Europe", "Asia", "North America", "South America", "Oceania"}), 3, rng)
        rng.shuffle(opts)
        correct = opts.index(a) if a in opts else 0
        options = opts
        difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("continents", q, a, options, correct, hint, difficulty, countdown)


def _candidate_currencies(rng: random.Random, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> _Candidate:
    cur_to_countries: dict[str, list[str]] = {}
    for c in countries:
        cur = str(c.get("currency_name") or "").strip()
        if not cur:
            continue
        cur_to_countries.setdefault(cur, []).append(str(c["country"]))

    uniques = [cur for cur, cs in cur_to_countries.items() if len(cs) == 1 and len(cur) > 2]
    if not uniques:
        return _candidate_capitals(rng, countries, template_id, cd_bucket)

    currency = rng.choice(uniques)
    country = cur_to_countries[currency][0]

    q = f"Which country uses the currency: {currency}?"
    a = country
    difficulty = 0.68
    hint = None
    if template_id == 4:
        hint = f"Hint: It starts with '{a[0]}'."

    options = None
    correct = None
    if template_id == 2:
        pool = [str(x["country"]) for x in rng.sample(countries, k=min(60, len(countries)))]
        opts = _pick_unique([a] + pool, 3, rng)
        rng.shuffle(opts)
        correct = opts.index(a)
        options = opts
        difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("currencies", q, a, options, correct, hint, difficulty, countdown)


def _candidate_elements(rng: random.Random, template_id: int, cd_bucket: int | None) -> _Candidate:
    name, sym = rng.choice(ELEMENTS)
    direction = rng.choice(["name_to_symbol", "symbol_to_name"])
    if direction == "name_to_symbol":
        q = f"What is the chemical symbol for {name}?"
        a = sym
        difficulty = 0.60
        hint = None
        if template_id == 4:
            hint = f"Hint: It has {len(sym)} letters."
        options = None
        correct = None
        if template_id == 2:
            pool = [s for _, s in rng.sample(ELEMENTS, k=min(25, len(ELEMENTS)))]
            opts = _pick_unique([a] + pool, 3, rng)
            rng.shuffle(opts)
            correct = opts.index(a)
            options = opts
            difficulty += 0.05
    else:
        q = f"Which element has the symbol '{sym}'?"
        a = name
        difficulty = 0.62
        hint = None
        if template_id == 4:
            hint = f"Hint: It starts with '{a[0]}'."
        options = None
        correct = None
        if template_id == 2:
            pool = [n for n, _ in rng.sample(ELEMENTS, k=min(25, len(ELEMENTS)))]
            opts = _pick_unique([a] + pool, 3, rng)
            rng.shuffle(opts)
            correct = opts.index(a)
            options = opts
            difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("elements", q, a, options, correct, hint, difficulty, countdown)


def _candidate_science(rng: random.Random, template_id: int, cd_bucket: int | None) -> _Candidate:
    kind = rng.choice(["fact", "planet_order", "ocean"])
    if kind == "fact":
        q, a = rng.choice(BASIC_FACTS)
        difficulty = 0.55
        hint = None
        if template_id == 4:
            hint = f"Hint: {a[:1]}..."
        options = None
        correct = None
        if template_id == 2:
            pool = [ans for _, ans in rng.sample(BASIC_FACTS, k=min(10, len(BASIC_FACTS)))]
            opts = _pick_unique([a] + pool, 3, rng)
            rng.shuffle(opts)
            correct = opts.index(a)
            options = opts
            difficulty += 0.05
    elif kind == "planet_order":
        idx = rng.randint(1, len(PLANETS_ORDER))
        a = PLANETS_ORDER[idx - 1]
        q = f"Which planet is {idx}{_ordinal_suffix(idx)} from the Sun?"
        difficulty = 0.65
        hint = None
        if template_id == 4:
            hint = "Hint: Think of the solar system order."
        options = None
        correct = None
        if template_id == 2:
            pool = rng.sample(PLANETS_ORDER, k=min(6, len(PLANETS_ORDER)))
            opts = _pick_unique([a] + pool, 3, rng)
            rng.shuffle(opts)
            correct = opts.index(a)
            options = opts
            difficulty += 0.05
    else:
        a = rng.choice(OCEANS)
        q = "Which of these is an океan on Earth?"
        q = "Which of these is an ocean on Earth?"
        difficulty = 0.45
        hint = None
        if template_id == 4:
            hint = "Hint: It's a major body of saltwater."
        options = None
        correct = None
        if template_id == 2:
            pool = ["Sahara", "Amazon", "Himalayas", "Gobi", "Nile"]
            opts = _pick_unique([a] + pool, 3, rng)
            rng.shuffle(opts)
            correct = opts.index(a)
            options = opts
            difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("science", q, a, options, correct, hint, difficulty, countdown)


def _candidate_math(rng: random.Random, template_id: int, cd_bucket: int | None) -> _Candidate:
    a = rng.randint(7, 99)
    b = rng.randint(7, 99)
    op = rng.choice(["+", "-", "×"])
    if op == "+":
        ans = a + b
        q = f"Fast math: {a} + {b} = ?"
    elif op == "-":
        if b > a:
            a, b = b, a
        ans = a - b
        q = f"Fast math: {a} - {b} = ?"
    else:
        a = rng.randint(6, 17)
        b = rng.randint(6, 17)
        ans = a * b
        q = f"Fast math: {a} × {b} = ?"

    difficulty = 0.50
    hint = None
    if template_id == 4:
        hint = "Hint: Do it in your head."
    options = None
    correct = None
    if template_id == 2:
        wrong = [str(ans + rng.randint(-10, 10)) for _ in range(8)]
        opts = _pick_unique([str(ans)] + wrong, 3, rng)
        rng.shuffle(opts)
        correct = opts.index(str(ans))
        options = opts
        difficulty += 0.05

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("math", q, str(ans), options, correct, hint, difficulty, countdown)


def _candidate_truefalse(rng: random.Random, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> _Candidate:
    c = rng.choice(countries)
    country = str(c["country"])
    true_cap = str(c["capital"])

    if rng.random() < 0.5:
        statement = f"True or False: The capital of {country} is {true_cap}."
        answer = "True"
        difficulty = 0.52
    else:
        wrong_cap = str(rng.choice(countries)["capital"])
        statement = f"True or False: The capital of {country} is {wrong_cap}."
        answer = "False"
        difficulty = 0.60

    hint = None
    if template_id == 4:
        hint = f"Hint: Think of {country}."

    options = None
    correct = None
    if template_id == 2:
        options = ["True", "False"]
        correct = 0 if answer == "True" else 1

    countdown = _pick_countdown(difficulty, cd_bucket)
    return _Candidate("truefalse", statement, answer, options, correct, hint, difficulty, countdown)


def _too_similar(norm_question: str, recent: list[str]) -> bool:
    for prev in recent:
        pn = normalize_text(prev)
        if not pn:
            continue
        if fuzz.token_set_ratio(norm_question, pn) >= 92:
            return True
    return False


def _pick_unique(pool: list[str], n: int, rng: random.Random) -> list[str]:
    uniq: list[str] = []
    seen: set[str] = set()
    for _ in range(1000):
        x = str(rng.choice(pool)).strip()
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
        if len(uniq) >= n:
            break

    if len(uniq) < n:
        for x in pool:
            x = str(x).strip()
            if not x:
                continue
            k = x.lower()
            if k in seen:
                continue
            seen.add(k)
            uniq.append(x)
            if len(uniq) >= n:
                break

    return uniq[:n]


def _ordinal_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    if n % 10 == 1:
        return "st"
    if n % 10 == 2:
        return "nd"
    if n % 10 == 3:
        return "rd"
    return "th"

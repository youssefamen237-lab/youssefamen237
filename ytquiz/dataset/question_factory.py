from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ytquiz.utils import clamp, normalize_text, sha256_text


@dataclass
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


# ---------- Public API ----------


def generate_short_question(
    *,
    rng,
    state,
    countries: list[dict[str, Any]],
    topic_id: str,
    template_id: int,
    cd_bucket: int | None,
    similarity_window: int,
    answer_cooldown_days: int,
) -> QuizItem:
    # Try multiple candidates to satisfy anti-duplicate + cooldown
    last_err: Exception | None = None
    for _ in range(80):
        try:
            item = _generate_candidate(rng=rng, countries=countries, topic_id=topic_id, template_id=template_id, cd_bucket=cd_bucket)
            if _is_duplicate(state=state, item=item, similarity_window=similarity_window):
                continue
            if _answer_on_cooldown(state=state, answer=item.answer_text, days=answer_cooldown_days):
                continue
            return item
        except Exception as e:
            last_err = e
            continue

    # Hard fallback (never crash the pipeline)
    item = _fallback_candidate(rng=rng, countries=countries, topic_id=topic_id, template_id=template_id, cd_bucket=cd_bucket)
    if item is None:
        raise RuntimeError(f"Failed to generate question (topic={topic_id}) last_err={last_err}")
    return item


def generate_long_questions(*, rng, state, countries: list[dict[str, Any]], topics: list[str], count: int) -> list[QuizItem]:
    out: list[QuizItem] = []
    tries = 0
    while len(out) < count and tries < count * 15:
        tries += 1
        topic_id = rng.choice(topics) if topics else "capitals"
        template_id = 1
        item = generate_short_question(
            rng=rng,
            state=state,
            countries=countries,
            topic_id=topic_id,
            template_id=template_id,
            cd_bucket=None,
            similarity_window=120,
            answer_cooldown_days=2,
        )
        out.append(item)
    return out[:count]


# ---------- Candidate generation ----------


def _generate_candidate(*, rng, countries: list[dict[str, Any]], topic_id: str, template_id: int, cd_bucket: int | None) -> QuizItem:
    topic_id = (topic_id or "capitals").strip().lower()

    if template_id == 3:
        return _candidate_truefalse(rng=rng, cd_bucket=cd_bucket)

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
        return _candidate_truefalse(rng=rng, cd_bucket=cd_bucket)

    return _candidate_capitals(rng, countries, template_id, cd_bucket)


def _candidate_capitals(rng, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> QuizItem:
    c = _pick_country_with(countries, rng, need=("name", "capital"))
    country = _c_name(c)
    cap = _c_capital(c)

    q = f"Which country has the capital {cap}?"
    a = country

    options, correct = _maybe_make_country_options(rng, countries, correct_country=a, template_id=template_id)
    hint = _hint_country(a)

    difficulty = 0.55
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)

    return _item(topic="capitals", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_continents(rng, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> QuizItem:
    c = _pick_country_with(countries, rng, need=("name", "continent"))
    country = _c_name(c)
    cont = _c_continent(c)

    q = f"Which continent is {country} in?"
    a = cont

    options, correct = _maybe_make_simple_options(
        rng=rng,
        template_id=template_id,
        correct_value=a,
        pool=["Africa", "Europe", "Asia", "North America", "South America", "Oceania"],
        n=3,
    )
    hint = None
    difficulty = 0.45
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)

    return _item(topic="continents", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_currencies(rng, countries: list[dict[str, Any]], template_id: int, cd_bucket: int | None) -> QuizItem:
    # Fix: ensure correct answer is ALWAYS included in the options list (no ValueError).
    c = _pick_country_with(countries, rng, need=("name", "currency"))
    country = _c_name(c)
    currency = _c_currency(c)

    q = f"Which country uses the currency {currency}?"
    a = country

    options, correct = _maybe_make_country_options(rng, countries, correct_country=a, template_id=template_id)
    hint = _hint_country(a)

    difficulty = 0.58
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)

    return _item(topic="currencies", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_elements(rng, template_id: int, cd_bucket: int | None) -> QuizItem:
    # Small safe bank (no hallucinations)
    bank = [
        ("Hydrogen", "H"),
        ("Helium", "He"),
        ("Carbon", "C"),
        ("Nitrogen", "N"),
        ("Oxygen", "O"),
        ("Sodium", "Na"),
        ("Potassium", "K"),
        ("Iron", "Fe"),
        ("Copper", "Cu"),
        ("Silver", "Ag"),
        ("Gold", "Au"),
    ]
    name, sym = rng.choice(bank)

    q = f"What is the chemical symbol for {name}?"
    a = sym

    options, correct = _maybe_make_simple_options(
        rng=rng,
        template_id=template_id,
        correct_value=a,
        pool=[s for _, s in bank],
        n=3,
    )
    hint = f"Hint: {len(a)} letters" if template_id != 2 else None

    difficulty = 0.60
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)
    return _item(topic="elements", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_science(rng, template_id: int, cd_bucket: int | None) -> QuizItem:
    bank = [
        ("Which planet is known as the Red Planet?", "Mars"),
        ("What gas do plants absorb from the air?", "Carbon dioxide"),
        ("What is the largest planet in our solar system?", "Jupiter"),
        ("What part of the cell contains DNA?", "Nucleus"),
        ("What force keeps us on the ground?", "Gravity"),
        ("What is H2O commonly called?", "Water"),
    ]
    q, a = rng.choice(bank)

    options, correct = _maybe_make_simple_options(
        rng=rng,
        template_id=template_id,
        correct_value=a,
        pool=[x[1] for x in bank],
        n=3,
    )
    hint = None
    difficulty = 0.55
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)
    return _item(topic="science", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_math(rng, template_id: int, cd_bucket: int | None) -> QuizItem:
    # Safe mental math (keeps answers deterministic)
    a = rng.randint(6, 48)
    b = rng.randint(6, 48)
    op = rng.choice(["+", "-", "×"])
    if op == "+":
        res = a + b
        q = f"Mental Math: {a} + {b} = ?"
    elif op == "-":
        if b > a:
            a, b = b, a
        res = a - b
        q = f"Mental Math: {a} - {b} = ?"
    else:
        a = rng.randint(3, 15)
        b = rng.randint(3, 15)
        res = a * b
        q = f"Mental Math: {a} × {b} = ?"

    ans = str(res)

    # For MC template, create nearby plausible distractors
    pool = {str(res), str(res + rng.randint(1, 6)), str(max(0, res - rng.randint(1, 6))), str(res + rng.randint(7, 14))}
    pool_list = list(pool)

    options, correct = _maybe_make_simple_options(
        rng=rng,
        template_id=template_id,
        correct_value=ans,
        pool=pool_list,
        n=3,
    )

    hint = None
    difficulty = 0.62
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)
    return _item(topic="math", q=q, a=ans, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _candidate_truefalse(*, rng, cd_bucket: int | None) -> QuizItem:
    # Template 3 uses True/False always
    facts = [
        ("Lightning is hotter than the surface of the Sun.", True),
        ("Humans have three lungs.", False),
        ("Octopuses have three hearts.", True),
        ("The Great Wall of China is visible from the Moon.", False),
        ("Bats are blind.", False),
        ("Water boils at 100°C at sea level.", True),
    ]
    statement, is_true = rng.choice(facts)
    q = f"True or False: {statement}"
    a = "True" if is_true else "False"
    options = ["True", "False"]
    correct = 0 if is_true else 1
    hint = None
    difficulty = 0.40
    cd = _countdown_for(difficulty=difficulty, cd_bucket=cd_bucket)
    return _item(topic="truefalse", q=q, a=a, options=options, correct=correct, hint=hint, difficulty=difficulty, cd=cd)


def _fallback_candidate(*, rng, countries: list[dict[str, Any]], topic_id: str, template_id: int, cd_bucket: int | None) -> QuizItem | None:
    try:
        return _candidate_capitals(rng, countries, template_id, cd_bucket)
    except Exception:
        return None


# ---------- Helpers ----------


def _item(*, topic: str, q: str, a: str, options: list[str] | None, correct: int | None, hint: str | None, difficulty: float, cd: int) -> QuizItem:
    qn = normalize_text(q)
    an = normalize_text(a)
    qhash = sha256_text(qn + "|" + an)

    # If MC options exist, ensure correct index is valid
    if options is not None:
        if a not in options:
            # Force include answer (never crash)
            options = list(dict.fromkeys([a] + options))[:3]
        if a in options:
            correct = options.index(a)
        else:
            correct = 0

    return QuizItem(
        topic_id=topic,
        question_text=q,
        answer_text=a,
        options=options,
        correct_option_index=correct,
        hint_text=hint,
        difficulty=float(clamp(float(difficulty), 0.0, 1.0)),
        countdown_seconds=int(cd),
        question_hash=qhash,
    )


def _countdown_for(*, difficulty: float, cd_bucket: int | None) -> int:
    # buckets: 1 fast, 2 normal, 3 slow
    if cd_bucket == 1:
        return int(6 + round(2 * difficulty))  # 6..8
    if cd_bucket == 2:
        return int(8 + round(3 * difficulty))  # 8..11
    if cd_bucket == 3:
        return int(10 + round(5 * difficulty))  # 10..15
    # default by difficulty
    return int(clamp(8 + round(6 * difficulty), 6, 16))


def _maybe_make_country_options(rng, countries: list[dict[str, Any]], correct_country: str, template_id: int) -> tuple[list[str] | None, int | None]:
    if int(template_id) != 2:
        return None, None

    correct_country = str(correct_country)
    pool = []
    for c in countries:
        name = _c_name(c)
        if not name:
            continue
        if name == correct_country:
            continue
        pool.append(name)

    rng.shuffle(pool)
    wrongs: list[str] = []
    seen = set()
    for x in pool:
        if x in seen:
            continue
        if x == correct_country:
            continue
        wrongs.append(x)
        seen.add(x)
        if len(wrongs) >= 2:
            break

    # Always include correct
    opts = [correct_country] + wrongs
    # If pool small, pad with safe fillers (won't crash)
    while len(opts) < 3:
        opts.append(f"Option {len(opts)+1}")
    rng.shuffle(opts)
    return opts, opts.index(correct_country)


def _maybe_make_simple_options(*, rng, template_id: int, correct_value: str, pool: list[str], n: int) -> tuple[list[str] | None, int | None]:
    if int(template_id) != 2:
        return None, None

    correct_value = str(correct_value)
    uniq_pool = []
    seen = set()
    for x in pool:
        x = str(x)
        if not x or x in seen:
            continue
        seen.add(x)
        uniq_pool.append(x)

    wrongs = [x for x in uniq_pool if x != correct_value]
    rng.shuffle(wrongs)
    opts = [correct_value] + wrongs[: max(0, n - 1)]
    while len(opts) < n:
        opts.append(f"Option {len(opts)+1}")
    rng.shuffle(opts)
    return opts, opts.index(correct_value)


def _hint_country(country: str) -> str:
    c = str(country).strip()
    if not c:
        return None  # type: ignore[return-value]
    first = c[0].upper()
    last = c[-1].upper()
    return f"Hint: starts with {first}, ends with {last}"


def _pick_country_with(countries: list[dict[str, Any]], rng, need: tuple[str, ...]) -> dict[str, Any]:
    if not countries:
        raise ValueError("countries dataset is empty")

    candidates = []
    for c in countries:
        if not isinstance(c, dict):
            continue
        ok = True
        for k in need:
            if k == "name" and not _c_name(c):
                ok = False
                break
            if k == "capital" and not _c_capital(c):
                ok = False
                break
            if k == "currency" and not _c_currency(c):
                ok = False
                break
            if k == "continent" and not _c_continent(c):
                ok = False
                break
        if ok:
            candidates.append(c)

    if not candidates:
        # fallback to any country that at least has a name
        candidates = [c for c in countries if isinstance(c, dict) and _c_name(c)]
        if not candidates:
            raise ValueError("No usable country entries found")

    return rng.choice(candidates)


def _c_name(c: dict[str, Any]) -> str:
    v = c.get("name") or c.get("country") or c.get("Country") or c.get("country_name") or c.get("CountryName")
    return str(v).strip() if v else ""


def _c_capital(c: dict[str, Any]) -> str:
    v = c.get("capital") or c.get("Capital") or c.get("capital_name") or c.get("CapitalName")
    return str(v).strip() if v else ""


def _c_currency(c: dict[str, Any]) -> str:
    v = c.get("currency") or c.get("Currency") or c.get("currency_name") or c.get("CurrencyName")
    return str(v).strip() if v else ""


def _c_continent(c: dict[str, Any]) -> str:
    v = c.get("continent") or c.get("Continent") or c.get("region") or c.get("Region")
    return str(v).strip() if v else ""


# ---------- Duplicate / cooldown checks (duck-typed to your existing StateDB) ----------


def _is_duplicate(*, state, item: QuizItem, similarity_window: int) -> bool:
    # 1) exact hash check (try known method names)
    if _state_call_bool(state, ["has_question_hash", "question_hash_exists", "is_question_hash_used", "seen_question_hash"], item.question_hash):
        return True

    # 2) similarity check if StateDB supports it
    for name in ["is_similar_question", "similar_question_exists"]:
        fn = getattr(state, name, None)
        if callable(fn):
            try:
                return bool(fn(item.question_text, int(similarity_window)))
            except Exception:
                pass

    # 3) local lightweight check if StateDB can return recent questions
    for name in ["recent_questions_text", "list_recent_questions_text"]:
        fn = getattr(state, name, None)
        if callable(fn):
            try:
                rec = fn(int(similarity_window))
                if isinstance(rec, list):
                    qn = normalize_text(item.question_text)
                    for t in rec[: int(similarity_window)]:
                        if not t:
                            continue
                        s = SequenceMatcher(None, qn, normalize_text(str(t))).ratio()
                        if s >= 0.90:
                            return True
            except Exception:
                pass

    return False


def _answer_on_cooldown(*, state, answer: str, days: int) -> bool:
    if not answer or not days or days <= 0:
        return False

    # Try known method names
    for name in ["is_answer_on_cooldown", "answer_on_cooldown", "is_answer_recent"]:
        fn = getattr(state, name, None)
        if callable(fn):
            try:
                return bool(fn(str(answer), int(days)))
            except Exception:
                pass

    return False


def _state_call_bool(state, names: list[str], *args) -> bool:
    for name in names:
        fn = getattr(state, name, None)
        if callable(fn):
            try:
                return bool(fn(*args))
            except Exception:
                continue
    return False

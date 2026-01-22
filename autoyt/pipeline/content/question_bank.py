\
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import random

from autoyt.pipeline.content.country_data import Country, CountryDataset
from autoyt.utils.text import normalize_key


@dataclass
class QuestionItem:
    template_id: str
    topic: str
    dupe_key: str
    question_text: str
    answer_text: str
    options: Optional[List[str]] = None
    hook: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


def _pick_distinct(rng: random.Random, items: Sequence[Country], k: int, exclude: Optional[Country] = None) -> List[Country]:
    pool = [c for c in items if (exclude is None or c.cca2 != exclude.cca2)]
    if len(pool) <= k:
        rng.shuffle(pool)
        return list(pool[:k])
    return rng.sample(pool, k)


def _capital_group_key(country: Country) -> str:
    return normalize_key(f"capital::{country.cca2}")


def _flag_group_key(country: Country) -> str:
    return normalize_key(f"flag::{country.cca2}")


def _continent_key(continent: str, country: Country) -> str:
    return normalize_key(f"continent::{continent}::{country.cca2}")


def _wyr_key(a: Country, b: Country) -> str:
    a2, b2 = sorted([a.cca2, b.cca2])
    return normalize_key(f"wyr::{a2}::{b2}")


def generate_tf_capital(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = ds.countries
    for _ in range(200):
        c = rng.choice(countries)
        dupe_key = _capital_group_key(c)
        if dupe_key in recent_dupes:
            continue

        is_true = rng.random() < 0.5
        if is_true:
            stmt_capital = c.capital
            answer = "✅ TRUE"
            answer_short = "TRUE ✅"
        else:
            wrong_from = rng.choice([x for x in countries if x.cca2 != c.cca2])
            stmt_capital = wrong_from.capital
            # show correct answer (short + clear)
            answer = f"❌ FALSE\n{c.capital}"
            answer_short = f"{c.capital}"

        phr = rng.choice(
            [
                "True or False:\nThe capital of {country} is {capital}.",
                "True/False:\n{country}'s capital is {capital}.",
                "TRUE or FALSE?\n{country} → {capital}",
            ]
        )
        q = phr.format(country=c.name, capital=stmt_capital)

        return QuestionItem(
            template_id="tf_capital",
            topic="capitals",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=answer if not is_true else answer_short,
            options=None,
            hook=f"{c.name} capital",
            meta={"country": c.name, "cca2": c.cca2, "truth": is_true, "shown_capital": stmt_capital, "correct_capital": c.capital},
        )

    # If all else fails, no-dupe fallback (should be rare)
    c = rng.choice(countries)
    return QuestionItem(
        template_id="tf_capital",
        topic="capitals",
        dupe_key=_capital_group_key(c) + "::fallback",
        question_text=f"True or False:\nThe capital of {c.name} is {c.capital}.",
        answer_text="TRUE ✅",
        meta={"fallback": True},
    )


def generate_mc_capital(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = ds.countries
    for _ in range(200):
        c = rng.choice(countries)
        dupe_key = _capital_group_key(c)
        if dupe_key in recent_dupes:
            continue

        distractors = _pick_distinct(rng, countries, k=2, exclude=c)
        options = [c.capital, distractors[0].capital, distractors[1].capital]
        rng.shuffle(options)
        correct = c.capital
        # Add labels A/B/C in render stage, keep options raw
        phr = rng.choice(
            [
                "Pick the correct answer:\nWhat is the capital of {country}?",
                "Choose A/B/C:\n{country} — capital city?",
                "Quick quiz:\nCapital of {country}?",
            ]
        )
        q = phr.format(country=c.name)
        return QuestionItem(
            template_id="mc_capital",
            topic="capitals",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=correct,
            options=options,
            hook=f"Capital of {c.name}",
            meta={"country": c.name, "cca2": c.cca2, "correct": correct, "options": options},
        )

    c = rng.choice(countries)
    return QuestionItem(
        template_id="mc_capital",
        topic="capitals",
        dupe_key=_capital_group_key(c) + "::fallback",
        question_text=f"Pick the correct answer:\nWhat is the capital of {c.name}?",
        answer_text=c.capital,
        options=[c.capital],
        meta={"fallback": True},
    )


def generate_direct_capital(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = ds.countries
    for _ in range(200):
        c = rng.choice(countries)
        dupe_key = _capital_group_key(c)
        if dupe_key in recent_dupes:
            continue

        phr = rng.choice(
            [
                "What is the capital of {country}?",
                "Name the capital city of {country}.",
                "{country} → capital city?",
            ]
        )
        q = phr.format(country=c.name)
        return QuestionItem(
            template_id="direct_capital",
            topic="capitals",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=c.capital,
            options=None,
            hook=f"{c.name} capital",
            meta={"country": c.name, "cca2": c.cca2, "capital": c.capital},
        )

    c = rng.choice(countries)
    return QuestionItem(
        template_id="direct_capital",
        topic="capitals",
        dupe_key=_capital_group_key(c) + "::fallback",
        question_text=f"What is the capital of {c.name}?",
        answer_text=c.capital,
        meta={"fallback": True},
    )


def generate_flag_emoji(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = [c for c in ds.countries if c.flag_emoji]
    for _ in range(200):
        c = rng.choice(countries)
        dupe_key = _flag_group_key(c)
        if dupe_key in recent_dupes:
            continue

        phr = rng.choice(
            [
                "Guess the country:\n{flag}",
                "Which country is this? {flag}",
                "Name this flag: {flag}",
            ]
        )
        q = phr.format(flag=c.flag_emoji)
        return QuestionItem(
            template_id="flag_emoji",
            topic="flags",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=c.name,
            hook=f"Guess the country {c.flag_emoji}",
            meta={"country": c.name, "cca2": c.cca2, "flag": c.flag_emoji},
        )

    c = rng.choice(countries)
    return QuestionItem(
        template_id="flag_emoji",
        topic="flags",
        dupe_key=_flag_group_key(c) + "::fallback",
        question_text=f"Guess the country:\n{c.flag_emoji}",
        answer_text=c.name,
        meta={"fallback": True},
    )


def generate_which_continent(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    continents = ["Europe", "Asia", "Africa", "Americas", "Oceania"]
    countries = ds.countries
    for _ in range(250):
        continent = rng.choice(continents)
        correct_pool = [c for c in countries if c.region == continent]
        wrong_pool = [c for c in countries if c.region != continent]
        if len(correct_pool) < 3 or len(wrong_pool) < 10:
            continue

        correct = rng.choice(correct_pool)
        dupe_key = _continent_key(continent, correct)
        if dupe_key in recent_dupes:
            continue

        distractors = _pick_distinct(rng, wrong_pool, k=2)
        options = [correct.name, distractors[0].name, distractors[1].name]
        rng.shuffle(options)

        phr = rng.choice(
            [
                "Which one is in {continent}?",
                "Pick the country in {continent}:",
                "{continent} quiz — which country belongs?",
            ]
        )
        q = phr.format(continent=continent)
        return QuestionItem(
            template_id="which_continent",
            topic="continents",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=correct.name,
            options=options,
            hook=f"{continent} quiz",
            meta={"continent": continent, "correct": correct.name, "options": options},
        )

    # fallback
    c = rng.choice(countries)
    return QuestionItem(
        template_id="which_continent",
        topic="continents",
        dupe_key=normalize_key(f"continent_fallback::{c.cca2}"),
        question_text="Which continent is this country in?\n" + c.name,
        answer_text=c.region,
        meta={"fallback": True},
    )


def generate_fill_blank(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = ds.countries
    for _ in range(200):
        c = rng.choice(countries)
        dupe_key = _capital_group_key(c)
        if dupe_key in recent_dupes:
            continue

        phr = rng.choice(
            [
                "Fill in the blank:\nThe capital of {country} is ____.",
                "Complete it:\n{country}'s capital is ____.",
                "Blank it:\n{country} → ____ (capital city)",
            ]
        )
        q = phr.format(country=c.name)
        return QuestionItem(
            template_id="fill_blank",
            topic="capitals",
            dupe_key=dupe_key,
            question_text=q,
            answer_text=c.capital,
            hook=f"{c.name} capital",
            meta={"country": c.name, "cca2": c.cca2, "capital": c.capital},
        )

    c = rng.choice(countries)
    return QuestionItem(
        template_id="fill_blank",
        topic="capitals",
        dupe_key=_capital_group_key(c) + "::fallback",
        question_text=f"Fill in the blank:\nThe capital of {c.name} is ____.",
        answer_text=c.capital,
        meta={"fallback": True},
    )


def generate_would_you_rather(ds: CountryDataset, recent_dupes: set[str], rng: random.Random) -> QuestionItem:
    countries = ds.countries
    for _ in range(300):
        a, b = _pick_distinct(rng, countries, k=2)
        dupe_key = _wyr_key(a, b)
        if dupe_key in recent_dupes:
            continue

        phr = rng.choice(
            [
                "Would you rather visit:\nA) {a}\nB) {b}",
                "Pick one:\nA) {a}\nB) {b}",
                "Travel choice:\nA) {a}\nB) {b}",
            ]
        )
        q = phr.format(a=a.name, b=b.name)
        return QuestionItem(
            template_id="would_you_rather",
            topic="geography",
            dupe_key=dupe_key,
            question_text=q,
            answer_text="(Discussion)",
            options=[a.name, b.name],
            hook=f"{a.name} vs {b.name}",
            meta={"a": a.name, "b": b.name, "cca2_a": a.cca2, "cca2_b": b.cca2},
        )

    a, b = _pick_distinct(rng, countries, k=2)
    return QuestionItem(
        template_id="would_you_rather",
        topic="geography",
        dupe_key=_wyr_key(a, b) + "::fallback",
        question_text=f"Would you rather visit:\nA) {a.name}\nB) {b.name}",
        answer_text="(Discussion)",
        options=[a.name, b.name],
        meta={"fallback": True},
    )


GENERATOR_BY_TEMPLATE = {
    "tf_capital": generate_tf_capital,
    "mc_capital": generate_mc_capital,
    "direct_capital": generate_direct_capital,
    "flag_emoji": generate_flag_emoji,
    "which_continent": generate_which_continent,
    "fill_blank": generate_fill_blank,
    "would_you_rather": generate_would_you_rather,
}

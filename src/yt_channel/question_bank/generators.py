from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class QuestionItem:
    question_id: str
    topic: str
    template_id: str
    question_text: str
    answer_text: str
    choices: Optional[List[str]] = None
    fun_fact: Optional[str] = None
    difficulty: int = 1


class QuestionGenerator:
    def __init__(
        self,
        rng: random.Random,
        datasets: Dict[str, List[Dict[str, str]]],
    ) -> None:
        self.rng = rng
        self.datasets = datasets

    def _pick(self, rows: List[Dict[str, str]]) -> Dict[str, str]:
        if not rows:
            return {}
        return self.rng.choice(rows)

    def make_capital_question(self, template_id: str) -> QuestionItem:
        rows = self.datasets.get("countries_capitals", [])
        row = self._pick(rows)
        country = row.get("country", "")
        capital = row.get("capital", "")
        region = row.get("region", "")
        qid = row.get("id", f"capital-{country}-{capital}")
        question = f"What's the capital of {country}?"
        answer = capital
        fun = f"{country} is in {region}." if region else None
        return QuestionItem(
            question_id=qid,
            topic="capital",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=fun,
            difficulty=2 if len(country) > 10 else 1,
        )

    def make_flag_question(self, template_id: str) -> QuestionItem:
        rows = self.datasets.get("countries_capitals", [])
        row = self._pick(rows)
        country = row.get("country", "")
        flag = row.get("flag_emoji", "")
        region = row.get("region", "")
        qid = row.get("id", f"flag-{country}")
        question = f"Which country does this flag belong to? {flag}"
        answer = country
        fun = f"It's in {region}." if region else None
        return QuestionItem(
            question_id=qid,
            topic="flag",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=fun,
            difficulty=2,
        )

    def make_currency_question(self, template_id: str) -> QuestionItem:
        rows = self.datasets.get("countries_currencies", [])
        row = self._pick(rows)
        country = row.get("country", "")
        code = row.get("currency_code", "")
        flag = row.get("flag_emoji", "")
        qid = row.get("id", f"currency-{country}-{code}")
        question = f"What's the currency code for {country}? {flag}"
        answer = code
        fun = None
        return QuestionItem(
            question_id=qid,
            topic="currency",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=fun,
            difficulty=2,
        )

    def make_planet_order_question(self, template_id: str) -> QuestionItem:
        rows = self.datasets.get("planets", [])
        row = self._pick(rows)
        planet = row.get("planet", "")
        order = row.get("order_from_sun", "")
        fact = row.get("fact", "")
        qid = row.get("id", f"planet-{order}-{planet}")
        question = f"Which planet is #{order} from the Sun?"
        answer = planet
        fun = fact or None
        return QuestionItem(
            question_id=qid,
            topic="planets",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=fun,
            difficulty=1,
        )

    def make_math_question(self, template_id: str) -> QuestionItem:
        # Deterministic, non-LLM, safe. Generates quick arithmetic.
        ops = [
            ("+", lambda a, b: a + b),
            ("-", lambda a, b: a - b),
            ("×", lambda a, b: a * b),
        ]
        op_symbol, fn = self.rng.choice(ops)
        a = self.rng.randint(7, 99)
        b = self.rng.randint(3, 99)
        if op_symbol == "-" and b > a:
            a, b = b, a
        ans = fn(a, b)
        qid = f"math-{a}{op_symbol}{b}={ans}"
        question = f"Quick math: {a} {op_symbol} {b} = ?"
        answer = str(ans)
        return QuestionItem(
            question_id=qid,
            topic="math",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=None,
            difficulty=1,
        )

    def make_true_false_question(self, template_id: str) -> QuestionItem:
        # Derived from the capitals dataset (data-driven).
        rows = self.datasets.get("countries_capitals", [])
        row = self._pick(rows)
        country = row.get("country", "")
        true_capital = row.get("capital", "")
        is_true = self.rng.random() < 0.5
        shown_capital = true_capital

        if not is_true and len(rows) > 2:
            # Pick a wrong capital from a different country.
            other = self._pick([r for r in rows if r.get("country") != country])
            shown_capital = other.get("capital", "") or shown_capital

        question = f"True or False: {shown_capital} is the capital of {country}."
        if is_true:
            answer = "TRUE"
        else:
            # Keep the correction short.
            answer = f"FALSE: {true_capital}"

        qid = row.get("id", f"tf-{country}-{shown_capital}")
        return QuestionItem(
            question_id=qid,
            topic="true_false",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=None,
            difficulty=2,
        )

    def make_mcq_question(self, template_id: str) -> QuestionItem:
        # Multiple choice from capitals dataset.
        rows = self.datasets.get("countries_capitals", [])
        row = self._pick(rows)
        country = row.get("country", "")
        correct = row.get("capital", "")

        # Build distractors from other capitals.
        distractor_pool = [r.get("capital", "") for r in rows if r.get("country") != country]
        distractor_pool = [d for d in distractor_pool if d and d != correct]
        self.rng.shuffle(distractor_pool)
        distractors = distractor_pool[:2]
        choices = [correct] + distractors
        while len(choices) < 3:
            choices.append(correct)
        self.rng.shuffle(choices)

        letters = ["A", "B", "C"]
        labeled = [f"{letters[i]}) {choices[i]}" for i in range(3)]
        correct_letter = letters[choices.index(correct)]

        question = f"What's the capital of {country}?"
        answer = f"{correct_letter}) {correct}"
        qid = row.get("id", f"mcq-{country}-{correct}")

        return QuestionItem(
            question_id=qid,
            topic="mcq_capitals",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            choices=labeled,
            fun_fact=None,
            difficulty=2,
        )

    def make_two_step_question(self, template_id: str) -> QuestionItem:
        rows = self.datasets.get("countries_capitals", [])
        row = self._pick(rows)
        country = row.get("country", "")
        capital = row.get("capital", "")
        region = row.get("region", "")

        question = f"What's the capital of {country}?\nBonus: Which region is it in?"
        answer_region = region or ""
        answer = f"{capital} | {answer_region}" if answer_region else capital

        qid = row.get("id", f"two-{country}-{capital}")
        return QuestionItem(
            question_id=qid,
            topic="two_step",
            template_id=template_id,
            question_text=question,
            answer_text=answer,
            fun_fact=None,
            difficulty=2,
        )

    def generate(self, template_id: str) -> QuestionItem:
        # Map templates to question types, mixing topics.
        if template_id == "classic":
            # Mix multiple topics for diversity.
            pick = self.rng.random()
            if pick < 0.4:
                return self.make_capital_question(template_id)
            if pick < 0.65:
                return self.make_flag_question(template_id)
            if pick < 0.85:
                return self.make_currency_question(template_id)
            if pick < 0.95:
                return self.make_planet_order_question(template_id)
            return self.make_math_question(template_id)
        if template_id == "mcq":
            return self.make_mcq_question(template_id)
        if template_id == "true_false":
            return self.make_true_false_question(template_id)
        if template_id == "two_step":
            return self.make_two_step_question(template_id)
        if template_id == "zoom_reveal":
            # Same as classic but different visual.
            return self.make_capital_question(template_id)
        # Fallback
        return self.make_capital_question(template_id)

from __future__ import annotations

import random
from typing import List, Tuple

from .question_bank import QA
from .utils.text_utils import sanitize_text


SHORT_TEMPLATES = [
    "classic_countdown",
    "multiple_choice",
    "true_false",
    "two_step",
    "zoom_reveal",
]


def choose_template(template_pool: List[str] | None = None) -> str:
    pool = template_pool or SHORT_TEMPLATES
    return random.choice(pool)


def build_mcq_from_qa(qa: QA) -> QA:
    if qa.choices and qa.correct_index is not None and len(qa.choices) >= 3:
        return qa
    # fallback: treat as classic
    qa.choices = None
    qa.correct_index = None
    return qa


def format_question_lines(template_id: str, qa: QA) -> Tuple[str, str]:
    """Return (question_text, answer_text) for rendering."""
    q = sanitize_text(qa.question)
    a = sanitize_text(qa.answer)

    if template_id == "multiple_choice" and qa.choices and qa.correct_index is not None:
        letters = ["A", "B", "C", "D"]
        opts = qa.choices[:3]
        opt_lines = [f"{letters[i]}) {opts[i]}" for i in range(len(opts))]
        q = q + "\n\n" + "\n".join(opt_lines)
        correct_letter = letters[qa.correct_index]
        a = f"Answer: {correct_letter}) {opts[qa.correct_index]}"
        return q, a

    if template_id == "true_false":
        # ensure the question starts as True/False prompt
        if not q.lower().startswith("true") and not q.lower().startswith("false"):
            q = "True or False: " + q
        a = a.title()
        return q, a

    if template_id == "two_step":
        # add a tiny bonus prompt that does not introduce new facts
        q = q + "\n\nBonus: Can you answer before the timer ends?"
        return q, a

    # classic_countdown or zoom_reveal
    return q, a

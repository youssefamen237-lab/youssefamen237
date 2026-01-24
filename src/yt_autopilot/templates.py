\
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class TemplateSpec:
    id: str
    requires_llm: bool
    supports_options: bool


TEMPLATES: Dict[str, TemplateSpec] = {
    "mcq": TemplateSpec(id="mcq", requires_llm=True, supports_options=True),
    "true_false": TemplateSpec(id="true_false", requires_llm=True, supports_options=True),
    "fill_blank": TemplateSpec(id="fill_blank", requires_llm=True, supports_options=False),
    "emoji_word": TemplateSpec(id="emoji_word", requires_llm=True, supports_options=False),
    "quick_math": TemplateSpec(id="quick_math", requires_llm=False, supports_options=False),
    "odd_one_out": TemplateSpec(id="odd_one_out", requires_llm=True, supports_options=True),
    "left_right_diff": TemplateSpec(id="left_right_diff", requires_llm=False, supports_options=True),
    "sports_prediction": TemplateSpec(id="sports_prediction", requires_llm=False, supports_options=False),
}


CAPITALS = [
    ("France", "Paris"),
    ("Italy", "Rome"),
    ("Spain", "Madrid"),
    ("Portugal", "Lisbon"),
    ("Germany", "Berlin"),
    ("Netherlands", "Amsterdam"),
    ("Belgium", "Brussels"),
    ("Switzerland", "Bern"),
    ("Austria", "Vienna"),
    ("Greece", "Athens"),
    ("Turkey", "Ankara"),
    ("Egypt", "Cairo"),
    ("Morocco", "Rabat"),
    ("Japan", "Tokyo"),
    ("China", "Beijing"),
    ("South Korea", "Seoul"),
    ("Canada", "Ottawa"),
    ("United States", "Washington, D.C."),
    ("Brazil", "Brasília"),
    ("Argentina", "Buenos Aires"),
    ("Mexico", "Mexico City"),
    ("Australia", "Canberra"),
    ("New Zealand", "Wellington"),
    ("South Africa", "Pretoria"),
    ("Nigeria", "Abuja"),
    ("Kenya", "Nairobi"),
    ("India", "New Delhi"),
    ("Pakistan", "Islamabad"),
    ("Indonesia", "Jakarta"),
    ("Thailand", "Bangkok"),
]


EMOJI_WORDS = [
    ("🌧️☔", "rain"),
    ("🔥🌶️", "spicy"),
    ("🌙⭐", "night"),
    ("🍎📚", "school"),
    ("🐶🏠", "doghouse"),
    ("🧊🥤", "cold drink"),
    ("🏖️🌊", "beach"),
    ("🎵🎧", "music"),
    ("🚗💨", "fast car"),
    ("📷✨", "photo"),
    ("🧠⚡", "idea"),
]


BIG_TEAMS = [
    "Real Madrid",
    "Barcelona",
    "Manchester United",
    "Manchester City",
    "Liverpool",
    "Arsenal",
    "Chelsea",
    "Bayern Munich",
    "Borussia Dortmund",
    "Paris Saint-Germain",
    "Juventus",
    "AC Milan",
    "Inter Milan",
    "Atletico Madrid",
]


def local_quick_math() -> Tuple[str, str, str]:
    a = random.randint(7, 29)
    b = random.randint(7, 29)
    op = random.choice(["+", "-", "×"])
    if op == "+":
        ans = a + b
        q = f"{a} + {b} = ?"
    elif op == "-":
        ans = a - b
        q = f"{a} - {b} = ?"
    else:
        a = random.randint(3, 12)
        b = random.randint(3, 12)
        ans = a * b
        q = f"{a} × {b} = ?"
    return q, str(ans), "math"


def local_left_right_diff() -> Tuple[str, str, List[str], str]:
    side = random.choice(["LEFT", "RIGHT"])
    q = "Which side is different? LEFT or RIGHT"
    ans = side
    opts = ["LEFT", "RIGHT"]
    return q, ans, opts, "spot the difference"


def local_sports_prediction() -> Tuple[str, str, str]:
    a, b = random.sample(BIG_TEAMS, 2)
    q = f"Predict the score: {a} vs {b}"
    ans = "COMMENT YOUR PREDICTION"
    return q, ans, "sports"


def local_emoji_word() -> Tuple[str, str, str]:
    emojis, word = random.choice(EMOJI_WORDS)
    q = f"Guess the word: {emojis}"
    ans = word
    return q, ans, "emoji"


def llm_prompt_for_template(template_id: str) -> str:
    base_rules = [
        "Output ONLY valid JSON. No markdown, no extra text.",
        "Language: English.",
        "Keep the question short and punchy (max 90 characters if possible).",
        "No politics, no religion, no adult/sexual content, no violence, no drugs, no medical advice, no hate.",
        "Avoid copyrighted/trademarked names (movie titles, brand names, celebrity names).",
        "Make it suitable for a general audience (all ages).",
    ]
    schema_common = {
        "template": template_id,
        "category": "one or two words",
        "difficulty": "easy|medium|hard",
        "question": "string",
        "answer": "string"
    }

    if template_id == "mcq":
        schema = dict(schema_common)
        schema["options"] = ["A", "B", "C", "D"]
        extra = [
            "Generate exactly 4 options. Exactly 1 option must be correct (equals 'answer').",
            "Options should be short (1-4 words).",
        ]
    elif template_id == "true_false":
        schema = dict(schema_common)
        schema["options"] = ["True", "False"]
        extra = [
            "The answer must be either 'True' or 'False'.",
            "Make the statement clearly true or clearly false.",
        ]
    elif template_id == "fill_blank":
        schema = dict(schema_common)
        extra = [
            "The question must contain exactly ONE blank like: ____",
            "The answer should be a single word or short phrase.",
        ]
    elif template_id == "emoji_word":
        schema = dict(schema_common)
        extra = [
            "Use emojis in the question (2-4 emojis).",
            "The answer must be a common noun/verb/adjective (avoid brand names).",
        ]
    elif template_id == "odd_one_out":
        schema = dict(schema_common)
        schema["options"] = ["opt1", "opt2", "opt3", "opt4"]
        extra = [
            "Question format should be like: 'Odd one out?' or similar.",
            "Provide 4 options, and the answer must be EXACTLY one of the options.",
        ]
    else:
        schema = dict(schema_common)
        extra = []

    rules = "\n".join([f"- {r}" for r in base_rules + extra])
    return (
        f"{rules}\n\n"
        f"Return JSON with this schema:\n"
        f"{schema}\n"
    )

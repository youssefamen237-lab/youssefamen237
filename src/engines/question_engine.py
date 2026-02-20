from datetime import datetime, timezone
import json

from core.state import StateStore
from integrations.llm_providers import LLMProviders
from utils.risk import is_safe_text

TEMPLATES = [
    "True/False",
    "Multiple Choice",
    "Direct Question",
    "Guess the Answer",
    "Quick Challenge",
    "Only Geniuses",
    "Memory Test",
    "Visual Question",
]

CTAS = [
    "Can you solve it before the timer ends? Comment now!",
    "Drop your answer before reveal time!",
    "Think fast and write your guess below!",
    "Challenge your friends in the comments!",
    "How many did you get right today?",
    "Prove your IQ in the comments!",
]


class QuestionEngine:
    def __init__(self) -> None:
        self.state = StateStore()
        self.llm = LLMProviders()

    def create(self) -> dict:
        state = self.state.get()
        template = TEMPLATES[state["template_index"] % len(TEMPLATES)]
        prompt = (
            "Generate one fun English trivia question for US/UK/CA audience. "
            f"Template type: {template}. Return strict JSON with keys: question, answer, choices(optional list), category."
        )

        def _fallback_json() -> str:
            return json.dumps(
                {
                    "question": "Which planet is known as the Red Planet?",
                    "answer": "Mars",
                    "choices": ["Earth", "Mars", "Jupiter", "Venus"],
                    "category": "science",
                }
            )

        raw = self.llm.generate(prompt)
        try:
            data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            data = json.loads(_fallback_json())

        if self.state.is_duplicate_question(data["question"]):
            data["question"] = f"{data['question']} ({datetime.now(timezone.utc).strftime('%H%M%S')})"

        if not is_safe_text(data["question"] + " " + data["answer"]):
            data = json.loads(_fallback_json())

        cta = CTAS[(state["template_index"] + len(state["uploads"])) % len(CTAS)]
        self.state.update(
            lambda s: (
                s["question_history"].append(
                    {"question": data["question"], "answer": data["answer"], "created_at": datetime.now(timezone.utc).isoformat()}
                ),
                s.update({"template_index": (s["template_index"] + 1) % len(TEMPLATES)}),
            )
        )
        data["template"] = template
        data["cta"] = cta
        return data

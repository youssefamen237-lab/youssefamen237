import json
from datetime import datetime

from integrations.llm_providers import LLMProviders


class SEOEngine:
    def __init__(self) -> None:
        self.llm = LLMProviders()

    def build(self, topic: str, mode: str) -> dict:
        prompt = (
            f"Create YouTube SEO metadata in English for {mode} video about: {topic}. "
            "Return strict JSON with keys: title, description, tags(array), hashtags(array), cta_line."
        )
        raw = self.llm.generate(prompt)
        try:
            data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            data = {
                "title": f"{topic} Quiz Challenge #{datetime.utcnow().strftime('%j%H')}",
                "description": f"Play this {mode} challenge and comment your score.",
                "tags": ["quiz", "trivia", "challenge", mode],
                "hashtags": ["#quiz", "#trivia", "#challenge"],
                "cta_line": "Subscribe for daily brain challenges.",
            }
        data["description"] = f"{data['description']}\n\n{data['cta_line']}"
        return data

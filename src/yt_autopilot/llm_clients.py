\
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("empty LLM response")
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


@dataclass
class LLMResult:
    provider: str
    data: Dict[str, Any]
    raw_text: str


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self.api_key = api_key
        self.model = model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=10))
    def generate_json(self, prompt: str) -> LLMResult:
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.9,
                "top_p": 0.95,
                "max_output_tokens": 400,
            },
        )
        text = (getattr(resp, "text", "") or "").strip()
        data = _extract_json(text)
        return LLMResult(provider="gemini", data=data, raw_text=text)


class GroqClient:
    def __init__(self, api_key: str, model: str = "llama-3.1-70b-versatile") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=10))
    def generate_json(self, prompt: str) -> LLMResult:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that outputs ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.9,
            "top_p": 0.95,
            "max_tokens": 450,
        }
        r = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        doc = r.json()
        text = (((doc.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        data = _extract_json(text)
        return LLMResult(provider="groq", data=data, raw_text=text)

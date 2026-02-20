import requests

from core.config import CONFIG
from utils.retry import with_retry


class LLMProviders:
    @staticmethod
    def _gemini(prompt: str) -> str:
        if not CONFIG.gemini_api_key:
            raise RuntimeError("Missing GEMINI_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={CONFIG.gemini_api_key}"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    @staticmethod
    def _groq(prompt: str) -> str:
        if not CONFIG.groq_api_key:
            raise RuntimeError("Missing GROQ_API_KEY")
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {CONFIG.groq_api_key}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _openrouter(prompt: str) -> str:
        if not CONFIG.openrouter_key:
            raise RuntimeError("Missing OPENROUTER_KEY")
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {CONFIG.openrouter_key}"},
            json={
                "model": "meta-llama/llama-3.1-8b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def generate(self, prompt: str) -> str:
        return with_retry(
            lambda: self._gemini(prompt),
            retries=1,
            fallback=lambda: with_retry(
                lambda: self._groq(prompt),
                retries=1,
                fallback=lambda: self._openrouter(prompt),
            ),
        )

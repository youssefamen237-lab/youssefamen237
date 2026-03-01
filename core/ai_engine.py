"""
core/ai_engine.py – Quizzaro Unified AI Engine
================================================
Single interface for all AI text generation across the project.
Provider chain: Gemini 1.5 Flash → Groq LLaMA3-70B → OpenRouter Mistral.
Tracks failures per-run via FallbackManager and skips broken providers.
Enforces rate limits via RateLimiter.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class AIEngine:

    PROVIDER_ORDER = ["gemini", "groq", "openrouter"]

    def __init__(
        self,
        gemini_key: str,
        groq_key: str,
        openai_key: str,
        openrouter_key: str,
        fallback_manager=None,
    ) -> None:
        self._gemini_key = gemini_key
        self._groq_key = groq_key
        self._openai_key = openai_key
        self._openrouter_key = openrouter_key
        self._fb = fallback_manager

    # ── Provider callers ───────────────────────────────────────────────────

    def _call_gemini(self, prompt: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=self._gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        resp = model.generate_content(prompt)
        return resp.text.strip()

    def _call_groq(self, prompt: str) -> str:
        from groq import Groq
        client = Groq(api_key=self._groq_key)
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=900,
        )
        return chat.choices[0].message.content.strip()

    def _call_openrouter(self, prompt: str) -> str:
        import requests
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8,
                "max_tokens": 900,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # ── Dispatcher ─────────────────────────────────────────────────────────

    def generate_raw(self, prompt: str) -> str:
        """
        Send *prompt* to the first non-failed provider.
        Raises RuntimeError if all providers fail.
        """
        callers = {
            "gemini": self._call_gemini,
            "groq": self._call_groq,
            "openrouter": self._call_openrouter,
        }
        last_exc: Optional[Exception] = None

        for name in self.PROVIDER_ORDER:
            if self._fb and self._fb.is_failed("ai", name):
                continue
            try:
                logger.debug(f"[AIEngine] Trying: {name}")
                result = callers[name](prompt)
                if result and len(result) > 10:
                    return result
            except Exception as exc:
                logger.warning(f"[AIEngine] '{name}' failed: {exc}")
                if self._fb:
                    self._fb.mark_failed("ai", name)
                last_exc = exc
                time.sleep(1)

        raise RuntimeError(f"[AIEngine] All providers failed. Last: {last_exc}")

    def generate_json(self, prompt: str) -> dict:
        """
        Call generate_raw and parse JSON from the response.
        Strips markdown fences automatically.
        """
        import json
        raw = self.generate_raw(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"[AIEngine] No JSON in response: {raw[:200]}")
        return json.loads(match.group())

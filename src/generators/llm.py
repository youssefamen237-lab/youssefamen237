from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests

from ..utils.retry import retry


log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if not s:
        raise LLMError("empty LLM response")
    if s.startswith("```") and "```" in s:
        s = s.strip("` ")
        lines = s.splitlines()
        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        s = "\n".join(lines).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("no JSON object found")
    candidate = s[start : end + 1]
    try:
        obj = json.loads(candidate)
    except Exception as e:
        raise LLMError(f"invalid JSON: {e}")
    if not isinstance(obj, dict):
        raise LLMError("JSON is not an object")
    return obj


@dataclass(frozen=True)
class LLMConfig:
    groq_api_key: Optional[str]
    gemini_api_key: Optional[str]


class LLMOrchestrator:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._groq_model_cache: Optional[str] = None
        self._gemini_model_cache: Optional[str] = None

    def generate_json(self, prompt: str, *, max_tokens: int = 400) -> dict[str, Any]:
        last: Exception | None = None

        providers = []
        if self.cfg.groq_api_key:
            providers.append(self._groq_generate_json)
        if self.cfg.gemini_api_key:
            providers.append(self._gemini_generate_json)

        providers.append(self._local_stub_generate_json)

        for provider in providers:
            try:
                return provider(prompt, max_tokens=max_tokens)
            except Exception as e:
                last = e
                log.warning("LLM provider failed (%s): %s", provider.__name__, str(e))
        raise LLMError(f"All LLM providers failed: {last}")

    def _groq_pick_model(self) -> str:
        if self._groq_model_cache:
            return self._groq_model_cache

        key = self.cfg.groq_api_key
        if not key:
            raise LLMError("GROQ_API_KEY missing")

        preferred = [
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma-7b-it",
            "groq/compound",
            "groq/compound-mini",
        ]

        def _call() -> str:
            r = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=20,
            )
            if r.status_code != 200:
                raise LLMError(f"Groq models list failed: {r.status_code} {r.text}")
            data = r.json()
            ids = []
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                for m in data["data"]:
                    if isinstance(m, dict) and isinstance(m.get("id"), str):
                        ids.append(m["id"])
            for p in preferred:
                if p in ids:
                    return p
            for m in ids:
                if isinstance(m, str) and m:
                    return m
            raise LLMError("No Groq models available")

        model = retry(_call, tries=3, base_delay_s=1.0)
        self._groq_model_cache = model
        return model

    def _groq_generate_json(self, prompt: str, *, max_tokens: int = 400) -> dict[str, Any]:
        key = self.cfg.groq_api_key
        if not key:
            raise LLMError("GROQ_API_KEY missing")

        model = self._groq_pick_model()

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return ONLY valid JSON. No markdown. No extra keys beyond what is requested.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": max(64, min(1024, int(max_tokens))),
        }

        def _call() -> dict[str, Any]:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )
            if r.status_code != 200:
                raise LLMError(f"Groq chat failed: {r.status_code} {r.text}")
            data = r.json()
            content = None
            if isinstance(data, dict) and isinstance(data.get("choices"), list) and data["choices"]:
                ch0 = data["choices"][0]
                if isinstance(ch0, dict):
                    msg = ch0.get("message")
                    if isinstance(msg, dict):
                        content = msg.get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMError("Groq returned empty content")
            return _extract_json(content)

        return retry(_call, tries=3, base_delay_s=1.2)

    def _gemini_pick_model(self) -> str:
        if self._gemini_model_cache:
            return self._gemini_model_cache

        key = self.cfg.gemini_api_key
        if not key:
            raise LLMError("GEMINI_API_KEY missing")

        preferred_base = [
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]

        def _call() -> str:
            r = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                timeout=20,
            )
            if r.status_code != 200:
                raise LLMError(f"Gemini models list failed: {r.status_code} {r.text}")
            data = r.json()
            models = []
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                models = data["models"]
            base_ids = []
            for m in models:
                if isinstance(m, dict) and isinstance(m.get("baseModelId"), str):
                    if isinstance(m.get("supportedGenerationMethods"), list) and "generateContent" in m.get(
                        "supportedGenerationMethods"
                    ):
                        base_ids.append(m["baseModelId"])
            for p in preferred_base:
                if p in base_ids:
                    return p
            if base_ids:
                return base_ids[0]
            raise LLMError("No Gemini generateContent models available")

        model = retry(_call, tries=3, base_delay_s=1.0)
        self._gemini_model_cache = model
        return model

    def _gemini_generate_json(self, prompt: str, *, max_tokens: int = 400) -> dict[str, Any]:
        key = self.cfg.gemini_api_key
        if not key:
            raise LLMError("GEMINI_API_KEY missing")

        model = self._gemini_pick_model()

        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": max(64, min(1024, int(max_tokens))),
                "responseMimeType": "application/json",
            },
        }

        def _call() -> dict[str, Any]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            r = requests.post(url, json=body, timeout=45)
            if r.status_code != 200:
                raise LLMError(f"Gemini generateContent failed: {r.status_code} {r.text}")
            data = r.json()
            text = None
            if isinstance(data, dict) and isinstance(data.get("candidates"), list) and data["candidates"]:
                c0 = data["candidates"][0]
                if isinstance(c0, dict):
                    content = c0.get("content")
                    if isinstance(content, dict) and isinstance(content.get("parts"), list) and content["parts"]:
                        p0 = content["parts"][0]
                        if isinstance(p0, dict) and isinstance(p0.get("text"), str):
                            text = p0["text"]
            if not isinstance(text, str) or not text.strip():
                raise LLMError("Gemini returned empty text")
            return _extract_json(text)

        return retry(_call, tries=3, base_delay_s=1.2)

    def _local_stub_generate_json(self, prompt: str, *, max_tokens: int = 400) -> dict[str, Any]:
        _ = max_tokens
        return {
            "question": "What is the capital of Japan?",
            "answer": "Tokyo",
            "category": "Geography",
            "title": "10-Second Trivia: Capital of Japan? #shorts",
            "description": "Can you answer in 10 seconds? Write your guess in the comments!\n\n#shorts #trivia #quiz",
            "tags": ["trivia", "quiz", "geography", "capital cities", "general knowledge"],
            "hashtags": ["#shorts", "#trivia", "#quiz", "#geography"],
        }

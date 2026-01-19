from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from yt_auto.config import Config
from yt_auto.safety import validate_text_is_safe
from yt_auto.utils import RetryPolicy, backoff_sleep_s, clamp_list_str


@dataclass(frozen=True)
class QuizItem:
    category: str
    question: str
    answer: str
    cta: str
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]
    provider: str


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ValueError("no_json_found")
    block = m.group(0).strip()
    return json.loads(block)


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_s: int = 35) -> dict[str, Any]:
    r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "maxOutputTokens": 520},
    }
    data = _http_post_json(url, headers={"Content-Type": "application/json"}, payload=payload, timeout_s=45)
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError("gemini_no_candidates")
    parts = (((cands[0] or {}).get("content") or {}).get("parts")) or []
    if not parts:
        raise RuntimeError("gemini_no_parts")
    txt = (parts[0] or {}).get("text")
    if not isinstance(txt, str) or not txt.strip():
        raise RuntimeError("gemini_empty_text")
    return txt


def _call_openai_compat(base_url: str, api_key: str, model: str, prompt: str, extra_headers: dict[str, str] | None = None) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict JSON generator. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.95,
        "max_tokens": 560,
    }

    data = _http_post_json(url, headers=headers, payload=payload, timeout_s=45)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("openai_compat_no_choices")
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("openai_compat_empty_content")
    return content


def _prompt(seed: int) -> str:
    channel = "Quizzaro"

    formats = [
        "Geography: capital / country / continent",
        "Science: space / biology / physics basics",
        "Logic: clean riddles",
        "Animals & nature facts",
        "Food & culture (safe, non-controversial)",
        "Math: quick mental math",
        "Language: common English idioms meaning",
        "Sports: general records (non-controversial, timeless)",
        "Tech: basic computing facts",
    ]
    r = random.Random(seed)
    chosen = r.choice(formats)

    return f"""
Create ONE original YouTube Shorts quiz item for an English-speaking audience for the channel: {channel}

Hard rules (must follow):
- NO song lyrics, NO movie quotes, NO copyrighted passages.
- No hate, harassment, sexual content, violence, or self-harm content.
- Must be family-friendly and safe for monetization.
- The spoken audio (question + CTA) MUST fit within 10 seconds. Keep CTA VERY short.
- Question under 140 characters. Answer under 50 characters.
- Avoid politics, elections, wars, or controversial current events.
- Do NOT mention "AI" in the content.

Return ONLY valid JSON with these keys:
{{
  "category": "short category label",
  "question": "question text",
  "answer": "answer text",
  "cta": "VERY short call-to-action spoken after the question (max 60 chars)",
  "title": "a strong SHORTS title (max 90 chars, include 'Quizzaro' if possible)",
  "description": "SEO description (max 600 chars). Include: 1) one-line hook, 2) 'Comment your answer', 3) 'Subscribe to Quizzaro'.",
  "tags": ["12-18 simple tags (no hashtags here)"],
  "hashtags": ["#shorts", "#quizzaro", "#quiz", "#trivia", "#challenge", "... up to 8 total"]
}}

Content style for this item: {chosen}
Seed hint: {seed}
""".strip()


def _fallback_item(seed: int) -> QuizItem:
    r = random.Random(seed)
    mode = r.choice(["math", "geo", "science", "riddle"])

    if mode == "math":
        a = r.randint(12, 99)
        b = r.randint(2, 11)
        c = r.randint(5, 40)
        question = f"What is {a} × {b} + {c}?"
        answer = str(a * b + c)
        category = "Quick Math"
    elif mode == "geo":
        pairs = [
            ("France", "Paris"),
            ("Japan", "Tokyo"),
            ("Canada", "Ottawa"),
            ("Brazil", "Brasília"),
            ("Australia", "Canberra"),
            ("Egypt", "Cairo"),
            ("Italy", "Rome"),
            ("Spain", "Madrid"),
            ("Germany", "Berlin"),
            ("Mexico", "Mexico City"),
        ]
        country, capital = r.choice(pairs)
        question = f"What is the capital of {country}?"
        answer = capital
        category = "Geography"
    elif mode == "science":
        facts = [
            ("Which planet is known as the Red Planet?", "Mars"),
            ("What gas do plants absorb from the air?", "Carbon dioxide"),
            ("What is H2O commonly called?", "Water"),
            ("What force pulls objects toward Earth?", "Gravity"),
            ("Which star is closest to Earth?", "The Sun"),
        ]
        question, answer = r.choice(facts)
        category = "Science"
    else:
        riddles = [
            ("What has keys but can't open locks?", "A piano"),
            ("What gets wetter the more it dries?", "A towel"),
            ("What has hands but can't clap?", "A clock"),
            ("What has a neck but no head?", "A bottle"),
        ]
        question, answer = r.choice(riddles)
        category = "Riddle"

    cta = "Comment your answer!"
    title = f"Quizzaro: Can You Solve This in 10 Seconds? #{category}"
    description = "10-second quiz challenge!\nComment your answer.\nSubscribe to Quizzaro for daily quizzes."
    tags = ["quiz", "trivia", "challenge", "brain teaser", "shorts", "quizzaro", "education", "fun facts", "quick quiz"]
    hashtags = ["#shorts", "#quizzaro", "#quiz", "#trivia", "#challenge"]

    return QuizItem(
        category=category,
        question=question,
        answer=answer,
        cta=cta,
        title=title[:90],
        description=description[:600],
        tags=tags,
        hashtags=hashtags,
        provider="fallback",
    )


def generate_quiz_item(cfg: Config, seed: int) -> QuizItem:
    prompt = _prompt(seed)
    policy = RetryPolicy(max_attempts=4, base_sleep_s=0.9, max_sleep_s=8.0)

    last_err: Exception | None = None

    for provider in cfg.llm_order:
        provider = provider.strip().lower()

        if provider == "gemini":
            if not cfg.gemini_api_key:
                continue
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    txt = _call_gemini(cfg.gemini_api_key, cfg.gemini_model, prompt)
                    obj = _extract_json(txt)
                    item = _coerce_item(obj, provider="gemini")
                    if not validate_text_is_safe(item.question, item.answer).ok:
                        raise RuntimeError("unsafe_content_from_llm")
                    return item
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

        if provider == "groq":
            if not cfg.groq_api_key:
                continue
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    txt = _call_openai_compat("https://api.groq.com/openai/v1", cfg.groq_api_key, cfg.groq_model, prompt)
                    obj = _extract_json(txt)
                    item = _coerce_item(obj, provider="groq")
                    if not validate_text_is_safe(item.question, item.answer).ok:
                        raise RuntimeError("unsafe_content_from_llm")
                    return item
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

        if provider == "openrouter":
            if not cfg.openrouter_key:
                continue
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    headers = {"HTTP-Referer": "https://github.com/", "X-Title": "yt-auto"}
                    txt = _call_openai_compat(
                        "https://openrouter.ai/api/v1",
                        cfg.openrouter_key,
                        cfg.openrouter_model,
                        prompt,
                        extra_headers=headers,
                    )
                    obj = _extract_json(txt)
                    item = _coerce_item(obj, provider="openrouter")
                    if not validate_text_is_safe(item.question, item.answer).ok:
                        raise RuntimeError("unsafe_content_from_llm")
                    return item
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

        if provider == "openai":
            if not cfg.allow_paid_providers:
                continue
            if not cfg.openai_api_key:
                continue
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    txt = _call_openai_compat("https://api.openai.com/v1", cfg.openai_api_key, cfg.openai_model, prompt)
                    obj = _extract_json(txt)
                    item = _coerce_item(obj, provider="openai")
                    if not validate_text_is_safe(item.question, item.answer).ok:
                        raise RuntimeError("unsafe_content_from_llm")
                    return item
                except Exception as e:
                    last_err = e
                    time.sleep(backoff_sleep_s(attempt, policy))

    _ = last_err
    return _fallback_item(seed)


def _coerce_item(obj: dict[str, Any], provider: str) -> QuizItem:
    category = str(obj.get("category", "")).strip() or "Quiz"
    question = str(obj.get("question", "")).strip()
    answer = str(obj.get("answer", "")).strip()
    cta = str(obj.get("cta", "")).strip() or "Comment your answer!"
    title = str(obj.get("title", "")).strip() or "Quizzaro: Can You Answer in 10 Seconds? #Shorts"
    description = str(obj.get("description", "")).strip() or "Quick quiz!\nComment your answer.\nSubscribe to Quizzaro."
    tags = obj.get("tags") if isinstance(obj.get("tags"), list) else []
    hashtags = obj.get("hashtags") if isinstance(obj.get("hashtags"), list) else []

    tags_list = clamp_list_str([str(x) for x in tags], max_items=18, max_total_chars=450)
    hashtags_list = clamp_list_str([str(x) for x in hashtags], max_items=8, max_total_chars=140)

    low = [h.lower() for h in hashtags_list]
    if "#shorts" not in low:
        hashtags_list = ["#shorts"] + hashtags_list
    low = [h.lower() for h in hashtags_list]
    if "#quizzaro" not in low:
        hashtags_list = ["#quizzaro"] + [h for h in hashtags_list if h.lower() != "#quizzaro"]

    dedup: list[str] = []
    seen = set()
    for h in hashtags_list:
        hh = h.strip()
        if not hh:
            continue
        k = hh.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(hh)
    hashtags_list = dedup[:8]

    return QuizItem(
        category=category,
        question=question,
        answer=answer,
        cta=cta[:60],
        title=title[:90],
        description=description[:600],
        tags=tags_list,
        hashtags=hashtags_list,
        provider=provider,
    )

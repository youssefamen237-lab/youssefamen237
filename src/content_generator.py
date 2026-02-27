"""
content_generator.py
Generates quiz questions, titles, descriptions, tags, CTAs using Gemini/Groq/OpenRouter.
Falls back between providers automatically.
"""

import os
import json
import random
import hashlib
import datetime
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

TEMPLATES = [
    "True / False",
    "Multiple Choice",
    "Direct Question",
    "Guess the Answer",
    "Quick Challenge",
    "Only Geniuses",
    "Memory Test",
    "Visual Question",
]

CTA_POOL = [
    "If you know the answer before the 5 seconds end, drop it in the comments.",
    "Can you answer this before the timer runs out? Comment below!",
    "Think you're smart enough? Prove it before time's up!",
    "Type your answer before 5 seconds — let's see how fast you are!",
    "Only geniuses answer this in time. Go!",
    "Challenge yourself — answer before the clock hits zero!",
    "Race the clock! Drop your answer in the comments now.",
    "Quick! You have 5 seconds. What's your answer?",
    "Smart people answer instantly. Are you one of them?",
    "Comment the answer — let's see who's first!",
    "Think fast! Answer before the countdown ends.",
    "Pause if you have to — but can you get it right?",
]

QUESTION_CATEGORIES = [
    "general knowledge",
    "science and nature",
    "history",
    "geography",
    "pop culture",
    "sports trivia",
    "food and drink",
    "technology",
    "movies and TV",
    "animals and wildlife",
    "space and astronomy",
    "human body",
    "famous inventions",
    "world records",
    "mythology",
]


def _load_used_questions(path="data/used_questions.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def _save_used_questions(used: dict, path="data/used_questions.json"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(used, f, indent=2)


def _question_hash(question_text: str) -> str:
    return hashlib.md5(question_text.strip().lower().encode()).hexdigest()[:12]


def _is_duplicate(question_text: str, used: dict, min_days: int = 15) -> bool:
    h = _question_hash(question_text)
    if h not in used:
        return False
    last_used = datetime.datetime.fromisoformat(used[h])
    delta = (datetime.datetime.utcnow() - last_used).days
    return delta < min_days


def _mark_used(question_text: str, used: dict):
    h = _question_hash(question_text)
    used[h] = datetime.datetime.utcnow().isoformat()


def _call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 1024},
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.0,
        "max_tokens": 1024,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_openrouter(prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/quiz-plus",
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def generate_text(prompt: str) -> str:
    providers = []
    if GEMINI_API_KEY:
        providers.append(("Gemini", _call_gemini))
    if GROQ_API_KEY:
        providers.append(("Groq", _call_groq))
    if OPENROUTER_KEY:
        providers.append(("OpenRouter", _call_openrouter))

    last_error = None
    for name, fn in providers:
        try:
            result = fn(prompt)
            print(f"[ContentGen] Used provider: {name}")
            return result
        except Exception as e:
            print(f"[ContentGen] Provider {name} failed: {e}")
            last_error = e
    raise RuntimeError(f"All AI providers failed. Last error: {last_error}")


def generate_question(template: str = None, category: str = None) -> dict:
    """
    Returns a dict:
    {
        "question": str,
        "answer": str,
        "trivia": str,          # Short fun fact for long video
        "template": str,
        "category": str,
        "choices": list[str],   # Only for Multiple Choice
    }
    """
    used = _load_used_questions()

    if template is None:
        template = random.choice(TEMPLATES)
    if category is None:
        category = random.choice(QUESTION_CATEGORIES)

    for attempt in range(10):
        if template == "Multiple Choice":
            prompt = (
                f"Generate a creative {category} trivia question in the style '{template}' for an English-speaking YouTube audience.\n"
                "Return ONLY valid JSON with keys: question, answer, choices (array of 4 strings), trivia (1 fun sentence about the answer).\n"
                "No extra text, no markdown fences. Example:\n"
                '{"question":"...","answer":"...","choices":["A","B","C","D"],"trivia":"..."}'
            )
        elif template == "True / False":
            prompt = (
                f"Generate a creative {category} True/False trivia question for a YouTube Shorts audience.\n"
                "Return ONLY valid JSON with keys: question, answer (True or False), trivia (1 fun sentence).\n"
                "No extra text. Example:\n"
                '{"question":"...","answer":"True","trivia":"..."}'
            )
        else:
            prompt = (
                f"Generate a creative {category} trivia question in the style '{template}' for an English-speaking YouTube audience.\n"
                "Return ONLY valid JSON with keys: question, answer, trivia (1 fun sentence about the answer).\n"
                "No extra text, no markdown fences."
            )

        raw = generate_text(prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except Exception:
                    continue
            else:
                continue

        question_text = data.get("question", "")
        if not question_text:
            continue

        if _is_duplicate(question_text, used):
            print(f"[ContentGen] Duplicate detected, regenerating (attempt {attempt+1})...")
            continue

        _mark_used(question_text, used)
        _save_used_questions(used)

        return {
            "question": question_text,
            "answer": data.get("answer", ""),
            "trivia": data.get("trivia", ""),
            "template": template,
            "category": category,
            "choices": data.get("choices", []),
        }

    raise RuntimeError("Failed to generate a non-duplicate question after 10 attempts.")


def generate_short_metadata(question: str, answer: str, template: str) -> dict:
    prompt = (
        f"You are an expert YouTube SEO specialist. Generate metadata for a YouTube Short.\n"
        f"Topic: Quiz question — '{question}' Answer: '{answer}'\n"
        f"Template style: {template}\n"
        "Return ONLY valid JSON with keys:\n"
        "  title (max 60 chars, catchy, no clickbait lies),\n"
        "  description (150-200 chars, natural, includes CTA to subscribe),\n"
        "  tags (array of 10-15 strings),\n"
        "  hashtags (array of 5 strings starting with #).\n"
        "No markdown, no extra text."
    )
    raw = generate_text(prompt)
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        data = json.loads(raw)
    except Exception:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = {
                "title": f"Can You Answer This? {question[:40]}",
                "description": f"Can you answer before the timer? {question} Answer: {answer} Subscribe for daily quizzes!",
                "tags": ["quiz", "trivia", "shorts", "challenge", template.lower().replace(" ", ""), "brain", "knowledge", "fun", "viral", "test"],
                "hashtags": ["#Quiz", "#Trivia", "#Shorts", "#BrainTest", "#Challenge"],
            }
    return data


def generate_long_video_script(questions: list) -> dict:
    questions_text = "\n".join(
        [f"{i+1}. Q: {q['question']} A: {q['answer']} Trivia: {q.get('trivia','')}" for i, q in enumerate(questions)]
    )
    prompt = (
        "You are a YouTube scriptwriter. Write an engaging script for a 5-minute trivia video.\n"
        f"Use these {len(questions)} questions:\n{questions_text}\n\n"
        "Structure:\n"
        "- Exciting intro hook (10 seconds): Challenge viewers, e.g. '99% of people fail this quiz...'\n"
        "- Every 10 questions: Add an energetic checkpoint line encouraging likes/comments\n"
        "- Each question: Read question, pause hint, reveal answer with trivia fact\n"
        "- Outro: Strong subscribe CTA\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "title": "...",\n'
        '  "description": "...",\n'
        '  "tags": [...],\n'
        '  "hashtags": [...],\n'
        '  "script_segments": [\n'
        '    {"text": "...", "type": "intro|question|answer|checkpoint|outro", "question_index": null}\n'
        "  ]\n"
        "}"
    )
    raw = generate_text(prompt)
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(raw)
    except Exception:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def get_random_cta() -> str:
    return random.choice(CTA_POOL)


def get_next_template_rotation(last_templates: list) -> str:
    available = [t for t in TEMPLATES if t not in last_templates[-3:]]
    if not available:
        available = TEMPLATES
    return random.choice(available)

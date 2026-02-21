"""
Content Generator — uses AI APIs to generate questions for YouTube Shorts.
Falls back across: Gemini → Groq → OpenAI → OpenRouter → internal bank
"""

import os
import json
import random
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

DATA_DIR = Path("data/questions")
DATA_DIR.mkdir(parents=True, exist_ok=True)
PUBLISHED_LOG = Path("data/published/questions_log.json")
PUBLISHED_LOG.parent.mkdir(parents=True, exist_ok=True)

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

CATEGORIES = [
    "general knowledge",
    "science",
    "history",
    "geography",
    "technology",
    "culture",
    "entertainment facts",
    "nature",
    "mathematics",
    "language",
]

CTA_VARIANTS = [
    "If you know the answer before the 5 seconds end, drop it in the comments!",
    "Can you solve this before the timer runs out? Comment below!",
    "Think you're smart enough? Prove it in the comments!",
    "Type your answer before time's up — let's see who gets it!",
    "Challenge accepted? Write your answer down below!",
    "Faster than 5 seconds? Show off in the comments!",
    "Drop the answer in the comments — no cheating!",
    "Think fast — comment your answer before the reveal!",
    "Who gets this right? Answer in the comments!",
    "Quick minds only — drop your answer below!",
    "Race the clock — type your answer in the comments!",
    "Genius alert! Comment your answer now!",
]

INTERNAL_QUESTION_BANK = [
    {
        "question": "What is the capital of Australia?",
        "answer": "Canberra",
        "template": "Direct Question",
        "category": "geography",
    },
    {
        "question": "True or False: The Great Wall of China is visible from space.",
        "answer": "False",
        "template": "True / False",
        "category": "general knowledge",
    },
    {
        "question": "How many planets are in our solar system?",
        "answer": "8",
        "template": "Direct Question",
        "category": "science",
    },
    {
        "question": "Which element has the chemical symbol 'Au'?",
        "answer": "Gold",
        "template": "Guess the Answer",
        "category": "science",
    },
    {
        "question": "True or False: Bats are blind.",
        "answer": "False",
        "template": "True / False",
        "category": "nature",
    },
    {
        "question": "What year did World War II end?",
        "answer": "1945",
        "template": "Direct Question",
        "category": "history",
    },
    {
        "question": "Which country invented pizza?",
        "answer": "Italy",
        "template": "Guess the Answer",
        "category": "culture",
    },
    {
        "question": "How many sides does a hexagon have?",
        "answer": "6",
        "template": "Only Geniuses",
        "category": "mathematics",
    },
    {
        "question": "What is the fastest land animal?",
        "answer": "Cheetah",
        "template": "Quick Challenge",
        "category": "nature",
    },
    {
        "question": "Which planet is known as the Red Planet?",
        "answer": "Mars",
        "template": "Multiple Choice",
        "category": "science",
    },
    {
        "question": "True or False: Diamonds are made of carbon.",
        "answer": "True",
        "template": "True / False",
        "category": "science",
    },
    {
        "question": "What language is spoken in Brazil?",
        "answer": "Portuguese",
        "template": "Direct Question",
        "category": "geography",
    },
    {
        "question": "How many bones are in the human body?",
        "answer": "206",
        "template": "Only Geniuses",
        "category": "science",
    },
    {
        "question": "What is the largest ocean on Earth?",
        "answer": "Pacific Ocean",
        "template": "Guess the Answer",
        "category": "geography",
    },
    {
        "question": "True or False: Lightning never strikes the same place twice.",
        "answer": "False",
        "template": "True / False",
        "category": "general knowledge",
    },
    {
        "question": "Which country has the most natural lakes?",
        "answer": "Canada",
        "template": "Quick Challenge",
        "category": "geography",
    },
    {
        "question": "What is the smallest country in the world?",
        "answer": "Vatican City",
        "template": "Direct Question",
        "category": "geography",
    },
    {
        "question": "How many colors are in a rainbow?",
        "answer": "7",
        "template": "Memory Test",
        "category": "general knowledge",
    },
    {
        "question": "True or False: Sound travels faster in water than in air.",
        "answer": "True",
        "template": "True / False",
        "category": "science",
    },
    {
        "question": "What is the longest river in the world?",
        "answer": "Nile River",
        "template": "Guess the Answer",
        "category": "geography",
    },
    {
        "question": "Which metal is liquid at room temperature?",
        "answer": "Mercury",
        "template": "Only Geniuses",
        "category": "science",
    },
    {
        "question": "How many letters are in the English alphabet?",
        "answer": "26",
        "template": "Quick Challenge",
        "category": "language",
    },
    {
        "question": "What year was the first iPhone released?",
        "answer": "2007",
        "template": "Direct Question",
        "category": "technology",
    },
    {
        "question": "True or False: Humans share 98% of DNA with chimpanzees.",
        "answer": "True",
        "template": "True / False",
        "category": "science",
    },
    {
        "question": "Which country is home to the kangaroo?",
        "answer": "Australia",
        "template": "Guess the Answer",
        "category": "nature",
    },
    {
        "question": "What is the hardest natural substance on Earth?",
        "answer": "Diamond",
        "template": "Only Geniuses",
        "category": "science",
    },
    {
        "question": "How many continents are there on Earth?",
        "answer": "7",
        "template": "Direct Question",
        "category": "geography",
    },
    {
        "question": "True or False: The Sun is a planet.",
        "answer": "False",
        "template": "True / False",
        "category": "science",
    },
    {
        "question": "Which country built the Eiffel Tower?",
        "answer": "France",
        "template": "Direct Question",
        "category": "history",
    },
    {
        "question": "What is the chemical symbol for water?",
        "answer": "H2O",
        "template": "Quick Challenge",
        "category": "science",
    },
]


def load_published_log():
    if PUBLISHED_LOG.exists():
        with open(PUBLISHED_LOG) as f:
            return json.load(f)
    return []


def save_published_log(log):
    with open(PUBLISHED_LOG, "w") as f:
        json.dump(log, f, indent=2)


def was_recently_used(question_text, days=15):
    log = load_published_log()
    cutoff = datetime.now() - timedelta(days=days)
    for entry in log:
        if entry.get("question") == question_text:
            used_date = datetime.fromisoformat(entry.get("date", "2000-01-01"))
            if used_date > cutoff:
                return True
    return False


def mark_as_used(question_data):
    log = load_published_log()
    log.append(
        {
            "question": question_data["question"],
            "answer": question_data["answer"],
            "template": question_data["template"],
            "date": datetime.now().isoformat(),
        }
    )
    save_published_log(log)


def get_last_used_template():
    log = load_published_log()
    if log:
        return log[-1].get("template", "")
    return ""


def pick_template(exclude=None):
    available = [t for t in TEMPLATES if t != exclude]
    return random.choice(available)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def generate_with_gemini(template, category):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No GEMINI_API_KEY")

    prompt = build_prompt(template, category)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 300},
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return parse_ai_response(text, template, category)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def generate_with_groq(template, category):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("No GROQ_API_KEY")

    prompt = build_prompt(template, category)
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "mixtral-8x7b-32768",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 300,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return parse_ai_response(text, template, category)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def generate_with_openai(template, category):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("No OPENAI_API_KEY")

    prompt = build_prompt(template, category)
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 300,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return parse_ai_response(text, template, category)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def generate_with_openrouter(template, category):
    api_key = os.environ.get("OPENROUTER_KEY")
    if not api_key:
        raise ValueError("No OPENROUTER_KEY")

    prompt = build_prompt(template, category)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 300,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return parse_ai_response(text, template, category)


def build_prompt(template, category):
    return f"""Create a trivia question for a YouTube Short video.
Template type: {template}
Category: {category}
Target audience: English-speaking (American, British, Canadian)

Return ONLY this JSON format (no extra text):
{{
  "question": "the question text here",
  "answer": "the correct answer here"
}}

Rules:
- Question must be factually correct with a definitive answer
- Keep question under 15 words
- Keep answer under 5 words
- Make it engaging and appropriate for general audiences
- For True/False: start with "True or False:"
- For Multiple Choice: include 4 options A/B/C/D in the question
- For Only Geniuses: make it slightly harder
"""


def parse_ai_response(text, template, category):
    import re
    text = text.strip()
    match = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "question": data.get("question", "").strip(),
                "answer": data.get("answer", "").strip(),
                "template": template,
                "category": category,
            }
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse AI response: {text[:200]}")


def get_question_from_internal_bank(template=None, exclude_recent=True):
    available = list(INTERNAL_QUESTION_BANK)
    if template:
        filtered = [q for q in available if q["template"] == template]
        if filtered:
            available = filtered
    if exclude_recent:
        available = [q for q in available if not was_recently_used(q["question"])]
    if not available:
        available = list(INTERNAL_QUESTION_BANK)
    return random.choice(available)


def generate_question():
    last_template = get_last_used_template()
    template = pick_template(exclude=last_template)
    category = random.choice(CATEGORIES)

    providers = [
        generate_with_gemini,
        generate_with_groq,
        generate_with_openai,
        generate_with_openrouter,
    ]
    random.shuffle(providers)

    for provider in providers:
        try:
            result = provider(template, category)
            if result and result.get("question") and result.get("answer"):
                if not was_recently_used(result["question"]):
                    print(f"[Content] Generated via {provider.__name__}: {result['question']}")
                    return result
        except Exception as e:
            print(f"[Content] Provider {provider.__name__} failed: {e}")
            continue

    print("[Content] All AI providers failed, using internal bank")
    return get_question_from_internal_bank(template)


def get_cta(exclude=None):
    available = [c for c in CTA_VARIANTS if c != exclude]
    return random.choice(available)


def get_last_used_cta():
    log = load_published_log()
    if log and log[-1].get("cta"):
        return log[-1]["cta"]
    return ""


def generate_question_for_video():
    question_data = generate_question()
    cta = get_cta(exclude=get_last_used_cta())
    question_data["cta"] = cta
    return question_data


if __name__ == "__main__":
    q = generate_question_for_video()
    print(json.dumps(q, indent=2))

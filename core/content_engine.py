"""
core/content_engine.py – Quizzaro Question Generation Engine
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import wikipediaapi
from loguru import logger
from pytrends.request import TrendReq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from tinydb import TinyDB, Query

# ── Path to persistent question DB
DB_PATH = Path("data/questions_db.json")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Template IDs
TEMPLATES = [
    "true_false",
    "multiple_choice",
    "direct_question",
    "guess_answer",
    "quick_challenge",
    "only_geniuses",
    "memory_test",
    "visual_question",
    "visual_levels",
]

# ── Category pool for MODERN diverse question generation ───────────────────────
CATEGORIES = [
    "pop culture secrets", "mind-bending riddles", "famous movie mistakes", 
    "gaming easter eggs", "crazy psychology facts", "bizarre history", 
    "urban legends", "space mysteries", "superhero trivia", "internet mysteries",
    "mandela effect", "impossible science", "hidden logos", "world records"
]

TARGET_AUDIENCES = ["American", "British", "Canadian", "Australian", "Irish"]


# ─────────────────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QuestionObject:
    question_id: str
    template: str
    question_text: str
    correct_answer: str
    wrong_answers: list[str]
    explanation: str
    category: str
    difficulty: str
    target_audience: str
    cta_text: str
    created_at: str
    source_hint: str
    fun_fact: str


# ─────────────────────────────────────────────────────────────────────────────
#  Raw content fetchers
# ─────────────────────────────────────────────────────────────────────────────

class WikipediaFetcher:
    def __init__(self) -> None:
        self._wiki = wikipediaapi.Wikipedia(
            language="en",
            user_agent="Quizzaro-Bot/1.0 (github.com/quizzaro)"
        )

    def fetch_random_facts(self, category: str, count: int = 5) -> list[str]:
        facts: list[str] = []
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": category,
            "srlimit": count * 2,
            "format": "json",
            "srnamespace": "0",
        }

        try:
            resp = requests.get(search_url, params=params, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("query", {}).get("search", [])

            for item in results:
                title = item.get("title", "")
                page = self._wiki.page(title)
                if page.exists() and len(page.summary) > 100:
                    facts.append(page.summary[:400].strip())
                    if len(facts) >= count:
                        break

        except Exception as exc:
            logger.warning(f"[WikiFetcher] Failed for '{category}': {exc}")

        return facts


class GoogleTrendsFetcher:
    def __init__(self) -> None:
        self._pytrends = TrendReq(hl="en-US", tz=360)

    def fetch_trending_topics(self, country: str = "united_states") -> list[str]:
        topics: list[str] = []
        try:
            trending_df = self._pytrends.trending_searches(pn=country)
            topics = trending_df[0].tolist()[:10]
        except Exception as exc:
            logger.warning(f"[TrendsFetcher] Failed: {exc}")
        return topics


class NewsFetcher:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._base = "https://newsapi.org/v2/top-headlines"

    def fetch_headlines(self, count: int = 10) -> list[str]:
        headlines: list[str] = []
        try:
            resp = requests.get(
                self._base,
                params={
                    "language": "en",
                    "pageSize": count,
                    "apiKey": self._api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            headlines = [a["title"] for a in articles if a.get("title")]
        except Exception as exc:
            logger.warning(f"[NewsFetcher] Failed: {exc}")
        return headlines


class YouTubeTrendsFetcher:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._base = "https://www.googleapis.com/youtube/v3/videos"

    def fetch_trending_titles(self, region: str = "US", count: int = 10) -> list[str]:
        titles: list[str] = []
        try:
            resp = requests.get(
                self._base,
                params={
                    "part": "snippet",
                    "chart": "mostPopular",
                    "regionCode": region,
                    "maxResults": count,
                    "key": self._api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            titles = [i["snippet"]["title"] for i in items]
        except Exception as exc:
            logger.warning(f"[YTTrendsFetcher] Failed: {exc}")
        return titles


# ─────────────────────────────────────────────────────────────────────────────
#  AI Question Generator
# ─────────────────────────────────────────────────────────────────────────────

class AIQuestionGenerator:
    PROVIDER_ORDER = ["gemini", "groq", "openrouter"]

    def __init__(
        self,
        gemini_key: str,
        groq_key: str,
        openrouter_key: str,
    ) -> None:
        self._gemini_key = gemini_key
        self._groq_key = groq_key
        self._openrouter_key = openrouter_key

    def _call_gemini(self, prompt: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=self._gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        response = model.generate_content(prompt)
        return response.text

    def _call_groq(self, prompt: str) -> str:
        from groq import Groq
        client = Groq(api_key=self._groq_key)
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9, # slightly higher for creativity
            max_tokens=800,
        )
        return chat.choices[0].message.content

    def _call_openrouter(self, prompt: str) -> str:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
                "max_tokens": 800,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def generate_raw(self, prompt: str) -> str:
        callers = {
            "gemini": self._call_gemini,
            "groq": self._call_groq,
            "openrouter": self._call_openrouter,
        }
        last_exc: Exception | None = None
        for name in self.PROVIDER_ORDER:
            try:
                logger.debug(f"[AIGen] Trying provider: {name}")
                result = callers[name](prompt)
                if result and len(result.strip()) > 20:
                    return result
            except Exception as exc:
                logger.warning(f"[AIGen] Provider '{name}' failed: {exc}")
                last_exc = exc
                time.sleep(1)

        raise RuntimeError(f"All AI providers failed. Last error: {last_exc}")

    def _build_prompt(
        self,
        template: str,
        category: str,
        difficulty: str,
        audience: str,
        context_facts: list[str],
    ) -> str:
        context_block = "\n".join(f"- {f}" for f in context_facts[:3]) if context_facts else "Modern Gen-Z/Millennial culture."

        template_instructions = {
            "true_false": (
                "Write a highly controversial or mind-blowing statement that sounds false but might be True (or vice versa). "
                "Do NOT write a question. The 'correct_answer' MUST be exactly 'True' or 'False'. "
                "The 'wrong_answers' array MUST contain exactly one item: the opposite word."
            ),
            "multiple_choice": (
                "Create a modern, surprising multiple-choice question. Start with a hook like 'Did you know?' or 'I bet you can't guess...'. "
                "Exactly 4 options total (1 correct + 3 very tricky distractors)."
            ),
            "direct_question": (
                "Create a fast, punchy question. Start with 'Quick!'. "
                "Single short correct answer (1–3 words). 3 plausible distractors."
            ),
            "guess_answer": (
                "Create a 'Guess Who/What' riddle. Describe something famous (movie, brand, celebrity) using emoji clues or vague descriptions. "
            ),
            "quick_challenge": (
                "Create a stressful, fast-paced challenge. Start with 'You have 5 seconds:'. "
                "Make it a visual memory test or a trick question."
            ),
            "only_geniuses": (
                "Start the question EXPLICITLY with '99% of people fail this:' or 'Only true geniuses know:'. "
                "Make it a genuinely tricky logic or pop-culture riddle."
            ),
            "memory_test": (
                "Nostalgia challenge! Ask about a detail from a famous 2000s/2010s movie, song, or trend. "
                "Start with 'Let's test your memory:'"
            ),
            "visual_question": (
                "Describe a famous logo, flag, or movie scene perfectly, and ask them to name it."
            ),
            "visual_levels": (
                "Create a question suitable for a LEVEL UP game (EASY/MEDIUM/HARD/EXPERT). Make it an escalating challenge. "
                "E.g., 'What is the hardest language to learn?' or 'Which of these logos is fake?'"
            ),
        }

        t_instruction = template_instructions.get(template, template_instructions["multiple_choice"])

        prompt = f"""You are a viral TikTok/Shorts creator known for fast, modern, and highly engaging trivia. 
Your audience has a short attention span, so you must use strong hooks.

TEMPLATE: {template.replace('_', ' ').title()}
CATEGORY: {category}
DIFFICULTY: {difficulty}
CONTEXT (Optional inspiration):
{context_block}

INSTRUCTIONS:
{t_instruction}

STRICT OUTPUT FORMAT (valid JSON only):
{{
  "question_text": "YOUR_STRONG_HOOK_AND_QUESTION_HERE",
  "correct_answer": "...",
  "wrong_answers": ["...", "...", "..."],
  "explanation": "One punchy sentence explaining the answer.",
  "difficulty": "{difficulty}",
  "category": "{category}",
  "fun_fact": "A crazy related fact in one sentence.",
  "source_hint": "viral_trends"
}}

RULES:
- The question_text MUST be catchy and start with a hook to stop people from swiping.
- Tone: Exciting, modern, challenging.
- English only. Target audience: {audience}.
- No boring textbook questions.
- Output ONLY the JSON object. Nothing else."""

        return prompt

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def generate_question(
        self,
        template: str,
        category: str,
        difficulty: str,
        audience: str,
        context_facts: list[str],
    ) -> dict:
        prompt = self._build_prompt(template, category, difficulty, audience, context_facts)
        raw = self.generate_raw(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in AI response: {raw[:200]}")

        data = json.loads(json_match.group())
        return data


# ─────────────────────────────────────────────────────────────────────────────
#  Anti-Duplicate Guard
# ─────────────────────────────────────────────────────────────────────────────

class QuestionDeduplicator:
    REPEAT_DAYS = 15

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db = TinyDB(db_path)
        self._table = self._db.table("used_questions")

    def _fingerprint(self, question_text: str) -> str:
        return hashlib.sha256(question_text.lower().strip().encode()).hexdigest()

    def is_duplicate(self, question_text: str) -> bool:
        fp = self._fingerprint(question_text)
        Q = Query()
        records = self._table.search(Q.fingerprint == fp)
        if not records:
            return False
        last_used = datetime.fromisoformat(records[0]["used_at"])
        delta = datetime.utcnow() - last_used
        return delta.days < self.REPEAT_DAYS

    def mark_used(self, question_text: str, question_id: str) -> None:
        fp = self._fingerprint(question_text)
        Q = Query()
        entry = {
            "fingerprint": fp,
            "question_id": question_id,
            "used_at": datetime.utcnow().isoformat(),
        }
        if self._table.search(Q.fingerprint == fp):
            self._table.update(entry, Q.fingerprint == fp)
        else:
            self._table.insert(entry)


# ─────────────────────────────────────────────────────────────────────────────
#  CTA Generator
# ─────────────────────────────────────────────────────────────────────────────

CTA_POOL = [
    "I bet you didn't get this! Prove me wrong in the comments 👇",
    "Did you beat the timer? Tell me your score! ⏱️",
    "Drop your answer before the reveal! No cheating 👀",
    "Only true legends got this right. Are you one of them? 🧠",
    "Send this to a friend to test their brain! 🚀",
]

def pick_cta() -> str:
    return random.choice(CTA_POOL)


# ─────────────────────────────────────────────────────────────────────────────
#  Master Content Engine
# ─────────────────────────────────────────────────────────────────────────────

class ContentEngine:
    def __init__(
        self,
        gemini_key: str,
        groq_key: str,
        openrouter_key: str,
        news_api_key: str,
        youtube_api_key: str,
    ) -> None:
        self._ai = AIQuestionGenerator(
            gemini_key=gemini_key,
            groq_key=groq_key,
            openrouter_key=openrouter_key,
        )
        self._wiki = WikipediaFetcher()
        self._trends = GoogleTrendsFetcher()
        self._news = NewsFetcher(api_key=news_api_key)
        self._yt = YouTubeTrendsFetcher(api_key=youtube_api_key)
        self._dedup = QuestionDeduplicator()
        self._recent_templates: list[str] = []

    def _pick_template(self) -> str:
        recent_counts: dict[str, int] = {}
        for t in self._recent_templates[-8:]:
            recent_counts[t] = recent_counts.get(t, 0) + 1

        available = [t for t in TEMPLATES if recent_counts.get(t, 0) < 2]
        if not available:
            available = TEMPLATES

        chosen = random.choice(available)
        self._recent_templates.append(chosen)
        return chosen

    def _gather_context(self, category: str) -> list[str]:
        facts: list[str] = []
        wiki_facts = self._wiki.fetch_random_facts(category, count=2)
        facts.extend(wiki_facts)

        if random.random() < 0.6:
            trends = self._trends.fetch_trending_topics()
            if trends:
                facts.append(f"Trending topic for inspiration: {random.choice(trends)}")

        return facts[:4]

    def _build_question_object(self, raw: dict, template: str, category: str, audience: str) -> QuestionObject:
        question_text = raw["question_text"].strip()
        correct_answer = str(raw["correct_answer"]).strip()
        wrong_answers = [str(w).strip() for w in raw.get("wrong_answers", [])]

        if not wrong_answers:
            wrong_answers = ["False"] if correct_answer.lower() == "true" else ["True"]

        question_id = hashlib.sha256(question_text.lower().encode()).hexdigest()[:16]

        return QuestionObject(
            question_id=question_id,
            template=template,
            question_text=question_text,
            correct_answer=correct_answer,
            wrong_answers=wrong_answers,
            explanation=raw.get("explanation", "").strip(),
            category=category,
            difficulty=raw.get("difficulty", "medium"),
            target_audience=audience,
            cta_text=pick_cta(),
            created_at=datetime.utcnow().isoformat(),
            source_hint=raw.get("source_hint", "general"),
            fun_fact=raw.get("fun_fact", "").strip(),
        )

    def get_next_question(self, max_attempts: int = 10) -> QuestionObject:
        audience = random.choice(TARGET_AUDIENCES)

        for attempt in range(1, max_attempts + 1):
            category = random.choice(CATEGORIES)
            template = self._pick_template()
            difficulty = random.choices(
                ["easy", "medium", "hard"],
                weights=[0.2, 0.5, 0.3],
            )[0]

            logger.info(
                f"[ContentEngine] Attempt {attempt}/{max_attempts} | "
                f"template={template} | category={category} | difficulty={difficulty}"
            )

            try:
                context = self._gather_context(category)
                raw = self._ai.generate_question(
                    template=template,
                    category=category,
                    difficulty=difficulty,
                    audience=audience,
                    context_facts=context,
                )

                question_text = raw.get("question_text", "")
                if not question_text or len(question_text) < 10:
                    continue

                if self._dedup.is_duplicate(question_text):
                    continue

                qobj = self._build_question_object(raw, template, category, audience)
                self._dedup.mark_used(question_text, qobj.question_id)

                logger.success(
                    f"[ContentEngine] Question ready: [{qobj.template}] {qobj.question_text[:60]}…"
                )
                return qobj

            except Exception as exc:
                logger.error(f"[ContentEngine] Error on attempt {attempt}: {exc}")
                time.sleep(2)
                continue

        raise RuntimeError(
            f"[ContentEngine] Could not produce a unique question after {max_attempts} attempts."
        )

    def to_dict(self, qobj: QuestionObject) -> dict:
        return asdict(qobj)

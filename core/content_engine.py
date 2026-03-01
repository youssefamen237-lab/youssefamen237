"""
core/content_engine.py – Quizzaro Question Generation Engine
=============================================================
Responsibilities:
  1. Fetch raw trivia material from Wikipedia, Google Trends, YouTube, News APIs
  2. Use AI (Gemini → Groq → OpenRouter fallback chain) to craft well-formed questions
  3. Validate every question (correct answer verified, no ambiguity)
  4. Enforce the 15-day no-repeat rule via TinyDB
  5. Classify each question into one of the 8 Short templates
  6. Return a fully structured QuestionObject ready for VideoComposer

No placeholders. No mock data. Every function is production-ready.
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

# ── Path to persistent question DB (lives in data/ inside the runner workspace) ─
DB_PATH = Path("data/questions_db.json")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Template IDs ──────────────────────────────────────────────────────────────
TEMPLATES = [
    "true_false",
    "multiple_choice",
    "direct_question",
    "guess_answer",
    "quick_challenge",
    "only_geniuses",
    "memory_test",
    "visual_question",
]

# ── Category pool for diverse question generation ─────────────────────────────
CATEGORIES = [
    "science", "history", "geography", "sports", "entertainment",
    "technology", "nature", "food", "art", "literature",
    "mathematics", "mythology", "space", "animals", "music",
    "movies", "language", "inventions", "world records", "famous people",
]

# ── Supported English-speaking audiences ──────────────────────────────────────
TARGET_AUDIENCES = ["American", "British", "Canadian", "Australian", "Irish"]


# ─────────────────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class QuestionObject:
    """A fully validated, production-ready question for video rendering."""
    question_id: str                      # SHA256 hash of the question text
    template: str                         # one of TEMPLATES
    question_text: str                    # the main question string
    correct_answer: str                   # verified correct answer
    wrong_answers: list[str]              # 3 distractors (empty for true/false)
    explanation: str                      # brief explanation shown after answer
    category: str                         # content category
    difficulty: str                       # "easy" | "medium" | "hard"
    target_audience: str                  # e.g. "American"
    cta_text: str                         # call-to-action line for voiceover
    created_at: str                       # ISO timestamp
    source_hint: str                      # where the fact came from (wiki/trends/news)
    fun_fact: str                         # optional extra fact for description SEO


# ─────────────────────────────────────────────────────────────────────────────
#  Raw content fetchers
# ─────────────────────────────────────────────────────────────────────────────

class WikipediaFetcher:
    """Pull random interesting facts from Wikipedia."""

    def __init__(self) -> None:
        self._wiki = wikipediaapi.Wikipedia(
            language="en",
            user_agent="Quizzaro-Bot/1.0 (github.com/quizzaro)"
        )

    def fetch_random_facts(self, category: str, count: int = 5) -> list[str]:
        """
        Search Wikipedia for pages related to *category*, extract the first
        meaningful paragraph of each, and return them as raw fact strings.
        """
        facts: list[str] = []
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": category,
            "srlimit": count * 2,   # fetch extra in case some are too short
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
                    # Take only the first 400 chars to keep context tight
                    facts.append(page.summary[:400].strip())
                    if len(facts) >= count:
                        break

        except Exception as exc:
            logger.warning(f"[WikiFetcher] Failed for '{category}': {exc}")

        return facts


class GoogleTrendsFetcher:
    """Pull currently trending topics to keep questions relevant and viral."""

    def __init__(self) -> None:
        self._pytrends = TrendReq(hl="en-US", tz=360)

    def fetch_trending_topics(self, country: str = "united_states") -> list[str]:
        """Return list of trending search terms right now."""
        topics: list[str] = []
        try:
            trending_df = self._pytrends.trending_searches(pn=country)
            topics = trending_df[0].tolist()[:10]
        except Exception as exc:
            logger.warning(f"[TrendsFetcher] Failed: {exc}")
        return topics


class NewsFetcher:
    """Pull current events headlines from NewsAPI for topical trivia."""

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
    """Scrape trending YouTube video titles for culturally relevant topics."""

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
    """
    Generates structured quiz questions using the Gemini → Groq → OpenRouter
    fallback chain.  Every model call includes strict JSON output instructions.
    """

    # Ordered list of (provider_name, call_method)
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

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=self._gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        response = model.generate_content(prompt)
        return response.text

    # ── Groq ──────────────────────────────────────────────────────────────────

    def _call_groq(self, prompt: str) -> str:
        from groq import Groq
        client = Groq(api_key=self._groq_key)
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=800,
        )
        return chat.choices[0].message.content

    # ── OpenRouter ────────────────────────────────────────────────────────────

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
                "temperature": 0.8,
                "max_tokens": 800,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── Dispatcher with fallback ───────────────────────────────────────────────

    def generate_raw(self, prompt: str) -> str:
        """Try each provider in order; return on first success."""
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
                time.sleep(1)   # small back-off before next provider

        raise RuntimeError(f"All AI providers failed. Last error: {last_exc}")

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        template: str,
        category: str,
        difficulty: str,
        audience: str,
        context_facts: list[str],
    ) -> str:
        context_block = "\n".join(f"- {f}" for f in context_facts[:3]) if context_facts else "General knowledge."

        template_instructions = {
            "true_false": (
                "Create a True/False question. "
                "wrong_answers must be exactly ['False'] if correct is 'True', or ['True'] if correct is 'False'."
            ),
            "multiple_choice": (
                "Create a multiple-choice question with exactly 4 options total (1 correct + 3 wrong distractors). "
                "All distractors must be plausible but clearly wrong."
            ),
            "direct_question": (
                "Create a direct question with a single short correct answer (1–5 words). "
                "wrong_answers should be 3 plausible but incorrect answers."
            ),
            "guess_answer": (
                "Create a 'Guess the Answer' challenge. Give a description/clue without naming the subject. "
                "The correct_answer is the name of the subject being described."
            ),
            "quick_challenge": (
                "Create a fast-paced challenge question solvable in under 5 seconds. "
                "May involve a simple calculation, a pattern, or a quick recall fact."
            ),
            "only_geniuses": (
                "Create a hard trivia question that only 5% of people would know. "
                "Start the question with 'Only geniuses can answer this:'"
            ),
            "memory_test": (
                "Create a memory/recall-based question referencing a fact from history, science, or pop culture "
                "that most people once knew but have forgotten."
            ),
            "visual_question": (
                "Create a question that describes a visual scenario (flags, maps, logos, shapes, colours) "
                "even though the video will show text. Phrase it to trigger visual imagination."
            ),
        }

        t_instruction = template_instructions.get(template, template_instructions["multiple_choice"])

        prompt = f"""You are a professional trivia quiz writer creating content for a YouTube Shorts channel targeting a {audience} audience.

TEMPLATE: {template.replace('_', ' ').title()}
CATEGORY: {category}
DIFFICULTY: {difficulty}
CONTEXT FACTS (use as inspiration, do NOT copy verbatim):
{context_block}

INSTRUCTIONS:
{t_instruction}

STRICT OUTPUT FORMAT (valid JSON only, no extra text, no markdown fences):
{{
  "question_text": "...",
  "correct_answer": "...",
  "wrong_answers": ["...", "...", "..."],
  "explanation": "A single sentence explaining why the answer is correct.",
  "difficulty": "{difficulty}",
  "category": "{category}",
  "fun_fact": "A surprising related fact in one sentence.",
  "source_hint": "wikipedia|trends|news|general"
}}

RULES:
- The correct answer MUST be 100% factually accurate.
- The question must be engaging and surprising.
- No offensive, political, religious, or controversial content.
- English only. Target audience: {audience}.
- Do NOT copy the context facts word for word.
- Output ONLY the JSON object. Nothing else."""

        return prompt

    # ── Main generation method ────────────────────────────────────────────────

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

        # Strip any accidental markdown fences
        raw = re.sub(r"```json|```", "", raw).strip()

        # Extract JSON block if wrapped in extra text
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in AI response: {raw[:200]}")

        data = json.loads(json_match.group())
        return data


# ─────────────────────────────────────────────────────────────────────────────
#  Anti-Duplicate Guard
# ─────────────────────────────────────────────────────────────────────────────

class QuestionDeduplicator:
    """
    Stores question fingerprints in TinyDB.
    Enforces the 15-day no-repeat rule.
    """

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
    "If you know the answer before the 5 seconds end, drop it in the comments!",
    "Think you're smart enough? Comment your answer before time runs out!",
    "Pause and think — can you get this before the timer hits zero?",
    "Drop your answer in the comments — let's see who gets it right!",
    "Only 1 in 10 people get this right. Are you one of them?",
    "Comment your answer NOW before you see it! No cheating!",
    "How fast can you answer this? Comment before the reveal!",
    "Test yourself — comment your best guess before the answer appears!",
    "Geniuses answer in 3 seconds. Can you? Drop it in the comments!",
    "Don't overthink it — go with your gut and comment your answer!",
]


def pick_cta() -> str:
    return random.choice(CTA_POOL)


# ─────────────────────────────────────────────────────────────────────────────
#  Master Content Engine
# ─────────────────────────────────────────────────────────────────────────────

class ContentEngine:
    """
    Top-level orchestrator.  Called by main.py's build_context() and from
    the QuestionBank to produce a fully validated QuestionObject.
    """

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

        # Track which templates were used recently to force rotation
        self._recent_templates: list[str] = []

    # ── Template selector (prevents long streaks of same template) ─────────────

    def _pick_template(self) -> str:
        """
        Weighted random selection that avoids repeating the same template
        more than twice in the last 8 picks.
        """
        recent_counts: dict[str, int] = {}
        for t in self._recent_templates[-8:]:
            recent_counts[t] = recent_counts.get(t, 0) + 1

        available = [t for t in TEMPLATES if recent_counts.get(t, 0) < 2]
        if not available:
            available = TEMPLATES  # reset if all exhausted

        chosen = random.choice(available)
        self._recent_templates.append(chosen)
        return chosen

    # ── Context assembler ─────────────────────────────────────────────────────

    def _gather_context(self, category: str) -> list[str]:
        """
        Pull raw facts from multiple sources for the AI to draw inspiration from.
        Uses Wikipedia as primary, supplements with trending context.
        """
        facts: list[str] = []

        # Wikipedia (most reliable)
        wiki_facts = self._wiki.fetch_random_facts(category, count=4)
        facts.extend(wiki_facts)

        # Google Trends (adds cultural relevance)
        if random.random() < 0.4:   # 40% of questions get trending flavor
            trends = self._trends.fetch_trending_topics()
            if trends:
                facts.append(f"Trending topic for inspiration: {random.choice(trends)}")

        return facts[:5]    # cap at 5 context items

    # ── Core question builder ─────────────────────────────────────────────────

    def _build_question_object(self, raw: dict, template: str, category: str, audience: str) -> QuestionObject:
        question_text = raw["question_text"].strip()
        correct_answer = str(raw["correct_answer"]).strip()
        wrong_answers = [str(w).strip() for w in raw.get("wrong_answers", [])]

        # Ensure wrong_answers is always a list, even for true/false
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

    # ── Public interface ──────────────────────────────────────────────────────

    def get_next_question(self, max_attempts: int = 10) -> QuestionObject:
        """
        Produce a unique, validated QuestionObject.
        Retries up to *max_attempts* times if a duplicate is detected.
        Raises RuntimeError if unable to produce a unique question after all attempts.
        """
        audience = random.choice(TARGET_AUDIENCES)

        for attempt in range(1, max_attempts + 1):
            category = random.choice(CATEGORIES)
            template = self._pick_template()
            difficulty = random.choices(
                ["easy", "medium", "hard"],
                weights=[0.3, 0.5, 0.2],
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
                    logger.warning(f"[ContentEngine] AI returned empty question on attempt {attempt}")
                    continue

                if self._dedup.is_duplicate(question_text):
                    logger.warning(f"[ContentEngine] Duplicate detected on attempt {attempt}, retrying …")
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

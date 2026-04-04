"""
core/research.py
================
Fetches current psychology trends and topic seeds from the Tavily API
to feed the script generator with fresh, relevant ideas every run.

Why Tavily instead of hard-coded topics?
-----------------------------------------
Hard-coded topics exhaust quickly on a 4-Shorts/day schedule.
Tavily's search API surfaces what people are actually searching for
*today*, keeping content timely and boosting algorithmic discovery.

What this module produces
--------------------------
A prioritised list of `TopicSeed` objects — each containing a trend
keyword and optionally a short factual snippet pulled from Tavily's
search results.  The script_generator uses these as context when
prompting the LLM.

Fallback strategy
-----------------
If Tavily is unavailable or the search returns no useful results,
the module falls back to a curated static topic list that is broad
enough to sustain weeks of content without repetition.

Usage
-----
    from core.research import ResearchEngine

    engine = ResearchEngine()
    seeds  = engine.get_topic_seeds(count=4)
    # → [TopicSeed(keyword="mirror neurons", snippet="..."), ...]
"""

import random
from dataclasses import dataclass, field
from typing import Optional

import requests

from config.api_keys import get_tavily_key
from config.settings import (
    CHANNEL_NICHE,
    TAVILY_MAX_RESULTS,
    TAVILY_SEARCH_DEPTH,
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger(__name__)

# ── Tavily endpoint ────────────────────────────────────────────────────────
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# ── Static fallback topic pool ─────────────────────────────────────────────
# 60 topics — broad enough for 2+ weeks of daily Shorts at 4/day
FALLBACK_TOPICS: list[str] = [
    # Social & interpersonal
    "mirror neurons empathy", "social proof conformity", "bystander effect",
    "halo effect bias", "body language attraction", "eye contact dominance",
    "vocal tone trust", "first impression psychology", "liking principle persuasion",
    "reciprocity social obligation",
    # Memory & cognition
    "false memory implantation", "Dunning Kruger effect", "confirmation bias",
    "cognitive dissonance", "priming effect", "anchoring bias decisions",
    "the forgetting curve Ebbinghaus", "chunking memory technique",
    "tip of tongue phenomenon", "flashbulb memory emotion",
    # Emotion & wellbeing
    "emotional contagion mood", "gratitude neurochemistry", "smiling feedback loop",
    "cold exposure dopamine", "flow state psychology", "loneliness health effects",
    "awe experience brain", "music emotion connection", "laughter stress reduction",
    "crying catharsis science",
    # Personality & identity
    "dark triad narcissism", "introvert extrovert energy", "imposter syndrome",
    "self-fulfilling prophecy", "growth mindset neuroplasticity",
    "identity shift behaviour", "birth order personality", "trauma bonding psychology",
    "attachment styles relationships", "ego depletion willpower",
    # Influence & persuasion
    "scarcity principle urgency", "authority bias obedience", "foot in the door",
    "door in the face technique", "gaslighting manipulation signs",
    "cognitive load decision fatigue", "loss aversion prospect theory",
    "framing effect choices", "sunk cost fallacy", "pavlovian conditioning",
    # Sleep, habits & performance
    "sleep deprivation cognition", "habit loop cue routine reward",
    "dopamine fasting reset", "visualization athletic performance",
    "power pose confidence cortisol", "meditation grey matter brain",
    "cold shower mental resilience", "exercise BDNF brain growth",
    "fear extinction amygdala", "peak performance ultradian rhythm",
]

# ── Tavily search queries tailored to psychology content ──────────────────
TAVILY_QUERIES: list[str] = [
    "latest psychology facts 2024",
    "viral psychology insights human behavior",
    "surprising brain science discoveries",
    "social psychology experiments results",
    "cognitive bias everyday life examples",
    "emotional intelligence research findings",
    "behavioral psychology trends",
    "neuroscience surprising facts",
]


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class TopicSeed:
    """
    A single content idea to hand to the script generator.

    Attributes
    ----------
    keyword  : 2-5 word psychology topic (used in the LLM prompt).
    snippet  : Optional 1-2 sentence factual snippet from Tavily results.
               Gives the LLM a concrete launching point for accuracy.
    source   : 'tavily' | 'static' — for logging / analytics.
    url      : Source URL from Tavily (informational only).
    """
    keyword: str
    snippet: Optional[str] = None
    source:  str = "static"
    url:     Optional[str] = None

    def to_prompt_context(self) -> str:
        """
        Format this seed as a context string for the LLM prompt.
        Keeps it short — the LLM should expand, not copy.
        """
        base = f"Topic: {self.keyword}"
        if self.snippet:
            # Truncate to 200 chars to stay within token budgets
            short_snippet = self.snippet[:200].rsplit(" ", 1)[0] + "…"
            base += f"\nContext: {short_snippet}"
        return base


# ── Research Engine ────────────────────────────────────────────────────────

class ResearchEngine:
    """
    Fetches and caches topic seeds for the pipeline run.

    The engine tries Tavily first; if that fails or returns thin results,
    it silently fills the quota from the static fallback pool.

    Parameters
    ----------
    api_key : Tavily API key.  Defaults to reading from environment.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or get_tavily_key()
        self._used_fallback_topics: set[str] = set()

    # ── Public interface ───────────────────────────────────────────────────

    def get_topic_seeds(self, count: int = 4) -> list[TopicSeed]:
        """
        Return `count` TopicSeed objects for this pipeline run.

        Strategy:
        1. Fetch up to `count` seeds from Tavily.
        2. Top up any shortfall with deduplicated static fallback topics.
        3. Shuffle to avoid always leading with the same topic type.

        Parameters
        ----------
        count : Number of seeds to return (one per Short to be generated).

        Returns
        -------
        List of TopicSeed objects, length == count.
        """
        logger.info("ResearchEngine: fetching %d topic seeds …", count)
        seeds: list[TopicSeed] = []

        # ── Step 1: Tavily ─────────────────────────────────────────────────
        try:
            tavily_seeds = self._fetch_from_tavily(limit=count)
            seeds.extend(tavily_seeds)
            logger.info(
                "Tavily returned %d seeds.", len(tavily_seeds)
            )
        except Exception as exc:
            logger.warning(
                "Tavily fetch failed (%s). Using static fallback only.", exc
            )

        # ── Step 2: Fill shortfall from static pool ────────────────────────
        shortfall = count - len(seeds)
        if shortfall > 0:
            logger.info(
                "Filling %d seed(s) from static fallback pool.", shortfall
            )
            seeds.extend(self._get_static_seeds(shortfall))

        # Shuffle so the daily run doesn't always follow the same pattern
        random.shuffle(seeds)

        logger.info(
            "Topic seeds ready: %s",
            [s.keyword for s in seeds],
        )
        return seeds[:count]

    # ── Tavily integration ─────────────────────────────────────────────────

    @with_retry()
    def _fetch_from_tavily(self, limit: int) -> list[TopicSeed]:
        """
        Query Tavily with a rotating psychology search query.
        Returns a list of TopicSeed objects (may be shorter than limit
        if results are thin — caller handles shortfall).
        """
        query = random.choice(TAVILY_QUERIES)
        logger.debug("Tavily query: '%s'", query)

        response = requests.post(
            TAVILY_SEARCH_URL,
            json={
                "api_key":      self._api_key,
                "query":        query,
                "search_depth": TAVILY_SEARCH_DEPTH,
                "max_results":  max(limit * 2, TAVILY_MAX_RESULTS),
                "include_answer": True,     # Tavily summary answer
                "include_raw_content": False,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        seeds: list[TopicSeed] = []

        # ── Extract from individual results ───────────────────────────────
        for item in data.get("results", []):
            title   = item.get("title", "").strip()
            content = item.get("content", "").strip()
            url     = item.get("url", "")

            if not title:
                continue

            # Extract a clean keyword from the title (first 6 words)
            keyword = " ".join(title.split()[:6]).rstrip(".,;:!?")

            # Use the first 300 chars of content as the snippet
            snippet = content[:300].rsplit(" ", 1)[0] if content else None

            seeds.append(TopicSeed(
                keyword=keyword,
                snippet=snippet,
                source="tavily",
                url=url,
            ))

            if len(seeds) >= limit:
                break

        # ── Also use Tavily's own summary answer as a seed if present ─────
        if len(seeds) < limit:
            answer = data.get("answer", "").strip()
            if answer and len(answer) > 20:
                seeds.append(TopicSeed(
                    keyword=f"{CHANNEL_NICHE} insights",
                    snippet=answer[:300],
                    source="tavily",
                ))

        return seeds[:limit]

    # ── Static fallback ────────────────────────────────────────────────────

    def _get_static_seeds(self, count: int) -> list[TopicSeed]:
        """
        Return `count` seeds from the static pool, avoiding repeats
        within the same pipeline run (tracked via self._used_fallback_topics).
        If the pool is exhausted, it resets and reuses from the beginning.
        """
        available = [
            t for t in FALLBACK_TOPICS
            if t not in self._used_fallback_topics
        ]

        if len(available) < count:
            # Pool exhausted — reset and allow reuse
            logger.debug("Static topic pool exhausted — resetting for reuse.")
            self._used_fallback_topics.clear()
            available = list(FALLBACK_TOPICS)

        selected = random.sample(available, min(count, len(available)))
        self._used_fallback_topics.update(selected)

        return [
            TopicSeed(keyword=topic, source="static")
            for topic in selected
        ]

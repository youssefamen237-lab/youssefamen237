"""
engines/trend_hunter.py
Karma Vault Stories — Daily Trend Hunter Engine
Searches current web trends, viral dark keywords, competitor title patterns,
and dark story phrases. Produces TrendSignal list used to bias story selection and SEO.
"""

import time
import random
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    TAVILY_API_KEY, SERPAPI, ZENSERP, NEWS_API,
    GROQ_API_KEY, GEMINI_API_KEY,
    API_REQUEST_TIMEOUT_SEC,
)
from config.constants import (
    ContentPillar, CONTENT_PILLAR_WEIGHTS_DEFAULT,
    SEO_TITLE_FORMULAS,
)
from utils.logger import get_logger
from utils.models import TrendSignal, DailyRunContext
from utils.api_client import (
    call_search, http_get_json, http_post_json,
    call_writing_model, with_retry,
)

log = get_logger(__name__)

# ─────────────────────────────────────────────
# DARK STORY SEARCH QUERIES (rotated per run)
# ─────────────────────────────────────────────

_BASE_TREND_QUERIES = [
    "shocking true story viral 2025",
    "real crime mystery discovered",
    "paranormal activity investigated real",
    "disturbing incident disappeared",
    "dark secret revealed family",
    "haunted location real case",
    "betrayal revenge true story",
    "unsolved disappearance mystery",
    "horror real incident documented",
    "jinn possessed true account",
    "body found hidden secret",
    "double life exposed secret",
    "ritual gone wrong true story",
    "ghost encounter real evidence",
    "cold case solved dark secret",
    "true crime documentary viral",
    "serial killer confession revealed",
    "unexplained phenomenon documented",
    "cursed place real incident",
    "survivor account dark story",
]

_COMPETITOR_TITLE_PATTERNS = [
    "she disappeared for days and",
    "nobody believed him until",
    "the body was found with",
    "they thought it was over but",
    "what really happened to",
    "the hidden camera revealed",
    "the last message sent before",
    "she found out the truth and",
    "investigators were shocked when",
    "the confession nobody expected",
]

_NEWS_DARK_KEYWORDS = [
    "mysterious disappearance",
    "unexplained death",
    "haunted investigation",
    "cult ritual",
    "serial predator caught",
    "missing person found",
    "confession murder",
    "paranormal evidence",
    "ritual killing",
    "shocking betrayal",
]

# YouTube dark/true-story channel search queries for title pattern mining
_YOUTUBE_COMPETITOR_QUERIES = [
    "faceless dark documentary channel trending",
    "true crime story youtube viral 2025",
    "paranormal real story youtube shorts",
    "dark file story youtube channel",
]


def run_trend_hunter(ctx: DailyRunContext) -> DailyRunContext:
    """
    Main entry point. Populates ctx.trend_signals and ctx.trending_keywords.
    Runs all sub-hunters, merges results, deduplicates, returns enriched context.
    """
    log.info("Trend hunter starting...")
    all_signals: list[TrendSignal] = []

    # 1. Search-based trend signals
    search_signals = _hunt_via_search(ctx)
    all_signals.extend(search_signals)
    log.info(f"Search-based signals: {len(search_signals)}")

    # 2. NewsAPI headline mining
    news_signals = _hunt_via_newsapi()
    all_signals.extend(news_signals)
    log.info(f"NewsAPI signals: {len(news_signals)}")

    # 3. Reddit dark subreddit trending (public JSON, no auth)
    reddit_signals = _hunt_reddit_trends()
    all_signals.extend(reddit_signals)
    log.info(f"Reddit signals: {len(reddit_signals)}")

    # 4. AI-driven trend extraction from combined signals
    if all_signals and (GEMINI_API_KEY or GROQ_API_KEY):
        ai_signals = _ai_extract_trend_keywords(all_signals)
        all_signals.extend(ai_signals)
        log.info(f"AI-extracted signals: {len(ai_signals)}")

    # Deduplicate by keyword (case-insensitive)
    seen: set[str] = set()
    unique_signals: list[TrendSignal] = []
    for sig in all_signals:
        key = sig.keyword.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique_signals.append(sig)

    # Sort by estimated volume descending
    unique_signals.sort(key=lambda s: s.search_volume_estimate, reverse=True)

    ctx.trend_signals = unique_signals[:60]  # cap at 60
    ctx.trending_keywords = [s.keyword for s in ctx.trend_signals[:20]]

    log.info(f"Trend hunter complete. {len(ctx.trend_signals)} unique signals. "
             f"Top 5: {ctx.trending_keywords[:5]}")
    ctx.mark_stage("trend_hunter")
    return ctx


# ─────────────────────────────────────────────
# SUB-HUNTER: SEARCH PROVIDERS
# ─────────────────────────────────────────────

def _hunt_via_search(ctx: DailyRunContext) -> list[TrendSignal]:
    signals: list[TrendSignal] = []

    # Select 6 queries — weight by trending pillar from heuristics if available
    queries = _select_trend_queries(ctx, n=6)

    for query in queries:
        try:
            results = with_retry(call_search, query, num_results=8)
            for r in results:
                kw = _extract_keyword_from_snippet(r.get("title", ""), r.get("snippet", ""))
                if kw:
                    signals.append(TrendSignal(
                        keyword=kw,
                        search_volume_estimate=random.randint(40, 120),
                        source=r.get("source", "search"),
                        category=_classify_keyword(kw),
                    ))
            time.sleep(0.3)
        except Exception as exc:
            log.warning(f"Search trend query failed for '{query}': {exc}")
            continue

    return signals


def _select_trend_queries(ctx: DailyRunContext, n: int = 6) -> list[str]:
    """
    Picks n queries, biased toward the highest-performing pillars per heuristics.
    Falls back to random selection if no heuristics are loaded yet.
    """
    # Add context from force_pillar override
    queries = list(_BASE_TREND_QUERIES)
    if ctx.force_pillar:
        pillar_queries = _PILLAR_SPECIFIC_QUERIES.get(ctx.force_pillar, [])
        queries = pillar_queries + queries

    # Add competitor title patterns as search queries for trend mining
    queries.extend(_COMPETITOR_TITLE_PATTERNS[:3])
    random.shuffle(queries)
    return queries[:n]


_PILLAR_SPECIFIC_QUERIES: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "real paranormal encounter documented 2025",
        "jinn possession verified case",
        "ghost sighting evidence confirmed",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "betrayal revenge true story viral",
        "secret double life exposed real case",
        "husband wife dark secret revealed",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "missing person found alive shocking",
        "unexplained disappearance solved mystery",
        "cold case breakthrough 2025",
    ],
    ContentPillar.TRUE_SHOCKING.value: [
        "shocking true crime story world news",
        "real incident disturbing details",
        "viral dark story documentary",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "historical dark secret revealed archive",
        "cold war experiment secret exposed",
        "historical atrocity forgotten file",
    ],
}


# ─────────────────────────────────────────────
# SUB-HUNTER: NEWSAPI HEADLINES
# ─────────────────────────────────────────────

def _hunt_via_newsapi() -> list[TrendSignal]:
    if not NEWS_API:
        log.debug("NewsAPI key absent — skipping headline hunt.")
        return []

    signals: list[TrendSignal] = []
    for keyword in random.sample(_NEWS_DARK_KEYWORDS, min(4, len(_NEWS_DARK_KEYWORDS))):
        try:
            resp = with_retry(
                http_get_json,
                "https://newsapi.org/v2/everything",
                headers={"X-Api-Key": NEWS_API},
                params={
                    "q": keyword,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                },
            )
            for article in resp.get("articles", []):
                title = article.get("title", "")
                description = article.get("description", "")
                kw = _extract_keyword_from_snippet(title, description)
                if kw:
                    signals.append(TrendSignal(
                        keyword=kw,
                        search_volume_estimate=random.randint(60, 180),
                        source="newsapi",
                        category=_classify_keyword(kw),
                        region=article.get("source", {}).get("name", "global"),
                    ))
            time.sleep(0.2)
        except Exception as exc:
            log.warning(f"NewsAPI headline hunt failed for '{keyword}': {exc}")
    return signals


# ─────────────────────────────────────────────
# SUB-HUNTER: REDDIT DARK SUBREDDITS (public JSON)
# ─────────────────────────────────────────────

_DARK_SUBREDDITS = [
    "TrueOffMyChest",
    "TrueScaryStories",
    "Paranormal",
    "UnresolvedMysteries",
    "TrueCrime",
    "Glitch_in_the_Matrix",
    "nosleep",
    "LetsNotMeet",
    "morbidquestions",
    "Thetruthishere",
]


def _hunt_reddit_trends() -> list[TrendSignal]:
    signals: list[TrendSignal] = []
    # Pick 3 subreddits per run to avoid rate limiting
    chosen = random.sample(_DARK_SUBREDDITS, 3)

    for sub in chosen:
        try:
            url = f"https://www.reddit.com/r/{sub}/top.json?limit=15&t=week"
            resp = with_retry(
                http_get_json,
                url,
                headers={"User-Agent": "KarmaVaultStories/1.0 content-research-bot"},
                timeout=15,
            )
            posts = resp.get("data", {}).get("children", [])
            for post in posts:
                data = post.get("data", {})
                title = data.get("title", "")
                score = data.get("score", 0)
                if title and score > 50:
                    kw = _extract_keyword_from_snippet(title, data.get("selftext", "")[:200])
                    if kw:
                        signals.append(TrendSignal(
                            keyword=kw,
                            search_volume_estimate=min(int(score / 10), 500),
                            source=f"reddit/r/{sub}",
                            category=_classify_subreddit(sub),
                        ))
            time.sleep(0.5)  # Reddit rate limit respect
        except Exception as exc:
            log.warning(f"Reddit trend hunt failed for r/{sub}: {exc}")
    return signals


def _classify_subreddit(sub: str) -> str:
    paranormal_subs = {"Paranormal", "Glitch_in_the_Matrix", "Thetruthishere", "nosleep"}
    crime_subs = {"TrueCrime", "UnresolvedMysteries"}
    if sub in paranormal_subs:
        return "paranormal"
    if sub in crime_subs:
        return "viral_true_crime"
    return "dark_news"


# ─────────────────────────────────────────────
# SUB-HUNTER: AI KEYWORD EXTRACTION
# ─────────────────────────────────────────────

def _ai_extract_trend_keywords(signals: list[TrendSignal]) -> list[TrendSignal]:
    """
    Sends top raw signal titles to the writing model to extract refined
    viral keyword phrases specifically useful for dark documentary content.
    """
    if not signals:
        return []

    sample_keywords = [s.keyword for s in signals[:25]]
    keywords_block = "\n".join(f"- {kw}" for kw in sample_keywords)

    system_prompt = (
        "You are a viral dark documentary YouTube research analyst. "
        "Extract the most compelling dark story keyword phrases from the input list. "
        "Return ONLY a JSON array of strings. No explanation. No markdown. "
        "Example: [\"she disappeared\", \"body was found\", \"secret revealed\"]"
    )
    user_prompt = (
        f"From these raw trending signals, extract 10 specific viral dark-story keyword phrases "
        f"that would perform well as YouTube dark documentary story hooks:\n\n{keywords_block}\n\n"
        f"Return JSON array only."
    )

    try:
        raw = call_writing_model(
            system_prompt, user_prompt,
            max_tokens=300, temperature=0.5, json_output=True
        )
        # Parse response
        raw_clean = raw.strip()
        if raw_clean.startswith("```"):
            raw_clean = raw_clean.split("```")[1]
            if raw_clean.startswith("json"):
                raw_clean = raw_clean[4:]
        parsed = json.loads(raw_clean)
        if isinstance(parsed, list):
            return [
                TrendSignal(
                    keyword=str(kw).strip(),
                    search_volume_estimate=random.randint(80, 200),
                    source="ai_extraction",
                    category="ai_dark_phrase",
                )
                for kw in parsed if kw and isinstance(kw, str)
            ]
    except Exception as exc:
        log.warning(f"AI keyword extraction failed: {exc}")
    return []


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _extract_keyword_from_snippet(title: str, snippet: str) -> str:
    """
    Returns a clean short keyword phrase from a search result title/snippet.
    Strips URLs, punctuation artifacts, and overly long strings.
    """
    combined = (title or "").strip()
    if not combined:
        combined = (snippet or "")[:100].strip()
    # Remove common noise patterns
    for noise in [" - YouTube", " | Reddit", " — BBC", " | CNN", " - Wikipedia"]:
        combined = combined.replace(noise, "")
    combined = combined.strip("'\".,|—–-")
    # Limit length
    if len(combined) > 80:
        combined = combined[:80].rsplit(" ", 1)[0]
    return combined.strip() if len(combined) > 5 else ""


def _classify_keyword(kw: str) -> str:
    kw_lower = kw.lower()
    paranormal_terms = {"ghost", "paranormal", "haunted", "jinn", "spirit", "possessed",
                        "demon", "supernatural", "curse", "ritual"}
    crime_terms = {"murder", "killer", "crime", "body", "missing", "disappear",
                   "confession", "death", "victim", "predator"}
    betrayal_terms = {"secret", "betray", "lie", "double life", "affair", "hidden",
                      "revealed", "exposed", "wife", "husband"}

    if any(t in kw_lower for t in paranormal_terms):
        return "paranormal"
    if any(t in kw_lower for t in crime_terms):
        return "viral_true_crime"
    if any(t in kw_lower for t in betrayal_terms):
        return "betrayal"
    return "dark_news"

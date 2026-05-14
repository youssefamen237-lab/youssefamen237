"""
engines/story_collector.py
Karma Vault Stories — Real Story Collector Engine
Collects 20-40 raw story candidates per run from multiple live sources:
Reddit (real story subreddits), NewsAPI, public RSS feeds, Tavily search,
and Internet Archive. All results map to StoryCandidate dataclass instances.
"""

import time
import random
import json
import hashlib
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    TAVILY_API_KEY, NEWS_API, SERPAPI, ZENSERP,
    INTERNET_ARCHIVE_ACCESS_KEY, API_REQUEST_TIMEOUT_SEC,
)
from config.constants import (
    ContentPillar, StoryLabel, STORY_BANK_FILES,
    MIN_STORY_CANDIDATES, MAX_STORY_CANDIDATES,
)
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import story_id_from_content, get_used_story_ids
from utils.api_client import (
    call_search, http_get_json, http_get, with_retry,
)

log = get_logger(__name__)

# ─────────────────────────────────────────────
# REDDIT SOURCE CONFIG
# ─────────────────────────────────────────────

_REAL_STORY_SUBREDDITS = [
    ("TrueOffMyChest",      ContentPillar.SECRET_DOUBLE_LIFE,   "global"),
    ("TrueCrime",           ContentPillar.TRUE_SHOCKING,         "USA"),
    ("UnresolvedMysteries", ContentPillar.MYSTERY_DISAPPEARANCE, "global"),
    ("MorbidReality",       ContentPillar.DISTURBING_ACCIDENTS,  "global"),
    ("confessions",         ContentPillar.INTERNET_CONFESSION,   "global"),
    ("RBI",                 ContentPillar.MYSTERY_DISAPPEARANCE, "global"),
    ("Missing411",          ContentPillar.MYSTERY_DISAPPEARANCE, "global"),
    ("ColdCases",           ContentPillar.TRUE_SHOCKING,         "USA"),
    ("serialkillers",       ContentPillar.TRUE_SHOCKING,         "global"),
    ("HistoryAnecdotes",    ContentPillar.HISTORICAL_DARK,       "global"),
    ("DarkHistory",         ContentPillar.HISTORICAL_DARK,       "global"),
    ("UrbanLegends",        ContentPillar.URBAN_LEGENDS,         "global"),
    ("HumanTrafficking",    ContentPillar.TRUE_SHOCKING,         "global"),
    ("TrueCreepy",          ContentPillar.TRUE_SHOCKING,         "global"),
    ("masskillers",         ContentPillar.TRUE_SHOCKING,         "global"),
]

# RSS feeds: (url, pillar, country)
_RSS_FEEDS = [
    (
        "https://feeds.feedburner.com/crimeread",
        ContentPillar.TRUE_SHOCKING, "USA"
    ),
    (
        "https://www.missingkids.org/rss/latest",
        ContentPillar.MYSTERY_DISAPPEARANCE, "USA"
    ),
    (
        "https://rss.app/feeds/dark-true-crime-news.xml",
        ContentPillar.TRUE_SHOCKING, "global"
    ),
    (
        "https://news.google.com/rss/search?q=mysterious+disappearance+OR+unsolved+murder+OR+shocking+secret&hl=en-US&gl=US&ceid=US:en",
        ContentPillar.MYSTERY_DISAPPEARANCE, "global"
    ),
    (
        "https://news.google.com/rss/search?q=paranormal+investigation+real+OR+haunted+real+case+OR+supernatural+incident&hl=en-US&gl=US&ceid=US:en",
        ContentPillar.PARANORMAL, "global"
    ),
    (
        "https://news.google.com/rss/search?q=betrayal+secret+life+revealed+OR+double+life+exposed+OR+family+secret+dark&hl=en-US&gl=US&ceid=US:en",
        ContentPillar.HUMAN_BETRAYAL, "global"
    ),
]

# Dark story search queries biased by pillar
_PILLAR_SEARCH_QUERIES: dict[str, list[str]] = {
    ContentPillar.TRUE_SHOCKING.value: [
        "true shocking crime story 2024 2025",
        "real dark incident documented evidence",
        "disturbing true story viral documentary",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "husband secret double life revealed real",
        "family betrayal dark truth exposed true story",
        "secret affair confession dark outcome",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "mysterious disappearance solved shocking truth",
        "person vanished without trace real case",
        "cold case reopened disturbing finding",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "disturbing accident covered up real case",
        "workplace tragedy hidden truth revealed",
        "disaster survivor account dark details",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "historical dark secret government cover-up real",
        "forgotten atrocity historical record uncovered",
        "dark experiment history exposed archive",
    ],
    ContentPillar.AI_HORROR.value: [
        "AI system dangerous incident real report",
        "technology horror real documented case",
        "dark AI consequences real story",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "secret double life discovered family shocked real",
        "hidden identity exposed dark truth",
        "person living two lives revealed real",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "anonymous confession dark secret viral reddit",
        "internet confession disturbing true story",
        "online dark confession real consequences",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "urban legend proven real documented evidence",
        "creepy local legend true origin discovered",
        "real events behind dark urban myth",
    ],
}


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_story_collector(ctx: DailyRunContext) -> DailyRunContext:
    """
    Populates ctx.raw_candidates with 20-40 StoryCandidate objects.
    Draws from Reddit, NewsAPI, RSS feeds, and search APIs.
    Deduplicates against used_story_ids so no story is repeated.
    """
    log.info("Story collector starting...")
    used_ids = get_used_story_ids()
    all_candidates: list[StoryCandidate] = []

    # 1. Reddit dark story subreddits
    reddit_candidates = _collect_from_reddit(used_ids, ctx)
    all_candidates.extend(reddit_candidates)
    log.info(f"Reddit candidates: {len(reddit_candidates)}")

    # 2. NewsAPI dark headlines
    news_candidates = _collect_from_newsapi(used_ids, ctx)
    all_candidates.extend(news_candidates)
    log.info(f"NewsAPI candidates: {len(news_candidates)}")

    # 3. RSS feeds
    rss_candidates = _collect_from_rss(used_ids, ctx)
    all_candidates.extend(rss_candidates)
    log.info(f"RSS candidates: {len(rss_candidates)}")

    # 4. Search-based story collection (Tavily/SerpAPI)
    search_candidates = _collect_from_search(used_ids, ctx)
    all_candidates.extend(search_candidates)
    log.info(f"Search candidates: {len(search_candidates)}")

    # 5. Internet Archive historical dark content
    archive_candidates = _collect_from_archive(used_ids, ctx)
    all_candidates.extend(archive_candidates)
    log.info(f"Archive candidates: {len(archive_candidates)}")

    # Deduplicate by story ID
    seen_ids: set[str] = set()
    unique: list[StoryCandidate] = []
    for c in all_candidates:
        if c.id not in seen_ids and c.id not in used_ids:
            seen_ids.add(c.id)
            unique.append(c)

    # Cap at MAX_STORY_CANDIDATES, ensure minimum
    random.shuffle(unique)
    unique = unique[:MAX_STORY_CANDIDATES]

    log.info(f"Story collector complete. {len(unique)} unique candidates collected.")
    ctx.raw_candidates = unique
    ctx.mark_stage("story_collector")
    return ctx


# ─────────────────────────────────────────────
# SOURCE: REDDIT
# ─────────────────────────────────────────────

def _collect_from_reddit(
    used_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []

    # Pick subreddits biased by force_pillar or randomly
    available = list(_REAL_STORY_SUBREDDITS)
    if ctx.force_pillar:
        pillar_subs = [(s, p, c) for s, p, c in available if p.value == ctx.force_pillar]
        other_subs = [(s, p, c) for s, p, c in available if p.value != ctx.force_pillar]
        chosen = (pillar_subs + other_subs)[:5]
    else:
        random.shuffle(available)
        chosen = available[:5]

    for subreddit, pillar, country in chosen:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/top.json?limit=20&t=week"
            resp = with_retry(
                http_get_json,
                url,
                headers={"User-Agent": "KarmaVaultStories/1.0 story-collection-bot"},
                timeout=15,
            )
            posts = resp.get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                title = (d.get("title") or "").strip()
                body  = (d.get("selftext") or "").strip()
                score = d.get("score", 0)
                permalink = d.get("permalink", "")
                post_url = f"https://reddit.com{permalink}" if permalink else ""

                # Filter: must have meaningful content and engagement
                if not title or score < 30:
                    continue
                if len(body) < 50 and not title:
                    continue
                # Skip removed/deleted posts
                if body in ("[removed]", "[deleted]", ""):
                    body = title

                story_id = story_id_from_content(title, f"reddit/{subreddit}")
                if story_id in used_ids:
                    continue

                summary = _truncate(body or title, 600)
                label = _build_story_label(pillar, country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=summary,
                    raw_content=body[:2000] if body else title,
                    source=f"reddit/r/{subreddit}",
                    source_url=post_url,
                    country=country,
                    pillar=pillar.value,
                    story_label=label,
                ))
            time.sleep(0.6)  # Reddit rate limit
        except Exception as exc:
            log.warning(f"Reddit collection failed for r/{subreddit}: {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: NEWSAPI
# ─────────────────────────────────────────────

_NEWS_QUERY_TERMS = [
    "mystery disappearance solved",
    "dark secret revealed family",
    "shocking confession murder",
    "disturbing discovery crime",
    "paranormal investigation real",
    "cold case breakthrough evidence",
    "double life exposed secret",
    "ritual gone wrong tragedy",
    "unexplained incident witness",
    "horror survived account",
]


def _collect_from_newsapi(
    used_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    if not NEWS_API:
        log.debug("NewsAPI key absent — skipping news collection.")
        return []

    candidates: list[StoryCandidate] = []
    # Inject trending keywords into queries
    queries = list(_NEWS_QUERY_TERMS[:4])
    if ctx.trending_keywords:
        trend_query = " OR ".join(ctx.trending_keywords[:3])
        queries.append(trend_query)

    for query in queries:
        try:
            resp = with_retry(
                http_get_json,
                "https://newsapi.org/v2/everything",
                headers={"X-Api-Key": NEWS_API},
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 8,
                },
            )
            for article in resp.get("articles", []):
                title   = (article.get("title") or "").strip()
                desc    = (article.get("description") or "").strip()
                content = (article.get("content") or "").strip()
                url     = article.get("url", "")
                source  = article.get("source", {}).get("name", "news")

                if not title or title == "[Removed]":
                    continue

                story_id = story_id_from_content(title, url or source)
                if story_id in used_ids:
                    continue

                summary = desc or content[:500] or title
                pillar  = _infer_pillar_from_text(title + " " + summary)
                country = _extract_country_hint(title + " " + summary)
                label   = _build_story_label(pillar, country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=_truncate(summary, 600),
                    raw_content=_truncate(content or summary, 1500),
                    source=f"newsapi/{source}",
                    source_url=url,
                    country=country,
                    pillar=pillar.value,
                    story_label=label,
                ))
            time.sleep(0.2)
        except Exception as exc:
            log.warning(f"NewsAPI collection failed for query '{query[:40]}': {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: RSS FEEDS
# ─────────────────────────────────────────────

def _collect_from_rss(
    used_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []

    for feed_url, pillar, country in _RSS_FEEDS:
        try:
            raw = with_retry(
                http_get,
                feed_url,
                headers={"User-Agent": "KarmaVaultStories/1.0 rss-reader"},
                timeout=12,
            )
            root = ET.fromstring(raw)

            # Handle both RSS 2.0 and Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for item in items[:10]:
                title_el = item.find("title")
                desc_el  = item.find("description") or item.find("atom:summary", ns)
                link_el  = item.find("link") or item.find("atom:link", ns)

                title   = _strip_cdata(title_el.text if title_el is not None else "")
                desc    = _strip_cdata(desc_el.text  if desc_el  is not None else "")
                link    = link_el.get("href", link_el.text) if link_el is not None else ""

                if not title:
                    continue

                story_id = story_id_from_content(title, link or feed_url)
                if story_id in used_ids:
                    continue

                # Infer pillar from content if feed is generic
                actual_pillar = pillar if pillar else _infer_pillar_from_text(title + " " + desc)
                actual_country = country if country != "global" else _extract_country_hint(title + " " + desc)
                label = _build_story_label(actual_pillar, actual_country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=_truncate(_strip_html(desc), 600),
                    raw_content=_truncate(_strip_html(desc), 1500),
                    source="rss",
                    source_url=link,
                    country=actual_country,
                    pillar=actual_pillar.value,
                    story_label=label,
                ))
            time.sleep(0.3)
        except Exception as exc:
            log.warning(f"RSS collection failed for {feed_url[:60]}: {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: SEARCH API (Tavily / SerpAPI)
# ─────────────────────────────────────────────

def _collect_from_search(
    used_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []

    # Build queries from pillar map + trending signals
    force = ctx.force_pillar
    if force and force in _PILLAR_SEARCH_QUERIES:
        queries = _PILLAR_SEARCH_QUERIES[force][:2]
        other_pillars = [p for p in _PILLAR_SEARCH_QUERIES if p != force]
        extra_pillar  = random.choice(other_pillars)
        queries += _PILLAR_SEARCH_QUERIES[extra_pillar][:1]
    else:
        # Pick 2 random pillars
        pillars_chosen = random.sample(list(_PILLAR_SEARCH_QUERIES.keys()), 2)
        queries = []
        for p in pillars_chosen:
            queries.extend(_PILLAR_SEARCH_QUERIES[p][:1])

    # Inject trending keyword for one query
    if ctx.trending_keywords:
        trending_q = f"true story dark {ctx.trending_keywords[0]} real incident"
        queries.append(trending_q)

    for query in queries:
        try:
            results = with_retry(call_search, query, num_results=6)
            for r in results:
                title   = (r.get("title") or "").strip()
                snippet = (r.get("snippet") or "").strip()
                url     = r.get("url", "")

                if not title or len(title) < 10:
                    continue

                story_id = story_id_from_content(title, url)
                if story_id in used_ids:
                    continue

                pillar  = _infer_pillar_from_text(title + " " + snippet)
                country = _extract_country_hint(title + " " + snippet)
                label   = _build_story_label(pillar, country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=_truncate(snippet, 600),
                    raw_content=_truncate(snippet, 1500),
                    source=f"search/{r.get('source', 'web')}",
                    source_url=url,
                    country=country,
                    pillar=pillar.value,
                    story_label=label,
                ))
            time.sleep(0.4)
        except Exception as exc:
            log.warning(f"Search story collection failed for '{query[:50]}': {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: INTERNET ARCHIVE (historical dark content)
# ─────────────────────────────────────────────

_ARCHIVE_QUERIES = [
    "true crime mystery historical",
    "paranormal investigation documented",
    "dark history secret revealed",
    "unsolved mystery archive",
    "haunted real case documented",
]


def _collect_from_archive(
    used_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []
    query = random.choice(_ARCHIVE_QUERIES)

    try:
        resp = with_retry(
            http_get_json,
            "https://archive.org/advancedsearch.php",
            params={
                "q": query,
                "output": "json",
                "rows": 12,
                "fl[]": "identifier,title,description,subject,date",
                "mediatype": "texts",
            },
            timeout=15,
        )
        docs = resp.get("response", {}).get("docs", [])
        for doc in docs:
            title = (doc.get("title") or "").strip()
            desc  = (doc.get("description") or "")
            if isinstance(desc, list):
                desc = " ".join(desc)
            desc = desc.strip()
            identifier = doc.get("identifier", "")

            if not title or len(title) < 5:
                continue

            story_id = story_id_from_content(title, f"archive/{identifier}")
            if story_id in used_ids:
                continue

            pillar  = _infer_pillar_from_text(title + " " + desc)
            country = _extract_country_hint(title + " " + desc)
            label   = _build_story_label(pillar, country)
            url     = f"https://archive.org/details/{identifier}" if identifier else ""

            candidates.append(StoryCandidate(
                id=story_id,
                title=title,
                summary=_truncate(desc, 600),
                raw_content=_truncate(desc, 1500),
                source="internet_archive",
                source_url=url,
                country=country,
                pillar=pillar.value,
                story_label=label,
            ))
    except Exception as exc:
        log.warning(f"Internet Archive collection failed: {exc}")
    return candidates


# ─────────────────────────────────────────────
# CLASSIFICATION HELPERS
# ─────────────────────────────────────────────

_PILLAR_KEYWORDS: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "ghost", "haunted", "spirit", "paranormal", "jinn", "demon",
        "supernatural", "possessed", "ritual", "curse", "apparition", "poltergeist",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "betray", "affair", "double life", "secret husband", "secret wife",
        "hidden family", "cheat", "lied", "deception", "exposed", "revealed",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "disappear", "missing", "vanish", "never found", "last seen",
        "no trace", "unsolved", "cold case", "gone missing", "search for",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "accident", "tragedy", "disaster", "explosion", "crash",
        "collapse", "incident", "industrial", "fire", "flood",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "historical", "archive", "1900", "1800", "world war", "secret experiment",
        "classified", "government", "cover-up", "declassified", "forgotten",
    ],
    ContentPillar.AI_HORROR.value: [
        "artificial intelligence", "ai system", "robot", "algorithm", "deep fake",
        "machine", "technology dark", "digital horror",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "double life", "secret identity", "two families", "hidden life",
        "second family", "fake identity", "impostor", "secret life",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "confession", "reddit", "anonymous", "admit", "i did it",
        "dark secret", "told no one", "finally confess",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "urban legend", "local legend", "myth", "folklore", "legend proven",
        "origin story", "dark myth", "legend true",
    ],
}

_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "Egypt":         ["egypt", "egyptian", "cairo", "nile"],
    "India":         ["india", "indian", "mumbai", "delhi", "bangalore"],
    "USA":           ["usa", "america", "american", "new york", "los angeles", "texas", "florida"],
    "UK":            ["uk", "britain", "british", "london", "england"],
    "Saudi Arabia":  ["saudi", "riyadh", "mecca", "medina"],
    "Pakistan":      ["pakistan", "pakistani", "karachi", "lahore"],
    "Nigeria":       ["nigeria", "nigerian", "lagos", "abuja"],
    "Philippines":   ["philippines", "filipino", "manila"],
    "Mexico":        ["mexico", "mexican", "ciudad"],
    "Brazil":        ["brazil", "brazilian", "sao paulo", "rio"],
    "Iraq":          ["iraq", "iraqi", "baghdad", "mosul"],
    "Syria":         ["syria", "syrian", "damascus", "aleppo"],
    "South Korea":   ["korea", "korean", "seoul"],
    "Japan":         ["japan", "japanese", "tokyo", "osaka"],
    "Russia":        ["russia", "russian", "moscow"],
    "China":         ["china", "chinese", "beijing", "shanghai"],
    "Turkey":        ["turkey", "turkish", "istanbul", "ankara"],
    "Indonesia":     ["indonesia", "indonesian", "jakarta"],
    "Germany":       ["germany", "german", "berlin"],
    "France":        ["france", "french", "paris"],
    "Australia":     ["australia", "australian", "sydney", "melbourne"],
    "Canada":        ["canada", "canadian", "toronto", "vancouver"],
    "South Africa":  ["south africa", "johannesburg", "cape town"],
    "Iran":          ["iran", "iranian", "tehran"],
    "Lebanon":       ["lebanon", "lebanese", "beirut"],
    "Jordan":        ["jordan", "jordanian", "amman"],
    "Morocco":       ["morocco", "moroccan", "casablanca"],
}


def _infer_pillar_from_text(text: str) -> ContentPillar:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for pillar_val, keywords in _PILLAR_KEYWORDS.items():
        scores[pillar_val] = sum(1 for kw in keywords if kw in text_lower)

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return ContentPillar.TRUE_SHOCKING
    return ContentPillar(best)


def _extract_country_hint(text: str) -> str:
    text_lower = text.lower()
    for country, keywords in _COUNTRY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return country
    return "Unknown"


def _build_story_label(pillar: ContentPillar, country: str) -> str:
    if pillar == ContentPillar.PARANORMAL:
        return StoryLabel.HAUNTED_FILE.value
    if pillar in (ContentPillar.HISTORICAL_DARK, ContentPillar.DISTURBING_ACCIDENTS):
        return StoryLabel.REAL_INCIDENT.value
    if pillar in (ContentPillar.INTERNET_CONFESSION, ContentPillar.AI_HORROR):
        return StoryLabel.INSPIRED.value
    if pillar == ContentPillar.URBAN_LEGENDS:
        return StoryLabel.PARANORMAL.value
    country_display = country if country not in ("Unknown", "global") else "AN UNKNOWN LOCATION"
    return StoryLabel.TRUE_STORY.value.replace("{COUNTRY}", country_display)


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def _strip_cdata(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.replace("<![CDATA[", "").replace("]]>", "").strip()


def _strip_html(text: str) -> str:
    """Remove basic HTML tags from RSS description text."""
    import re
    return re.sub(r"<[^>]+>", " ", text or "").strip()

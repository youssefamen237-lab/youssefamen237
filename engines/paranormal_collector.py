"""
engines/paranormal_collector.py
Karma Vault Stories — Paranormal Story Collector Engine
Dedicated collector for paranormal, haunted, jinn, and supernatural content.
Operates independently from the real-story collector so paranormal pillar
always has a rich candidate pool regardless of trending news volume.
"""

import time
import random
import json
from datetime import datetime, timezone

from config.settings import (
    TAVILY_API_KEY, NEWS_API, INTERNET_ARCHIVE_ACCESS_KEY,
    API_REQUEST_TIMEOUT_SEC,
)
from config.constants import ContentPillar, StoryLabel
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import story_id_from_content, get_used_story_ids
from utils.api_client import (
    call_search, http_get_json, http_get, with_retry,
)
from engines.story_collector import (
    _truncate, _extract_country_hint, _strip_html, _strip_cdata,
)

log = get_logger(__name__)

# ─────────────────────────────────────────────
# PARANORMAL SUBREDDIT CONFIG
# ─────────────────────────────────────────────

_PARANORMAL_SUBREDDITS = [
    ("Paranormal",              "global"),
    ("Glitch_in_the_Matrix",    "global"),
    ("Haunted",                 "global"),
    ("Jinn",                    "global"),
    ("TrueScaryStories",        "global"),
    ("Thetruthishere",          "global"),
    ("GhostStories",            "global"),
    ("ExplainThisThing",        "global"),
    ("DemonicActivity",         "global"),
    ("Humanoidencounters",      "global"),
    ("HighStrangeness",         "global"),
    ("Skinwalker",              "global"),
    ("ShadowPeople",            "global"),
    ("PrimevalForest",          "global"),
    ("BackroomsCreepy",         "global"),
]

# Paranormal search queries — real investigation accounts and documented cases
_PARANORMAL_SEARCH_QUERIES = [
    "real paranormal encounter evidence investigated",
    "haunted location official investigation documented",
    "jinn possession account verified witness",
    "ghost sighting evidence photograph real case",
    "supernatural event investigated police record",
    "exorcism real account documented witnesses",
    "haunted house investigation real evidence",
    "shadow figure real encounter account",
    "demonic activity real documented case",
    "paranormal activity official investigation report",
    "true haunted story witness testimony",
    "spirit encounter real photograph evidence",
    "possessed person real documented account",
    "curse real consequence documented case",
    "ritual gone wrong real account",
]

# Paranormal RSS / feeds
_PARANORMAL_RSS = [
    "https://news.google.com/rss/search?q=paranormal+investigation+real+evidence+OR+haunting+documented+case+OR+jinn+encounter+real&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=ghost+sighting+evidence+OR+supernatural+phenomenon+investigated+OR+possessed+documented&hl=en-US&gl=US&ceid=US:en",
]

# Evergreen paranormal queries for Internet Archive
_ARCHIVE_PARANORMAL_QUERIES = [
    "ghost investigation documented",
    "paranormal activity real case",
    "haunted house documented evidence",
    "supernatural phenomenon real",
    "spirit encounter testimonial",
]

# High-performing paranormal countries / regions for label
_PARANORMAL_COUNTRIES = [
    "Egypt", "Saudi Arabia", "Iraq", "Iran", "Pakistan",
    "India", "Philippines", "Lebanon", "Syria", "Jordan",
    "Morocco", "Turkey", "Indonesia", "Malaysia", "Nigeria",
    "UK", "USA", "Mexico", "Brazil",
]


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_paranormal_collector(ctx: DailyRunContext) -> DailyRunContext:
    """
    Appends paranormal-specific StoryCandidate objects to ctx.raw_candidates.
    Targets 8-15 high-quality paranormal candidates per run.
    """
    log.info("Paranormal collector starting...")
    used_ids = get_used_story_ids()

    # Also collect IDs already in raw_candidates to avoid intra-run duplication
    existing_ids = {c.id for c in ctx.raw_candidates}
    all_skip = used_ids | existing_ids

    paranormal_candidates: list[StoryCandidate] = []

    # 1. Reddit paranormal subreddits
    reddit = _collect_paranormal_reddit(all_skip)
    paranormal_candidates.extend(reddit)
    log.info(f"Paranormal Reddit candidates: {len(reddit)}")

    # 2. Search-based paranormal stories
    search = _collect_paranormal_search(all_skip, ctx)
    paranormal_candidates.extend(search)
    log.info(f"Paranormal search candidates: {len(search)}")

    # 3. RSS paranormal feeds
    rss = _collect_paranormal_rss(all_skip)
    paranormal_candidates.extend(rss)
    log.info(f"Paranormal RSS candidates: {len(rss)}")

    # 4. Internet Archive paranormal documents
    archive = _collect_paranormal_archive(all_skip)
    paranormal_candidates.extend(archive)
    log.info(f"Paranormal Archive candidates: {len(archive)}")

    # Deduplicate within this collector
    seen: set[str] = set()
    unique: list[StoryCandidate] = []
    for c in paranormal_candidates:
        if c.id not in seen and c.id not in all_skip:
            seen.add(c.id)
            unique.append(c)

    # Cap at 15 paranormal candidates
    unique = unique[:15]

    log.info(f"Paranormal collector complete. {len(unique)} candidates added.")
    ctx.raw_candidates.extend(unique)
    ctx.mark_stage("paranormal_collector")
    return ctx


# ─────────────────────────────────────────────
# SOURCE: PARANORMAL REDDIT
# ─────────────────────────────────────────────

def _collect_paranormal_reddit(skip_ids: set) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []
    chosen = random.sample(_PARANORMAL_SUBREDDITS, min(4, len(_PARANORMAL_SUBREDDITS)))

    for subreddit, base_country in chosen:
        try:
            url = (
                f"https://www.reddit.com/r/{subreddit}/top.json"
                f"?limit=15&t=month"
            )
            resp = with_retry(
                http_get_json,
                url,
                headers={"User-Agent": "KarmaVaultStories/1.0 paranormal-research-bot"},
                timeout=15,
            )
            posts = resp.get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                title  = (d.get("title") or "").strip()
                body   = (d.get("selftext") or "").strip()
                score  = d.get("score", 0)
                link   = d.get("permalink", "")
                post_url = f"https://reddit.com{link}" if link else ""

                if not title or score < 20:
                    continue
                if body in ("[removed]", "[deleted]"):
                    body = ""

                story_id = story_id_from_content(title, f"reddit_paranormal/{subreddit}")
                if story_id in skip_ids:
                    continue

                # Quality gate: paranormal stories need enough detail
                combined_text = title + " " + body
                if not _has_paranormal_substance(combined_text):
                    continue

                raw_text = body[:2000] if body else title
                summary  = _truncate(body or title, 600)
                country  = _extract_country_hint(combined_text)
                if country == "Unknown":
                    country = random.choice(_PARANORMAL_COUNTRIES[:8])

                label = _build_paranormal_label(subreddit, country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=summary,
                    raw_content=raw_text,
                    source=f"reddit/r/{subreddit}",
                    source_url=post_url,
                    country=country,
                    pillar=ContentPillar.PARANORMAL.value,
                    story_label=label,
                ))
            time.sleep(0.6)
        except Exception as exc:
            log.warning(f"Paranormal Reddit failed for r/{subreddit}: {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: PARANORMAL SEARCH
# ─────────────────────────────────────────────

def _collect_paranormal_search(
    skip_ids: set, ctx: DailyRunContext
) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []

    # Inject trending keywords if any paranormal ones exist
    queries = random.sample(_PARANORMAL_SEARCH_QUERIES, 3)
    if ctx.trending_keywords:
        trend_paranormal = [
            kw for kw in ctx.trending_keywords
            if any(term in kw.lower() for term in
                   ["ghost", "haunted", "jinn", "paranormal", "spirit", "curse",
                    "ritual", "demon", "supernatural"])
        ]
        if trend_paranormal:
            queries.append(f"real paranormal {trend_paranormal[0]} documented case")

    for query in queries:
        try:
            results = with_retry(call_search, query, num_results=5)
            for r in results:
                title   = (r.get("title") or "").strip()
                snippet = (r.get("snippet") or "").strip()
                url     = r.get("url", "")

                if not title or len(title) < 10:
                    continue
                combined = title + " " + snippet
                if not _has_paranormal_substance(combined):
                    continue

                story_id = story_id_from_content(title, url)
                if story_id in skip_ids:
                    continue

                country = _extract_country_hint(combined)
                if country == "Unknown":
                    country = random.choice(_PARANORMAL_COUNTRIES[:10])

                label = _build_paranormal_label("search", country)

                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=_truncate(snippet, 600),
                    raw_content=_truncate(snippet, 1500),
                    source=f"search_paranormal/{r.get('source', 'web')}",
                    source_url=url,
                    country=country,
                    pillar=ContentPillar.PARANORMAL.value,
                    story_label=label,
                ))
            time.sleep(0.4)
        except Exception as exc:
            log.warning(f"Paranormal search failed for '{query[:50]}': {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: PARANORMAL RSS
# ─────────────────────────────────────────────

def _collect_paranormal_rss(skip_ids: set) -> list[StoryCandidate]:
    import xml.etree.ElementTree as ET
    candidates: list[StoryCandidate] = []

    for feed_url in _PARANORMAL_RSS:
        try:
            raw = with_retry(
                http_get,
                feed_url,
                headers={"User-Agent": "KarmaVaultStories/1.0 rss-reader"},
                timeout=12,
            )
            root = ET.fromstring(raw)
            items = root.findall(".//item")
            for item in items[:8]:
                title_el = item.find("title")
                desc_el  = item.find("description")
                link_el  = item.find("link")

                title = _strip_cdata(title_el.text if title_el is not None else "")
                desc  = _strip_cdata(desc_el.text  if desc_el  is not None else "")
                link  = link_el.text if link_el is not None else ""

                if not title:
                    continue
                if not _has_paranormal_substance(title + " " + desc):
                    continue

                story_id = story_id_from_content(title, link or feed_url)
                if story_id in skip_ids:
                    continue

                country = _extract_country_hint(title + " " + desc)
                if country == "Unknown":
                    country = random.choice(_PARANORMAL_COUNTRIES[:8])

                label = _build_paranormal_label("rss", country)
                candidates.append(StoryCandidate(
                    id=story_id,
                    title=title,
                    summary=_truncate(_strip_html(desc), 600),
                    raw_content=_truncate(_strip_html(desc), 1500),
                    source="rss_paranormal",
                    source_url=link,
                    country=country,
                    pillar=ContentPillar.PARANORMAL.value,
                    story_label=label,
                ))
            time.sleep(0.3)
        except Exception as exc:
            log.warning(f"Paranormal RSS failed: {exc}")
    return candidates


# ─────────────────────────────────────────────
# SOURCE: INTERNET ARCHIVE PARANORMAL
# ─────────────────────────────────────────────

def _collect_paranormal_archive(skip_ids: set) -> list[StoryCandidate]:
    candidates: list[StoryCandidate] = []
    query = random.choice(_ARCHIVE_PARANORMAL_QUERIES)

    try:
        resp = with_retry(
            http_get_json,
            "https://archive.org/advancedsearch.php",
            params={
                "q": query,
                "output": "json",
                "rows": 8,
                "fl[]": "identifier,title,description,subject",
                "mediatype": "texts",
            },
            timeout=15,
        )
        docs = resp.get("response", {}).get("docs", [])
        for doc in docs:
            title = (doc.get("title") or "").strip()
            desc  = doc.get("description") or ""
            if isinstance(desc, list):
                desc = " ".join(desc)
            desc = desc.strip()
            identifier = doc.get("identifier", "")

            if not title:
                continue
            if not _has_paranormal_substance(title + " " + desc):
                continue

            story_id = story_id_from_content(title, f"archive_paranormal/{identifier}")
            if story_id in skip_ids:
                continue

            country = _extract_country_hint(title + " " + desc)
            if country == "Unknown":
                country = random.choice(_PARANORMAL_COUNTRIES[:8])

            label = _build_paranormal_label("archive", country)
            url   = f"https://archive.org/details/{identifier}" if identifier else ""

            candidates.append(StoryCandidate(
                id=story_id,
                title=title,
                summary=_truncate(desc, 600),
                raw_content=_truncate(desc, 1500),
                source="archive_paranormal",
                source_url=url,
                country=country,
                pillar=ContentPillar.PARANORMAL.value,
                story_label=label,
            ))
    except Exception as exc:
        log.warning(f"Paranormal Archive collection failed: {exc}")
    return candidates


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

_PARANORMAL_SUBSTANCE_TERMS = {
    "ghost", "haunt", "spirit", "paranormal", "jinn", "demon", "supernatural",
    "possess", "apparition", "specter", "shadow", "dark presence", "evil",
    "ritual", "curse", "poltergeist", "encounter", "visited", "appeared",
    "floating", "disappeared", "felt presence", "heard voice", "saw figure",
    "cold spot", "moved on its own", "knocking", "scratching", "whisper",
    "levitate", "exorcism", "summoned", "entity", "cryptid", "ufo",
    "unexplained", "investigated", "evidence", "witness", "terrified",
}


def _has_paranormal_substance(text: str) -> bool:
    """Returns True if text contains enough paranormal vocabulary to be useful."""
    text_lower = text.lower()
    matches = sum(1 for term in _PARANORMAL_SUBSTANCE_TERMS if term in text_lower)
    return matches >= 2


def _build_paranormal_label(source: str, country: str) -> str:
    jinn_sources = {"Jinn", "reddit/r/Jinn"}
    if source in jinn_sources or "jinn" in source.lower():
        return "PARANORMAL REPORT"
    if country not in ("Unknown", "global"):
        return f"HAUNTED FILE — {country.upper()}"
    return StoryLabel.HAUNTED_FILE.value

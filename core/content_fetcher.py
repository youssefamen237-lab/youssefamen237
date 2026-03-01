"""
core/content_fetcher.py – Quizzaro Content Fetcher
====================================================
Aggregates raw trivia context from four free sources:
  1. Wikipedia (REST API — no key required)
  2. Google Trends (pytrends — no key required)
  3. NewsAPI (free tier — NEWS_API key)
  4. YouTube Data API v3 trending (YOUTUBE_API_KEY)

Used by QuestionBank to enrich AI prompts with fresh factual context,
improving answer accuracy and keeping questions culturally relevant.
"""

from __future__ import annotations

import random
from typing import Optional

import requests
from loguru import logger
from pytrends.request import TrendReq


class ContentFetcher:

    def __init__(
        self,
        serpapi_key: str = "",
        tavily_key: str = "",
        news_api_key: str = "",
        youtube_api_key: str = "",
    ) -> None:
        self._news_key = news_api_key
        self._yt_key = youtube_api_key
        self._pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 20))

    # ── Wikipedia ─────────────────────────────────────────────────────────

    def fetch_wikipedia_facts(self, topic: str, count: int = 4) -> list[str]:
        facts: list[str] = []
        try:
            search_resp = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": topic,
                    "srlimit": count * 2,
                    "format": "json",
                    "srnamespace": "0",
                },
                timeout=12,
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("query", {}).get("search", [])

            for item in results[:count * 2]:
                title = item.get("title", "")
                extract_resp = requests.get(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/" + title.replace(" ", "_"),
                    timeout=10,
                )
                if extract_resp.status_code == 200:
                    summary = extract_resp.json().get("extract", "")
                    if len(summary) > 80:
                        facts.append(summary[:350].strip())
                if len(facts) >= count:
                    break
        except Exception as exc:
            logger.warning(f"[ContentFetcher] Wikipedia failed for '{topic}': {exc}")
        return facts

    # ── Google Trends ──────────────────────────────────────────────────────

    def fetch_trending_topics(self, country: str = "united_states") -> list[str]:
        try:
            df = self._pytrends.trending_searches(pn=country)
            return df[0].tolist()[:12]
        except Exception as exc:
            logger.warning(f"[ContentFetcher] Trends failed: {exc}")
            return []

    # ── NewsAPI ────────────────────────────────────────────────────────────

    def fetch_news_headlines(self, count: int = 8) -> list[str]:
        if not self._news_key:
            return []
        try:
            resp = requests.get(
                "https://newsapi.org/v2/top-headlines",
                params={"language": "en", "pageSize": count, "apiKey": self._news_key},
                timeout=12,
            )
            resp.raise_for_status()
            return [a["title"] for a in resp.json().get("articles", []) if a.get("title")]
        except Exception as exc:
            logger.warning(f"[ContentFetcher] News failed: {exc}")
            return []

    # ── YouTube trending titles ────────────────────────────────────────────

    def fetch_youtube_trending(self, region: str = "US", count: int = 8) -> list[str]:
        if not self._yt_key:
            return []
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet",
                    "chart": "mostPopular",
                    "regionCode": region,
                    "maxResults": count,
                    "key": self._yt_key,
                },
                timeout=12,
            )
            resp.raise_for_status()
            return [i["snippet"]["title"] for i in resp.json().get("items", [])]
        except Exception as exc:
            logger.warning(f"[ContentFetcher] YouTube trending failed: {exc}")
            return []

    # ── Combined context builder ───────────────────────────────────────────

    def gather_context(self, category: str, include_trends: bool = True) -> list[str]:
        """
        Build a list of raw fact strings for AI prompt injection.
        Wikipedia is always primary; trends/news added probabilistically.
        """
        facts = self.fetch_wikipedia_facts(category, count=4)

        if include_trends and random.random() < 0.40:
            trends = self.fetch_trending_topics()
            if trends:
                facts.append(f"Current trending topic for cultural flavour: {random.choice(trends)}")

        if self._news_key and random.random() < 0.25:
            headlines = self.fetch_news_headlines(count=5)
            if headlines:
                facts.append(f"Recent news headline for context: {random.choice(headlines)}")

        return facts[:5]

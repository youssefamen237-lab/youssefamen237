"""
engines/fact_research.py
"""
from __future__ import annotations
import os
from typing import Dict, List, Optional
import requests, structlog
from cascade.llm.llm_cascade import get_llm
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_TAVILY_URL  = "https://api.tavily.com/search"
_SERPAPI_URL = "https://serpapi.com/search.json"
_APPROVED_DOMAINS = [
    "wikipedia.org", "nationalgeographic.com", "britannica.com",
    "nasa.gov", "noaa.gov", "smithsonianmag.com", "bbcearth.com",
]
_MIN_FACTS_THRESHOLD = 4
_EXTRACT_SYSTEM = (
    "You are a science fact extractor. "
    "Only state facts that are directly supported by the provided source text. "
    "Do not fabricate, exaggerate, or embellish."
)


class FactResearch:

    def __init__(self) -> None:
        self._llm = get_llm()
        self._db  = get_db()

    def research(
        self,
        topic_id:   str,
        topic_name: str,
        category:   str,
        count:      int = 10,
    ) -> List[Dict]:
        """
        Return up to `count` verified fact dicts for the topic.
        Checks DB first; researches online when DB has fewer than threshold.
        """
        existing = self._db.get_facts_for_topic(topic_id=topic_id, limit=count, min_confidence=65)
        if len(existing) >= _MIN_FACTS_THRESHOLD:
            logger.info("facts_from_db", topic=topic_name, count=len(existing))
            return existing[:count]

        new_facts = self._research_online(topic_name, category, count)
        if new_facts:
            self._persist(topic_id, new_facts)

        merged = existing + new_facts
        merged.sort(key=lambda f: int(f.get("curiosity_level", 50)), reverse=True)
        logger.info("facts_ready", topic=topic_name, total=len(merged))
        return merged[:count]

    # ── Online research ────────────────────────────────────────────────────────

    def _research_online(self, topic_name: str, category: str, count: int) -> List[Dict]:
        queries = self._generate_queries(topic_name, category)
        snippets = self._search(queries)
        if snippets:
            return self._extract_facts(topic_name, snippets, count)
        return self._llm_only_facts(topic_name, category, count)

    def _generate_queries(self, topic_name: str, category: str) -> List[str]:
        prompt = (
            f'Generate 5 scientific search queries to find surprising facts about: {topic_name}\n'
            f'Category: {category}\n'
            f'Return JSON: {{"queries": ["q1","q2","q3","q4","q5"]}}'
        )
        try:
            data = self._llm.generate_json(prompt=prompt, max_tokens=200)
            qs = [str(q) for q in data.get("queries", []) if q][:5]
            if qs:
                return qs
        except Exception:
            pass
        return [f"{topic_name} facts", f"{topic_name} biology record", f"{topic_name} science"]

    def _search(self, queries: List[str]) -> List[str]:
        snippets = self._tavily_search(queries)
        if not snippets:
            snippets = self._serpapi_search(queries)
        return snippets

    def _tavily_search(self, queries: List[str]) -> List[str]:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return []
        snippets: List[str] = []
        for q in queries[:4]:
            try:
                resp = requests.post(
                    _TAVILY_URL,
                    json={
                        "api_key": api_key,
                        "query": q,
                        "max_results": 3,
                        "search_depth": "basic",
                        "include_domains": _APPROVED_DOMAINS,
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    for r in resp.json().get("results", []):
                        c = r.get("content", "")
                        if len(c) > 60:
                            snippets.append(f"[{r.get('url','')}] {c[:600]}")
            except Exception as exc:
                logger.debug("tavily_miss", q=q[:40], err=str(exc)[:60])
        return snippets

    def _serpapi_search(self, queries: List[str]) -> List[str]:
        api_key = os.getenv("SERPAPI", "") or os.getenv("ZENSERP", "")
        if not api_key:
            return []
        snippets: List[str] = []
        try:
            resp = requests.get(
                _SERPAPI_URL,
                params={"q": queries[0], "api_key": api_key, "num": 5},
                timeout=15,
            )
            if resp.status_code == 200:
                for r in resp.json().get("organic_results", []):
                    snip = r.get("snippet", "")
                    if len(snip) > 40:
                        snippets.append(f"[{r.get('link','')}] {snip}")
        except Exception as exc:
            logger.debug("serpapi_miss", err=str(exc)[:60])
        return snippets

    # ── Extraction ────────────────────────────────────────────────────────────

    def _extract_facts(self, topic_name: str, snippets: List[str], count: int) -> List[Dict]:
        context = "\n\n".join(snippets[:8])
        prompt = f"""Extract {count} fascinating scientific facts about {topic_name} from these search results:

{context}

Return JSON:
{{
    "facts": [
        {{
            "fact_text": "<one clear, self-contained factual sentence>",
            "fact_type": "<size|speed|intelligence|danger|hunting|survival|family|communication|mystery|record|comparison|biology|behavior>",
            "curiosity_level": <0-100>,
            "confidence_score": <0-100>,
            "source_name": "<domain e.g. nationalgeographic.com>"
        }}
    ]
}}

Rules: only include facts directly supported by the text above. Prioritise surprising facts."""
        try:
            data = self._llm.generate_json(prompt=prompt, system_prompt=_EXTRACT_SYSTEM, max_tokens=1600)
            return [f for f in data.get("facts", []) if f.get("fact_text")]
        except Exception as exc:
            logger.warning("extraction_failed", err=str(exc)[:100])
            return self._llm_only_facts(topic_name, "general", count)

    def _llm_only_facts(self, topic_name: str, category: str, count: int) -> List[Dict]:
        prompt = f"""List {count} accurate scientific facts about {topic_name} (category: {category}).
Return JSON: {{"facts":[{{"fact_text":"...","fact_type":"biology","curiosity_level":70,"confidence_score":70,"source_name":"general_knowledge"}}]}}"""
        try:
            data = self._llm.generate_json(prompt=prompt, max_tokens=1200)
            return [f for f in data.get("facts", []) if f.get("fact_text")]
        except Exception:
            return []

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist(self, topic_id: str, facts: List[Dict]) -> None:
        rows = []
        for f in facts:
            if not f.get("fact_text"):
                continue
            src_name = f.get("source_name", "general_knowledge")
            src = self._db.get_source_by_name(src_name)
            rows.append({
                "topic_id":        topic_id,
                "fact_text":       str(f["fact_text"]),
                "fact_type":       str(f.get("fact_type", "biology")),
                "curiosity_level": int(f.get("curiosity_level", 50)),
                "visual_potential":60,
                "evergreen_score": 90,
                "viral_potential": int(f.get("curiosity_level", 50)),
                "confidence_score":int(f.get("confidence_score", 70)),
                "source_ids":      [src["source_id"]] if src else [],
                "source_count":    1 if src else 0,
                "is_verified":     int(f.get("confidence_score", 0)) >= 75,
                "status":          "verified" if int(f.get("confidence_score", 0)) >= 75 else "new",
            })
        if rows:
            try:
                self._db.bulk_insert_facts(rows)
            except Exception as exc:
                logger.warning("fact_persist_failed", err=str(exc)[:100])


_instance: Optional[FactResearch] = None

def get_fact_research() -> FactResearch:
    global _instance
    if _instance is None:
        _instance = FactResearch()
    return _instance

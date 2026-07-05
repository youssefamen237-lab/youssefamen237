"""
engines/metadata_generator.py
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import structlog
from cascade.llm.llm_cascade import get_llm
from storage.supabase_client import get_db
from storage.redis_client import get_redis

logger = structlog.get_logger(__name__)

_CATEGORY_HASHTAGS: Dict[str, List[str]] = {
    "ocean":   ["Nature", "Ocean", "Wildlife", "Science", "MarineLife"],
    "animals": ["Nature", "Animals", "Wildlife", "Science", "NatureLovers"],
    "space":   ["Space", "Science", "Universe", "NASA", "Astronomy"],
    "nature":  ["Nature", "Wildlife", "Earth", "Science", "NatureFacts"],
    "birds":   ["Birds", "Nature", "Wildlife", "Birdwatching", "Science"],
    "insects": ["Insects", "Nature", "Science", "Wildlife", "EntomologyFacts"],
}
_DEFAULT_HASHTAGS = ["Nature", "Science", "Wildlife"]
_YT_CATEGORY_ID  = "28"   # Science & Technology

_META_SYSTEM = (
    "You write concise, curiosity-driven YouTube metadata for a nature and science channel. "
    "Titles must be compelling, truthful, and under 100 characters. "
    "Descriptions must be factual and written in plain English."
)


@dataclass
class MetadataResult:
    title:        str
    description:  str
    hashtags:     List[str]
    tags:         List[str]   # YouTube tags (hashtags without #)
    category_id:  str         = _YT_CATEGORY_ID
    playlist_id:  Optional[str] = None


class MetadataGenerator:

    def __init__(self) -> None:
        self._llm   = get_llm()
        self._db    = get_db()
        self._redis = get_redis()

    def generate(
        self,
        topic_name:  str,
        category:    str,
        script:      Dict,
        facts:       List[Dict],
        video_type:  str = "short",
    ) -> MetadataResult:
        title       = self._generate_title(topic_name, category, script)
        description = self._generate_description(topic_name, category, script, facts, video_type)
        hashtags    = self._select_hashtags(topic_name, category)
        tags        = [h.lstrip("#") for h in hashtags]

        # NOTE: Title is NOT registered here.
        # Registration happens exclusively in protection/duplicate_guard.register(),
        # which short_pipeline.py calls at line 267 ONLY after all quality gates
        # pass and the video is confirmed approved. Registering here (before the
        # pipeline's check_title() call at line 222) caused a self-poisoning loop:
        # every topic's title was written to Redis by generate(), then immediately
        # detected as a duplicate by check_title(), exhausting all 5 retry attempts
        # on every single video and producing 100% "Exhausted topic attempts" failures.

        logger.info("metadata_generated", topic=topic_name, title=title[:60])
        return MetadataResult(
            title=title,
            description=description,
            hashtags=hashtags,
            tags=tags,
            category_id=_YT_CATEGORY_ID,
        )

    # ── Title ─────────────────────────────────────────────────────────────────

    def _generate_title(self, topic_name: str, category: str, script: Dict) -> str:
        hook = script.get("hook", "")

        # Try to use a DB title pattern
        pattern = self._pick_title_pattern(category)

        if pattern:
            prompt = (
                f"Fill in this YouTube title template for a nature/science video.\n"
                f"Template: {pattern}\n"
                f"Topic: {topic_name}\n"
                f"Hook: {hook}\n"
                f"Rules: max 90 characters, create strong curiosity, factually accurate.\n"
                f"Return ONLY the final title string. No quotes, no explanation."
            )
        else:
            prompt = (
                f"Write ONE YouTube video title about: {topic_name}\n"
                f"Hook context: {hook}\n"
                f"Rules: max 90 characters, create strong curiosity, no clickbait lies.\n"
                f"Return ONLY the title string."
            )
        try:
            title = self._llm.generate_text(
                prompt=prompt, system_prompt=_META_SYSTEM, max_tokens=80, temperature=0.65
            ).strip().strip('"\'')
            # Deduplicate check
            if self._redis.is_title_duplicate(title):
                title = self._fallback_title(topic_name)
            return title[:100]
        except Exception:
            return self._fallback_title(topic_name)

    def _pick_title_pattern(self, category: str) -> Optional[str]:
        try:
            patterns = self._db.get_titles_by_type("curiosity", limit=5)
            if not patterns:
                patterns = self._db.get_titles_by_type("danger", limit=5)
            if patterns:
                import random
                p = random.choice(patterns)
                return p.get("title_pattern", "")
        except Exception:
            pass
        return None

    @staticmethod
    def _fallback_title(topic_name: str) -> str:
        return f"The Truth About {topic_name} Nobody Tells You"[:100]

    # ── Description ───────────────────────────────────────────────────────────

    def _generate_description(
        self,
        topic_name: str,
        category:   str,
        script:     Dict,
        facts:      List[Dict],
        video_type: str,
    ) -> str:
        hook = script.get("hook", "")
        key_facts = [f["fact_text"] for f in facts[:3] if f.get("fact_text")]
        facts_str = " • ".join(key_facts) if key_facts else ""

        shorts_note = "\n\n#Shorts" if video_type == "short" else ""
        prompt = (
            f"Write a YouTube video description for this nature/science video.\n\n"
            f"Topic: {topic_name}\nCategory: {category}\n"
            f"Opening hook: {hook}\n"
            f"Key facts: {facts_str}\n\n"
            f"Requirements:\n"
            f"- 120 to 250 words\n"
            f"- First sentence mirrors the video hook energy\n"
            f"- Middle: 2-3 fascinating facts from the video\n"
            f"- End with: 'Follow for a new nature fact every day.'\n"
            f"- Plain English, no markdown, no emojis"
        )
        try:
            desc = self._llm.generate_text(
                prompt=prompt, system_prompt=_META_SYSTEM, max_tokens=350, temperature=0.65
            ).strip()
            return desc + shorts_note
        except Exception:
            return (
                f"Discover the most fascinating facts about {topic_name}. "
                f"{hook} Follow for a new nature fact every day.{shorts_note}"
            )

    # ── Hashtags ──────────────────────────────────────────────────────────────

    def _select_hashtags(self, topic_name: str, category: str) -> List[str]:
        base = list(_CATEGORY_HASHTAGS.get(category, _DEFAULT_HASHTAGS))
        # Add topic-specific tag
        topic_tag = "#" + topic_name.replace(" ", "").title()[:20]
        result = [f"#{h}" if not h.startswith("#") else h for h in base[:4]]
        result.append(topic_tag)
        return result[:5]


_instance: Optional[MetadataGenerator] = None

def get_metadata_generator() -> MetadataGenerator:
    global _instance
    if _instance is None:
        _instance = MetadataGenerator()
    return _instance

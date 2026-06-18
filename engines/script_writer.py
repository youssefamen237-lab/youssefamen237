"""
engines/script_writer.py
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import structlog
from cascade.llm.llm_cascade import get_llm
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_SYSTEM = (
    "You are a professional YouTube script writer for a nature and science channel. "
    "Your scripts achieve 85%+ retention. Write simple English (B1-B2 level) for a global audience. "
    "Every sentence must be short enough to match one video clip (max 20 words)."
)

_HOOK_OPENERS: Dict[str, str] = {
    "danger":      "This [ANIMAL/SUBJECT] can kill",
    "size":        "This [ANIMAL/SUBJECT] is larger than",
    "mystery":     "Scientists still cannot explain",
    "intelligence":"This [ANIMAL/SUBJECT] is smarter than",
    "speed":       "This [ANIMAL/SUBJECT] moves faster than",
    "survival":    "This [ANIMAL/SUBJECT] can survive",
    "comparison":  "Nothing on Earth compares to",
    "record":      "This [ANIMAL/SUBJECT] holds a world record",
}


class ScriptWriter:

    def __init__(self) -> None:
        self._llm = get_llm()
        self._db  = get_db()

    def write_script(
        self,
        topic_name:  str,
        category:    str,
        facts:       List[Dict],
        video_type:  str = "short",
        hook_type:   str = "danger",
    ) -> Dict:
        """
        Generate a structured script dict.  Keys:
            hook, segments [{sentence, search_query, visual_type, fact_index}],
            cta, full_text
        """
        seg_range = "4 to 6" if video_type == "short" else "15 to 25"
        cta_text  = self._pick_cta()
        facts_block = "\n".join(
            f"[{i}] {f.get('fact_text', '')}" for i, f in enumerate(facts[:10])
        )
        hook_hint = _HOOK_OPENERS.get(hook_type, "This subject is extraordinary because")

        prompt = f"""Write a YouTube {video_type} script about: {topic_name} (category: {category})

Hook type: {hook_type}  |  Opening style hint: "{hook_hint}"
Segment count: {seg_range} segments

Facts to reference (use 3-5 of the most compelling ones):
{facts_block}

Return ONLY a JSON object:
{{
    "hook": "<single opening sentence that stops the scroll — the most alarming or curious sentence>",
    "segments": [
        {{
            "sentence": "<one narration sentence, ≤20 words>",
            "search_query": "<2-4 word footage search term, e.g. 'orca hunting shark'>",
            "visual_type": "<action|close_up|wide|comparison|aerial>",
            "fact_index": <integer index into facts above, or -1>
        }}
    ],
    "cta": "{cta_text}",
    "full_text": "<hook + all segment sentences joined by spaces>"
}}

Rules:
- Hook must be the strongest sentence in the entire script.
- Each segment sentence fits 3-8 seconds of narration.
- search_query must be footage-specific (not vague — bad: 'ocean', good: 'orca breaching wave').
- full_text = hook + " " + all segment sentences joined by spaces.
- Do NOT add any text outside the JSON."""

        try:
            script = self._llm.generate_json(
                prompt=prompt, system_prompt=_SYSTEM, max_tokens=1800
            )
        except RuntimeError as exc:
            logger.error("script_llm_failed", topic=topic_name, error=str(exc))
            script = self._fallback_script(topic_name, facts, cta_text)

        script = self._validate(script, topic_name, category, cta_text)
        logger.info(
            "script_written",
            topic=topic_name,
            video_type=video_type,
            hook_type=hook_type,
            segments=len(script.get("segments", [])),
        )
        return script

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate(self, script: Dict, topic: str, category: str, cta: str) -> Dict:
        if not isinstance(script, dict):
            return self._fallback_script(topic, [], cta)

        if not script.get("hook"):
            script["hook"] = f"This is one of nature's most remarkable {topic.lower()} facts."

        segments = script.get("segments")
        if not isinstance(segments, list) or not segments:
            script["segments"] = [self._default_segment(topic, category)]
            segments = script["segments"]

        cleaned = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            cleaned.append({
                "sentence":     str(seg.get("sentence") or f"This is {topic}."),
                "search_query": str(seg.get("search_query") or topic.lower()),
                "visual_type":  str(seg.get("visual_type") or "wide"),
                "fact_index":   int(seg.get("fact_index", -1)),
            })
        if not cleaned:
            cleaned = [self._default_segment(topic, category)]
        script["segments"] = cleaned
        script["cta"] = cta

        all_sentences = [script["hook"]] + [s["sentence"] for s in cleaned]
        script["full_text"] = " ".join(s.strip() for s in all_sentences if s.strip())
        return script

    @staticmethod
    def _default_segment(topic: str, category: str) -> Dict:
        return {
            "sentence":     f"{topic} is one of the most fascinating subjects in {category}.",
            "search_query": topic.lower(),
            "visual_type":  "wide",
            "fact_index":   -1,
        }

    @staticmethod
    def _fallback_script(topic: str, facts: List[Dict], cta: str) -> Dict:
        fact_sentence = (
            facts[0]["fact_text"] if facts else f"{topic} has incredible abilities."
        )
        return {
            "hook":     f"This is one of the most extraordinary things about {topic}.",
            "segments": [
                {
                    "sentence":     fact_sentence,
                    "search_query": topic.lower(),
                    "visual_type":  "close_up",
                    "fact_index":   0 if facts else -1,
                }
            ],
            "cta":      cta,
            "full_text": f"This is one of the most extraordinary things about {topic}. {fact_sentence} {cta}",
        }

    def _pick_cta(self) -> str:
        try:
            row = self._db.get_random_cta()
            if row:
                return row["cta_text"]
        except Exception:
            pass
        return "Follow for a new nature fact every day."


_instance: Optional[ScriptWriter] = None

def get_script_writer() -> ScriptWriter:
    global _instance
    if _instance is None:
        _instance = ScriptWriter()
    return _instance

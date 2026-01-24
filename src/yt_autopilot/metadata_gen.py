\
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from .llm_clients import GeminiClient, GroqClient
from .utils.random_utils import shuffled

logger = logging.getLogger(__name__)


def _local_short_metadata(config: Dict[str, Any], question: str) -> Tuple[str, str, List[str], List[str]]:
    seo_cfg = config.get("seo") or {}
    patterns = list(seo_cfg.get("short_title_patterns") or [])
    title = random.choice(patterns).format(question=question)
    tags = list(seo_cfg.get("default_tags") or [])
    hashtags = list(seo_cfg.get("default_hashtags") or [])
    tags = shuffled(tags)[:10]
    hashtags = shuffled(hashtags)[:5]
    desc_lines = [
        "Quick quiz time!",
        "Comment your answer and see if you got it right.",
        "",
        "Subscribe for more daily quizzes.",
    ]
    desc = "\n".join(desc_lines + ["", " ".join(hashtags)])
    return title[:95], desc[:4900], tags, hashtags


def _local_long_metadata(config: Dict[str, Any], topic: str, count: int) -> Tuple[str, str, List[str], List[str]]:
    seo_cfg = config.get("seo") or {}
    patterns = list(seo_cfg.get("long_title_patterns") or [])
    title = random.choice(patterns).format(topic=topic.title(), count=count)
    tags = list(seo_cfg.get("default_tags") or [])
    hashtags = list(seo_cfg.get("default_hashtags") or [])
    tags = shuffled(tags)[:12]
    hashtags = shuffled(hashtags)[:6]
    desc_lines = [
        f"Welcome to a {topic.title()} quiz compilation!",
        f"{count} questions — pause if you need extra time.",
        "",
        "Tell us your score in the comments.",
        "Subscribe for more quiz videos every week.",
    ]
    desc = "\n".join(desc_lines + ["", " ".join(hashtags)])
    return title[:95], desc[:4900], tags, hashtags


def _meta_prompt(kind: str, payload: Dict[str, Any]) -> str:
    base = [
        "Output ONLY valid JSON. No markdown.",
        "Write naturally like a real creator.",
        "English only.",
        "Avoid spammy repetition.",
        "No politics, no religion, no adult content, no violence.",
        "Avoid copyrighted/trademarked names.",
        "Hashtags must start with # and be relevant.",
        "Return tags as a list of short strings, max 12.",
        "Return hashtags as a list, max 8.",
        "Title max 95 characters.",
        "Description max 4900 characters.",
    ]
    schema = {
        "title": "string",
        "description": "string",
        "tags": ["tag1", "tag2"],
        "hashtags": ["#tag1", "#tag2"],
    }
    return "\n".join([f"- {x}" for x in base]) + "\n\n" + f"Video kind: {kind}\nInput:\n{json.dumps(payload, ensure_ascii=False)}\n\nSchema:\n{schema}"


def generate_metadata(
    config: Dict[str, Any],
    secrets: Any,
    *,
    kind: str,
    question: Optional[str] = None,
    category: Optional[str] = None,
    long_topic: Optional[str] = None,
    long_count: Optional[int] = None,
) -> Tuple[str, str, List[str], List[str], str]:
    llm_order = (config.get("providers") or {}).get("llm_order") or ["gemini", "groq", "local"]

    if kind == "short":
        local_title, local_desc, local_tags, local_hash = _local_short_metadata(config, question or "Quick quiz!")
        payload = {"question": question or "", "category": category or "general", "style": "short quiz"}
        prompt = _meta_prompt(kind, payload)
    else:
        topic = long_topic or (category or "general knowledge")
        count = int(long_count or 30)
        local_title, local_desc, local_tags, local_hash = _local_long_metadata(config, topic, count)
        payload = {"topic": topic, "count": count, "style": "quiz compilation"}
        prompt = _meta_prompt(kind, payload)

    for prov in llm_order:
        try:
            if prov == "gemini" and secrets.gemini_api_key:
                res = GeminiClient(api_key=secrets.gemini_api_key).generate_json(prompt)
            elif prov == "groq" and secrets.groq_api_key:
                res = GroqClient(api_key=secrets.groq_api_key).generate_json(prompt)
            else:
                continue

            data = res.data or {}
            title = str(data.get("title") or "").strip()[:95]
            desc = str(data.get("description") or "").strip()[:4900]
            tags = data.get("tags") if isinstance(data.get("tags"), list) else None
            hashtags = data.get("hashtags") if isinstance(data.get("hashtags"), list) else None

            if not title or not desc:
                raise ValueError("missing title/description")

            tags_out = [str(t).strip() for t in (tags or []) if str(t).strip()]
            hashtags_out = [str(h).strip() for h in (hashtags or []) if str(h).strip().startswith("#")]

            tags_out = tags_out[:12] if tags_out else local_tags
            hashtags_out = hashtags_out[:8] if hashtags_out else local_hash

            # append hashtags to description naturally if not included
            if hashtags_out:
                joined = " ".join(hashtags_out)
                if joined not in desc:
                    desc = (desc + "\n\n" + joined)[:4900]

            return title, desc, tags_out, hashtags_out, res.provider
        except Exception as e:
            logger.warning("metadata generation failed provider=%s err=%s", prov, e)

    return local_title, local_desc, local_tags, local_hash, "local"

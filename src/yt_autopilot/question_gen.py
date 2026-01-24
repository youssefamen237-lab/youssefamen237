\
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from .db import QuestionItem, fetch_recent_questions, find_duplicate_question, insert_question, normalize_text
from .llm_clients import GeminiClient, GroqClient
from .safety import basic_safety_check
from .templates import (
    TEMPLATES,
    llm_prompt_for_template,
    local_emoji_word,
    local_left_right_diff,
    local_quick_math,
    local_sports_prediction,
)
from .utils.random_utils import weighted_choice

logger = logging.getLogger(__name__)


def _validate_item(template_id: str, data: Dict[str, Any]) -> Tuple[str, str, Optional[List[str]], str, str]:
    q = str(data.get("question") or "").strip()
    a = str(data.get("answer") or "").strip()
    cat = str(data.get("category") or "general").strip()
    diff = str(data.get("difficulty") or "easy").strip().lower()
    if diff not in {"easy", "medium", "hard"}:
        diff = "easy"

    opts = None
    if TEMPLATES[template_id].supports_options:
        o = data.get("options")
        if not isinstance(o, list) or not o:
            raise ValueError("options missing")
        opts = [str(x).strip() for x in o if str(x).strip()]
        if template_id == "mcq" and len(opts) != 4:
            raise ValueError("mcq must have 4 options")
        if template_id == "true_false":
            opts = ["True", "False"]
            a = "True" if a.lower().startswith("t") else "False"
        if template_id == "odd_one_out":
            if a not in opts:
                raise ValueError("answer must be one of options")
    return q, a, opts, cat, diff


def _too_similar_to_recent(question: str, recent: List[Dict[str, Any]], threshold: int = 92) -> bool:
    nq = normalize_text(question)
    for r in recent:
        rq = normalize_text(r.get("question") or "")
        if not rq:
            continue
        if fuzz.ratio(nq, rq) >= threshold:
            return True
    return False


def generate_question(config: Dict[str, Any], secrets: Any) -> Tuple[int, QuestionItem]:
    content_cfg = config.get("content") or {}
    days = int(content_cfg.get("min_days_before_repeat", 15))
    max_attempts = int(content_cfg.get("max_generation_attempts", 8))

    template_weights = (config.get("templates") or {}).get("weights") or {}
    llm_order = (config.get("providers") or {}).get("llm_order") or ["gemini", "groq", "local"]

    recent = fetch_recent_questions(days)

    for attempt in range(max_attempts):
        template_id = weighted_choice({k: float(v) for k, v in template_weights.items() if k in TEMPLATES})

        spec = TEMPLATES.get(template_id)
        if not spec:
            continue

        item: Optional[QuestionItem] = None

        if spec.requires_llm:
            prompt = llm_prompt_for_template(template_id)
            for prov in llm_order:
                try:
                    if prov == "gemini" and secrets.gemini_api_key:
                        client = GeminiClient(api_key=secrets.gemini_api_key)
                        res = client.generate_json(prompt)
                    elif prov == "groq" and secrets.groq_api_key:
                        client = GroqClient(api_key=secrets.groq_api_key)
                        res = client.generate_json(prompt)
                    elif prov == "local":
                        raise RuntimeError("local fallback for llm templates")
                    else:
                        continue

                    if str(res.data.get("template") or template_id).strip() not in {template_id, ""}:
                        res.data["template"] = template_id

                    q, a, opts, cat, diff = _validate_item(template_id, res.data)

                    if len(q) > 120:
                        raise ValueError("question too long")
                    if len(a) > 60:
                        raise ValueError("answer too long")

                    if not basic_safety_check(q, a, config):
                        raise ValueError("failed safety check")

                    if find_duplicate_question(q, a, days):
                        raise ValueError("duplicate hash")

                    if _too_similar_to_recent(q, recent):
                        raise ValueError("too similar")

                    item = QuestionItem(
                        template_id=template_id,
                        category=cat,
                        difficulty=diff,
                        question=q,
                        answer=a,
                        options=opts,
                        llm_provider=res.provider,
                    )
                    break
                except Exception as e:
                    logger.warning("LLM generation failed provider=%s template=%s err=%s", prov, template_id, e)

        if item is None:
            try:
                if template_id == "quick_math":
                    q, a, cat = local_quick_math()
                    item = QuestionItem(template_id=template_id, category=cat, difficulty="easy", question=q, answer=a, options=None, llm_provider="local")
                elif template_id == "left_right_diff":
                    q, a, opts, cat = local_left_right_diff()
                    item = QuestionItem(template_id=template_id, category=cat, difficulty="easy", question=q, answer=a, options=opts, llm_provider="local")
                elif template_id == "sports_prediction":
                    q, a, cat = local_sports_prediction()
                    item = QuestionItem(template_id=template_id, category=cat, difficulty="easy", question=q, answer=a, options=None, llm_provider="local")
                elif template_id == "emoji_word":
                    q, a, cat = local_emoji_word()
                    item = QuestionItem(template_id=template_id, category=cat, difficulty="easy", question=q, answer=a, options=None, llm_provider="local")
            except Exception as e:
                logger.warning("Local generation failed template=%s err=%s", template_id, e)

        if not item:
            continue

        if not basic_safety_check(item.question, item.answer, config):
            continue
        if find_duplicate_question(item.question, item.answer, days):
            continue
        if _too_similar_to_recent(item.question, recent):
            continue

        qid = insert_question(item)
        return qid, item

    raise RuntimeError("Failed to generate a safe, non-duplicate question after max attempts")

\
from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from autoyt.pipeline.content.question_bank import QuestionItem


def _pick_rotating(rng: random.Random, pool: List[str], recent: List[int], max_recent: int = 10) -> Tuple[str, int]:
    if not pool:
        return "", -1
    candidates = list(range(len(pool)))
    rng.shuffle(candidates)
    for idx in candidates:
        if idx not in recent[-max_recent:]:
            return pool[idx], idx
    # all used recently
    idx = rng.choice(list(range(len(pool))))
    return pool[idx], idx


def _pick_hashtags(rng: random.Random, pool: List[str], k: int = 5) -> str:
    pool = list(dict.fromkeys(pool))  # unique preserve order
    if len(pool) <= k:
        return " ".join(pool)
    return " ".join(rng.sample(pool, k))


def build_short_metadata(
    item: QuestionItem,
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
    rng: random.Random,
) -> Tuple[str, str, List[str]]:
    seo = cfg_base["seo"]
    hashtags = _pick_hashtags(rng, seo.get("hashtags_pool", []), k=6)

    title_tpls = seo.get("title_templates_shorts", [])
    desc_tpls = seo.get("desc_templates_shorts", [])

    cfg_state.setdefault("recent_title_tpl_ids_shorts", [])
    cfg_state.setdefault("recent_desc_tpl_ids_shorts", [])

    title_tpl, title_idx = _pick_rotating(rng, title_tpls, cfg_state["recent_title_tpl_ids_shorts"], max_recent=8)
    desc_tpl, desc_idx = _pick_rotating(rng, desc_tpls, cfg_state["recent_desc_tpl_ids_shorts"], max_recent=8)

    hook = item.hook or (item.question_text.split("\n")[0][:60])
    pct = rng.randint(8, 45)

    title = title_tpl.format(hook=hook, pct=pct).strip()
    # Ensure Shorts discoverability
    if "#shorts" not in title.lower():
        # don't force always, but often
        if rng.random() < 0.4:
            title = f"{title} #Shorts"

    # CTA comes from config; for discussion/match handled separately in render; but metadata still can include
    cta = rng.choice(cfg_base["cta"]["shorts"])
    if item.template_id == "would_you_rather":
        cta = rng.choice(cfg_base["cta"]["discussion"])
    if item.template_id == "match_prediction":
        cta = rng.choice(cfg_base["cta"]["match"])

    hook2 = hook
    desc = desc_tpl.format(
        question=item.question_text.replace("\n", " "),
        hook=hook2,
        cta=cta,
        hashtags=hashtags,
    ).strip()

    tags = [
        "quiz",
        "trivia",
        "shorts",
        "geography",
        "flags",
        "capitals",
        "fun",
        item.template_id,
        item.topic,
    ]
    tags = [t for t in tags if t]

    cfg_state["recent_title_tpl_ids_shorts"].append(title_idx)
    cfg_state["recent_desc_tpl_ids_shorts"].append(desc_idx)

    # keep lists bounded
    cfg_state["recent_title_tpl_ids_shorts"] = cfg_state["recent_title_tpl_ids_shorts"][-50:]
    cfg_state["recent_desc_tpl_ids_shorts"] = cfg_state["recent_desc_tpl_ids_shorts"][-50:]

    return title, desc, tags


def build_long_metadata(
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
    rng: random.Random,
) -> Tuple[str, str, List[str]]:
    seo = cfg_base["seo"]
    hashtags = _pick_hashtags(rng, seo.get("hashtags_pool", []), k=8)

    title_tpls = seo.get("title_templates_long", [])
    desc_tpls = seo.get("desc_templates_long", [])

    cfg_state.setdefault("recent_title_tpl_ids_long", [])
    cfg_state.setdefault("recent_desc_tpl_ids_long", [])

    title_tpl, title_idx = _pick_rotating(rng, title_tpls, cfg_state["recent_title_tpl_ids_long"], max_recent=6)
    desc_tpl, desc_idx = _pick_rotating(rng, desc_tpls, cfg_state["recent_desc_tpl_ids_long"], max_recent=6)

    title = title_tpl.strip()
    desc = desc_tpl.format(hashtags=hashtags).strip()

    tags = ["quiz", "trivia", "geography", "capitals", "flags", "education", "fun"]

    cfg_state["recent_title_tpl_ids_long"].append(title_idx)
    cfg_state["recent_desc_tpl_ids_long"].append(desc_idx)
    cfg_state["recent_title_tpl_ids_long"] = cfg_state["recent_title_tpl_ids_long"][-50:]
    cfg_state["recent_desc_tpl_ids_long"] = cfg_state["recent_desc_tpl_ids_long"][-50:]

    return title, desc, tags

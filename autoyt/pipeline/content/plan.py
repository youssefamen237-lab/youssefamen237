\
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoyt.pipeline.content.country_data import CountryDataset
from autoyt.pipeline.content.matches import Match, dupe_key_for_match, fetch_big_matches
from autoyt.pipeline.content.question_bank import GENERATOR_BY_TEMPLATE, QuestionItem
from autoyt.pipeline.storage import Storage
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.text import normalize_key

log = get_logger("autoyt.plan")


@dataclass
class DailyPlan:
    date_utc: dt.date
    shorts: List[QuestionItem]
    include_long: bool
    long_questions: List[QuestionItem]
    selected_match: Optional[Match] = None


def _weighted_choice(rng: random.Random, items: List[str], weights: List[float]) -> str:
    total = sum(max(0.0, w) for w in weights)
    if total <= 0:
        return rng.choice(items)
    r = rng.random() * total
    acc = 0.0
    for it, w in zip(items, weights):
        w = max(0.0, w)
        acc += w
        if r <= acc:
            return it
    return items[-1]


def _pick_shorts_count(cfg_base: Dict[str, Any], rng: random.Random) -> int:
    mode = int(cfg_base["content"].get("shorts_per_day_mode", 4))
    jitter = cfg_base["content"].get("shorts_per_day_jitter", {"p_3": 0.1, "p_4": 0.8, "p_5": 0.1})
    p3 = float(jitter.get("p_3", 0.1))
    p4 = float(jitter.get("p_4", 0.8))
    p5 = float(jitter.get("p_5", 0.1))
    x = rng.random()
    if x < p3:
        return 3
    if x < p3 + p4:
        return 4
    return 5


def _should_include_long(today: dt.date, cfg_base: Dict[str, Any]) -> bool:
    """
    4/week ≈ every other day.
    Strategy: publish long on Mon/Wed/Fri/Sun in target timezone by default.
    """
    # Monday=0 ... Sunday=6
    return today.weekday() in {0, 2, 4, 6}


def _make_match_item(match: Match, now_utc: dt.datetime, cta: str) -> QuestionItem:
    md = match.match_date.isoformat()
    q = f"Predict today's match:\n{match.home} vs {match.away}\n{md}\n\n{cta}"
    dupe_key = dupe_key_for_match(match.home, match.away, match.match_date)
    return QuestionItem(
        template_id="match_prediction",
        topic="football",
        dupe_key=dupe_key,
        question_text=q,
        answer_text="",
        options=None,
        hook=f"{match.home} vs {match.away}",
        meta={
            "competition": match.competition,
            "home": match.home,
            "away": match.away,
            "match_date": md,
            "kickoff_utc": match.kickoff_utc.isoformat().replace("+00:00", "Z"),
        },
    )


def build_daily_plan(
    repo_root,
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
    ds: CountryDataset,
    storage: Storage,
    now_utc: Optional[dt.datetime] = None,
) -> DailyPlan:
    now_utc = now_utc or dt.datetime.now(tz=dt.timezone.utc)
    day = now_utc.date()

    rng = random.Random(int(day.strftime("%Y%m%d")))
    shorts_count = _pick_shorts_count(cfg_base, rng)

    anti_days = int(cfg_base["content"].get("anti_duplicate_days", 15))
    recent_dupes = storage.recent_dupe_keys(days=anti_days, now=now_utc)

    # Decide if we include a match prediction among today's Shorts
    lookahead = int(cfg_base["content"].get("match_lookahead_days", 3))
    football_data_token = __import__("os").environ.get("FOOTBALL_DATA_TOKEN") or __import__("os").environ.get("FOOTBALL_DATA_ORG") or ""
    api_football_key = __import__("os").environ.get("API_FOOTBALL_KEY") or ""
    matches = fetch_big_matches(
        lookahead_days=lookahead,
        football_data_token=football_data_token or None,
        api_football_key=api_football_key or None,
        now_utc=now_utc,
    )

    selected_match: Optional[Match] = matches[0] if matches else None

    # Prepare template pools
    templates = [t["id"] for t in cfg_base.get("templates", []) if t.get("type") in {"qa", "discussion"}]
    # We handle match separately
    weights = [float(cfg_state.get("template_weights", {}).get(tid, 1.0)) for tid in templates]

    discussion_ratio = float(cfg_base["content"].get("discussion_ratio", 0.15))
    want_discussion = rng.random() < discussion_ratio

    shorts: List[QuestionItem] = []

    # If a big match exists, include 1 match short (but never exceed 1/day)
    if selected_match:
        cta_match = rng.choice(cfg_base["cta"]["match"])
        mi = _make_match_item(selected_match, now_utc=now_utc, cta=cta_match)
        # Ensure no dupe
        if mi.dupe_key not in recent_dupes:
            shorts.append(mi)
            recent_dupes.add(mi.dupe_key)

    # Fill the rest
    max_attempts = 500
    attempts = 0
    while len(shorts) < shorts_count and attempts < max_attempts:
        attempts += 1

        # Force at least one discussion question if desired
        if want_discussion and not any(s.template_id == "would_you_rather" for s in shorts):
            pick = "would_you_rather"
        else:
            pick = _weighted_choice(rng, templates, weights)

        gen = GENERATOR_BY_TEMPLATE.get(pick)
        if not gen:
            continue
        qi = gen(ds, recent_dupes, rng)
        if qi.dupe_key in recent_dupes:
            continue

        shorts.append(qi)
        recent_dupes.add(qi.dupe_key)

        # Avoid too many discussion questions
        if sum(1 for s in shorts if s.template_id == "would_you_rather") >= 2:
            want_discussion = False

    if len(shorts) < shorts_count:
        log.warning(f"Only generated {len(shorts)}/{shorts_count} shorts due to anti-duplicate constraints.")

    include_long = _should_include_long(day, cfg_base)

    # For long: create questions_per_video questions, mostly capitals/flags/continents
    long_questions: List[QuestionItem] = []
    if include_long:
        qn = int(cfg_base["rendering"]["long"].get("questions_per_video", 30))
        # Use a different seed so shorts and long don't overlap too much
        rng_long = random.Random(int(day.strftime("%Y%m%d")) + 999)
        for _ in range(qn):
            # Prefer non-discussion for long
            pool = [tid for tid in templates if tid != "would_you_rather"]
            pool_w = [float(cfg_state.get("template_weights", {}).get(tid, 1.0)) for tid in pool]
            tid = _weighted_choice(rng_long, pool, pool_w)
            gen = GENERATOR_BY_TEMPLATE.get(tid)
            if not gen:
                continue
            qi = gen(ds, recent_dupes, rng_long)
            # For long, allow some repeats but still avoid same capital/flag too recently
            if qi.dupe_key in recent_dupes:
                continue
            long_questions.append(qi)
            recent_dupes.add(qi.dupe_key)
            if len(long_questions) >= qn:
                break

    return DailyPlan(
        date_utc=day,
        shorts=shorts,
        include_long=include_long,
        long_questions=long_questions,
        selected_match=selected_match,
    )

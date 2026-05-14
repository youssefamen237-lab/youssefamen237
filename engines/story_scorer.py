"""
engines/story_scorer.py
Karma Vault Stories — Story Scoring & Ranking Engine
Batch-scores all candidates across 7 dimensions using the writing model.
Applies adaptive heuristic weights from the self-learning analytics brain.
Selects the single best story for today's video.
"""

import json
import random
from datetime import datetime, timezone
from typing import Optional

from config.constants import (
    ContentPillar, STORY_SCORE_DIMENSIONS, STORY_SCORE_MAX,
    STORY_PASS_THRESHOLD, CONTENT_PILLAR_WEIGHTS_DEFAULT,
)
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import load_heuristics
from utils.api_client import call_writing_model

log = get_logger(__name__)

# Batch size: score this many candidates per AI call to save tokens/cost
_SCORE_BATCH_SIZE = 10
# Minimum summary length to send to scorer (too short = bad score)
_MIN_SUMMARY_CHARS = 30


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_story_scorer(ctx: DailyRunContext) -> DailyRunContext:
    """
    Scores all ctx.raw_candidates, applies heuristic pillar weights,
    selects the best story, and writes results to ctx.scored_candidates
    and ctx.selected_story.
    """
    log.info(f"Story scorer starting. Candidates to score: {len(ctx.raw_candidates)}")

    if not ctx.raw_candidates:
        log.error("No candidates to score. Aborting scorer.")
        ctx.mark_stage("story_scorer_empty")
        return ctx

    heuristics = load_heuristics()

    # Pre-filter: remove candidates with no usable content
    viable = [
        c for c in ctx.raw_candidates
        if len((c.summary or c.title or "")) >= _MIN_SUMMARY_CHARS
    ]
    log.info(f"Viable candidates after pre-filter: {len(viable)}")

    # Score in batches
    scored: list[StoryCandidate] = []
    batches = _chunk(viable, _SCORE_BATCH_SIZE)

    for batch_idx, batch in enumerate(batches):
        log.info(f"Scoring batch {batch_idx + 1}/{len(batches)} "
                 f"({len(batch)} candidates)...")
        try:
            batch_scored = _score_batch(batch)
            scored.extend(batch_scored)
        except Exception as exc:
            log.warning(f"Batch {batch_idx + 1} scoring failed: {exc}. "
                        f"Applying fallback heuristic scores.")
            fallback = _apply_fallback_scores(batch)
            scored.extend(fallback)

    # Apply adaptive heuristic pillar weight multipliers
    scored = _apply_heuristic_weights(scored, heuristics)

    # Apply recency bonus: prefer stories from live sources over banks
    scored = _apply_freshness_bonus(scored)

    # Sort descending by weighted_score
    scored.sort(key=lambda c: c.weighted_score, reverse=True)

    # Assign rank
    for rank, candidate in enumerate(scored, start=1):
        candidate.selection_rank = rank

    ctx.scored_candidates = scored
    log.info(f"Scoring complete. Top 5 scores: "
             f"{[round(c.weighted_score, 2) for c in scored[:5]]}")

    # Select today's story
    selected = _select_best_story(scored, ctx)
    ctx.selected_story = selected

    if selected:
        log.info(
            f"✓ TODAY'S STORY SELECTED: '{selected.title[:70]}' "
            f"[score={selected.weighted_score:.2f}, pillar={selected.pillar}, "
            f"country={selected.country}]"
        )
    else:
        log.error("No story passed the scoring threshold. Pipeline will attempt "
                  "to use the highest-ranked available candidate.")
        if scored:
            ctx.selected_story = scored[0]
            log.warning(f"Fallback story: '{scored[0].title[:70]}' "
                        f"[score={scored[0].weighted_score:.2f}]")

    ctx.mark_stage("story_scorer")
    return ctx


# ─────────────────────────────────────────────
# BATCH AI SCORING
# ─────────────────────────────────────────────

def _score_batch(batch: list[StoryCandidate]) -> list[StoryCandidate]:
    """
    Sends one AI call for the entire batch.
    Returns the same candidates with .scores and .weighted_score populated.
    """
    batch_input = _build_batch_prompt_input(batch)

    system_prompt = _SCORER_SYSTEM_PROMPT
    user_prompt = (
        f"Score these {len(batch)} story candidates for a dark documentary "
        f"YouTube channel. Return a JSON array with one object per story.\n\n"
        f"{batch_input}\n\n"
        f"Return ONLY a valid JSON array. No markdown. No explanation.\n"
        f"Each object must have: story_index (int), scores (object with keys: "
        f"curiosity, shock, retention, title_potential, thumb_potential, "
        f"uniqueness, advertiser_safety — each a float 0-10), "
        f"rationale (one sentence string)."
    )

    raw = call_writing_model(
        system_prompt, user_prompt,
        max_tokens=2000,
        temperature=0.3,
        json_output=True,
    )

    score_results = _parse_score_response(raw, len(batch))

    for result in score_results:
        idx = result.get("story_index", -1)
        if idx < 0 or idx >= len(batch):
            continue
        candidate = batch[idx]
        raw_scores: dict = result.get("scores", {})
        candidate.scores = {
            dim: float(raw_scores.get(dim, 5.0))
            for dim in STORY_SCORE_DIMENSIONS
        }
        candidate.weighted_score = _compute_weighted_score(candidate.scores)
        candidate.score_rationale = result.get("rationale", "")

    # Any unscored candidates get fallback
    for candidate in batch:
        if not candidate.scores:
            candidate.scores = {dim: 5.0 for dim in STORY_SCORE_DIMENSIONS}
            candidate.weighted_score = 5.0
            candidate.score_rationale = "fallback_score"

    return batch


def _build_batch_prompt_input(batch: list[StoryCandidate]) -> str:
    lines = []
    for idx, c in enumerate(batch):
        text = (c.summary or c.title or "")[:400]
        lines.append(
            f"STORY {idx}:\n"
            f"  Title: {c.title[:120]}\n"
            f"  Pillar: {c.pillar}\n"
            f"  Country: {c.country}\n"
            f"  Summary: {text}"
        )
    return "\n\n".join(lines)


def _parse_score_response(raw: str, expected_count: int) -> list[dict]:
    """Parses AI response into list of score dicts. Robust to malformed output."""
    raw_clean = raw.strip()

    # Strip markdown fences if present
    if "```" in raw_clean:
        parts = raw_clean.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw_clean = part
                break

    # Find the JSON array boundaries
    start = raw_clean.find("[")
    end   = raw_clean.rfind("]") + 1
    if start >= 0 and end > start:
        raw_clean = raw_clean[start:end]

    try:
        parsed = json.loads(raw_clean)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    log.warning(f"Score response parse failed — raw length={len(raw)}. "
                f"Using fallback scores for this batch.")
    # Return fallback structure
    return [
        {
            "story_index": i,
            "scores": {dim: 5.0 for dim in STORY_SCORE_DIMENSIONS},
            "rationale": "parse_fallback",
        }
        for i in range(expected_count)
    ]


# ─────────────────────────────────────────────
# WEIGHTED SCORE COMPUTATION
# ─────────────────────────────────────────────

# Dimension weights — higher = more important for this channel
_DIMENSION_WEIGHTS: dict[str, float] = {
    "curiosity":         0.22,
    "shock":             0.18,
    "retention":         0.20,
    "title_potential":   0.15,
    "thumb_potential":   0.10,
    "uniqueness":        0.10,
    "advertiser_safety": 0.05,
}

assert abs(sum(_DIMENSION_WEIGHTS.values()) - 1.0) < 0.001, \
    "Dimension weights must sum to 1.0"


def _compute_weighted_score(scores: dict) -> float:
    total = 0.0
    for dim, weight in _DIMENSION_WEIGHTS.items():
        total += scores.get(dim, 5.0) * weight
    return round(total, 3)


# ─────────────────────────────────────────────
# HEURISTIC WEIGHT APPLICATION
# ─────────────────────────────────────────────

def _apply_heuristic_weights(
    candidates: list[StoryCandidate],
    heuristics: dict,
) -> list[StoryCandidate]:
    """
    Boosts or dampens scores based on the analytics brain's pillar performance data.
    A pillar with consistently high watch time gets a multiplier > 1.0.
    A pillar that under-performs gets a multiplier < 1.0.
    """
    pillar_weights: dict = heuristics.get("pillar_weights", {})
    if not pillar_weights:
        return candidates

    # Normalize pillar weights to a multiplier range [0.75, 1.25]
    max_w = max(pillar_weights.values()) if pillar_weights.values() else 1.0
    min_w = min(pillar_weights.values()) if pillar_weights.values() else 0.0
    w_range = max_w - min_w if max_w != min_w else 1.0

    for candidate in candidates:
        raw_pillar_weight = pillar_weights.get(
            candidate.pillar,
            CONTENT_PILLAR_WEIGHTS_DEFAULT.get(
                ContentPillar(candidate.pillar),
                0.1
            )
        )
        # Normalize to [0.75, 1.25]
        normalized = 0.75 + 0.5 * (raw_pillar_weight - min_w) / w_range
        candidate.weighted_score = round(candidate.weighted_score * normalized, 3)

    return candidates


def _apply_freshness_bonus(
    candidates: list[StoryCandidate],
) -> list[StoryCandidate]:
    """
    Gives a +0.3 bonus to live-collected stories (not from bank).
    Encourages fresh content while still allowing bank stories to compete.
    """
    for c in candidates:
        if not c.is_from_bank:
            c.weighted_score = round(c.weighted_score + 0.3, 3)
    return candidates


# ─────────────────────────────────────────────
# STORY SELECTION
# ─────────────────────────────────────────────

def _select_best_story(
    scored: list[StoryCandidate],
    ctx: DailyRunContext,
) -> Optional[StoryCandidate]:
    """
    Selects the best story subject to:
    - Passes STORY_PASS_THRESHOLD (or best available)
    - Matches force_pillar if specified
    - Not previously used (already filtered earlier)
    - Rotates pillars — avoids using same pillar 3 days in a row
    """
    if not scored:
        return None

    # Apply force_pillar filter
    pool = scored
    if ctx.force_pillar:
        pillar_pool = [c for c in scored if c.pillar == ctx.force_pillar]
        if pillar_pool:
            pool = pillar_pool
        else:
            log.warning(f"force_pillar='{ctx.force_pillar}' yielded no candidates. "
                        f"Using full ranked pool.")

    # Apply pillar rotation: if today's top story shares pillar with
    # recent analytics, gently demote it (not a hard block)
    pool = _apply_pillar_rotation_nudge(pool)

    # Select top-scoring story that passes threshold
    passing = [c for c in pool if c.weighted_score >= STORY_PASS_THRESHOLD]

    if passing:
        selected = passing[0]
        selected.is_selected = True
        return selected

    # No story passes threshold — take best available
    if pool:
        best = pool[0]
        best.is_selected = True
        return best

    return None


def _apply_pillar_rotation_nudge(
    candidates: list[StoryCandidate],
) -> list[StoryCandidate]:
    """
    Loads recent publication log and gently demotes the pillar used
    in the last 2 videos. This ensures content variety without forcing
    the system into a weaker story.
    """
    try:
        from utils.file_manager import load_publication_log
        log_entries = load_publication_log()
        recent_pillars = [e.get("pillar") for e in log_entries[-2:] if e.get("pillar")]

        if not recent_pillars:
            return candidates

        result = []
        for c in candidates:
            if c.pillar in recent_pillars:
                # Gently demote — reduce score by 0.5 to nudge diversity
                c_copy = StoryCandidate(**{k: getattr(c, k) for k in c.__dataclass_fields__})
                c_copy.weighted_score = max(0, c_copy.weighted_score - 0.5)
                result.append(c_copy)
            else:
                result.append(c)

        result.sort(key=lambda x: x.weighted_score, reverse=True)
        return result
    except Exception:
        return candidates


# ─────────────────────────────────────────────
# FALLBACK SCORING (when AI is unavailable)
# ─────────────────────────────────────────────

def _apply_fallback_scores(
    batch: list[StoryCandidate],
) -> list[StoryCandidate]:
    """
    Assigns heuristic scores when all AI providers are down.
    Uses keyword signals from the title/summary to estimate quality.
    """
    HIGH_SIGNAL_TERMS = {
        "shock", "disappear", "murder", "secret", "haunted", "body",
        "betrayal", "cult", "possessed", "missing", "confession", "ritual",
        "horror", "dark", "revealed", "hidden", "truth", "jinn", "ghost",
        "killed", "escape", "trap", "nobody knew", "no one survived",
    }
    for candidate in batch:
        text  = (candidate.title + " " + candidate.summary).lower()
        hits  = sum(1 for term in HIGH_SIGNAL_TERMS if term in text)
        score = min(10.0, 4.0 + hits * 0.6)

        candidate.scores = {dim: score for dim in STORY_SCORE_DIMENSIONS}
        # Advertiser safety slightly lower for very dark content
        candidate.scores["advertiser_safety"] = max(3.0, score - 2.0)
        candidate.weighted_score = _compute_weighted_score(candidate.scores)
        candidate.score_rationale = "keyword_fallback_no_ai"
    return batch


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


# ─────────────────────────────────────────────
# SCORING SYSTEM PROMPT
# ─────────────────────────────────────────────

_SCORER_SYSTEM_PROMPT = """You are the story scoring engine for Karma Vault Stories, a faceless dark documentary YouTube channel targeting 18-45 year old English-speaking global audiences who love true dark stories, paranormal files, betrayal dramas, mystery disappearances, and horror narratives.

You score story candidates to select the most viral, retainable story for a daily video.

Score each story on exactly these 7 dimensions (0-10 float):

curiosity: Does the title/hook create an irresistible need to know what happens next?
shock: How disturbing, surprising, or deeply unsettling is the core incident?
retention: Will the story hold viewers for 8-12 minutes? Is there enough layered detail and escalating tension?
title_potential: How viral and click-worthy can a YouTube title about this story be?
thumb_potential: How strong is the visual concept for a dark documentary thumbnail?
uniqueness: Is this story fresh and not massively over-covered on YouTube?
advertiser_safety: Can this run monetized ads? (10=safe, 0=extreme/unmonetizable gore)

A good story for this channel:
- Has a genuine dark mystery or disturbing truth at its core
- Can sustain 8-10 minutes of engaging documentary narration
- Has a strong hook within the first 30 seconds
- Has at least 3 natural twist/reveal moments
- Is grounded in real events or inspired by real events (not pure fiction)

Score strictly. A 9/10 story is genuinely exceptional viral material. A 5/10 is passable but forgettable. A 3/10 should not be produced."""

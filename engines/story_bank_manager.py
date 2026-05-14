"""
engines/story_bank_manager.py
Karma Vault Stories — Verified Story Bank Manager
Manages the 5 persistent story banks across all pipeline runs:
  - verified_real_cases
  - paranormal_legends
  - inspired_confessions
  - historical_incidents
  - evergreen_dark_stories

Banks persist across GitHub Actions runs via cache.
Provides candidate retrieval, deduplication, and bank enrichment from scored stories.
"""

import random
from datetime import datetime, timezone
from typing import Optional

from config.constants import (
    ContentPillar, STORY_BANK_FILES,
    MIN_STORY_CANDIDATES, MAX_STORY_CANDIDATES,
)
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import (
    load_story_bank, save_story_bank,
    story_id_from_content, get_used_story_ids, mark_story_used,
    load_json, save_json,
)

log = get_logger(__name__)

# ─────────────────────────────────────────────
# BANK KEY → PILLAR MAPPING
# ─────────────────────────────────────────────

_BANK_PILLAR_MAP: dict[str, list[str]] = {
    "verified_real": [
        ContentPillar.TRUE_SHOCKING.value,
        ContentPillar.HUMAN_BETRAYAL.value,
        ContentPillar.MYSTERY_DISAPPEARANCE.value,
        ContentPillar.DISTURBING_ACCIDENTS.value,
    ],
    "paranormal": [
        ContentPillar.PARANORMAL.value,
        ContentPillar.URBAN_LEGENDS.value,
    ],
    "confessions": [
        ContentPillar.INTERNET_CONFESSION.value,
        ContentPillar.SECRET_DOUBLE_LIFE.value,
    ],
    "historical": [
        ContentPillar.HISTORICAL_DARK.value,
    ],
    "evergreen": [
        ContentPillar.TRUE_SHOCKING.value,
        ContentPillar.PARANORMAL.value,
        ContentPillar.HUMAN_BETRAYAL.value,
        ContentPillar.AI_HORROR.value,
        ContentPillar.URBAN_LEGENDS.value,
        ContentPillar.MYSTERY_DISAPPEARANCE.value,
    ],
}

# Minimum score to persist a story into the evergreen bank
_BANK_PERSIST_MIN_SCORE = 6.0
# Maximum stories per bank before we trim oldest
_BANK_MAX_SIZE = 300


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_story_bank_manager(ctx: DailyRunContext) -> DailyRunContext:
    """
    Merges the 5 persistent story banks into ctx.raw_candidates
    (up to MAX_STORY_CANDIDATES total), adding fresh bank stories
    that haven't been used yet.

    Also persists any high-scoring newly discovered stories back
    into the appropriate bank for future reuse.
    """
    log.info("Story bank manager starting...")
    used_ids = get_used_story_ids()
    existing_ids = {c.id for c in ctx.raw_candidates}
    all_skip = used_ids | existing_ids

    bank_candidates = _pull_bank_candidates(ctx, all_skip)
    log.info(f"Bank candidates pulled: {len(bank_candidates)}")

    # Merge into raw_candidates — bank stories have is_from_bank=True
    ctx.raw_candidates.extend(bank_candidates)

    # Enforce MIN/MAX bounds
    if len(ctx.raw_candidates) < MIN_STORY_CANDIDATES:
        log.warning(
            f"Only {len(ctx.raw_candidates)} candidates collected — "
            f"below minimum {MIN_STORY_CANDIDATES}. "
            f"Pipeline will proceed but story quality may be limited."
        )

    ctx.raw_candidates = ctx.raw_candidates[:MAX_STORY_CANDIDATES]
    log.info(f"Total candidates after bank merge: {len(ctx.raw_candidates)}")
    ctx.mark_stage("story_bank_manager")
    return ctx


def enrich_banks_after_scoring(ctx: DailyRunContext) -> None:
    """
    Called after scoring. Saves newly discovered high-quality stories
    into the appropriate persistent bank for future pipeline runs.
    Not blocking — failures are logged but don't kill the run.
    """
    if not ctx.scored_candidates:
        return

    enriched_count = 0
    for candidate in ctx.scored_candidates:
        if candidate.is_from_bank:
            continue  # already in bank, skip
        if candidate.weighted_score < _BANK_PERSIST_MIN_SCORE:
            continue

        bank_key = _pillar_to_bank_key(candidate.pillar)
        if not bank_key:
            continue

        try:
            bank = load_story_bank(bank_key)
            # Check if already exists in bank
            existing_ids_in_bank = {s.get("id", "") for s in bank}
            if candidate.id in existing_ids_in_bank:
                continue

            story_dict = candidate.to_dict()
            story_dict["persisted_at"] = datetime.now(timezone.utc).isoformat()
            story_dict["persist_score"] = candidate.weighted_score
            bank.append(story_dict)

            # Trim bank if too large (keep highest-scored)
            if len(bank) > _BANK_MAX_SIZE:
                bank = sorted(
                    bank,
                    key=lambda s: s.get("weighted_score", 0),
                    reverse=True,
                )[:_BANK_MAX_SIZE]

            save_story_bank(bank_key, bank)
            enriched_count += 1
        except Exception as exc:
            log.warning(f"Failed to persist story '{candidate.title[:40]}' to bank '{bank_key}': {exc}")

    if enriched_count:
        log.info(f"Bank enrichment complete. {enriched_count} new stories persisted.")


def mark_selected_story_used(ctx: DailyRunContext) -> None:
    """Marks the selected story ID as used so it never repeats."""
    if ctx.selected_story:
        mark_story_used(ctx.selected_story.id)
        log.info(f"Marked story as used: {ctx.selected_story.id}")


def get_all_bank_stats() -> dict:
    """Returns size stats for all 5 banks. Used for monitoring."""
    stats = {}
    for key in STORY_BANK_FILES:
        if key == "used_ids":
            used = load_json(STORY_BANK_FILES[key], default=[])
            stats["used_story_count"] = len(used)
        else:
            bank = load_story_bank(key)
            stats[f"bank_{key}_size"] = len(bank)
    return stats


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _pull_bank_candidates(
    ctx: DailyRunContext, skip_ids: set
) -> list[StoryCandidate]:
    """
    Pulls up to 15 stories from banks that:
    - Have not been used (not in skip_ids)
    - Match the forced pillar if specified, or any pillar
    - Are biased toward pillars with higher current heuristic weights
    """
    all_bank_candidates: list[StoryCandidate] = []

    for bank_key, pillars in _BANK_PILLAR_MAP.items():
        # Skip pillar mismatch when force_pillar is set
        if ctx.force_pillar and ctx.force_pillar not in pillars:
            continue

        bank = load_story_bank(bank_key)
        if not bank:
            continue

        # Shuffle and pull fresh stories
        random.shuffle(bank)
        pulled = 0
        for story_dict in bank:
            story_id = story_dict.get("id", "")
            if not story_id or story_id in skip_ids:
                continue
            if story_dict.get("used", False):
                continue

            try:
                candidate = StoryCandidate.from_dict({
                    "id":           story_dict.get("id", ""),
                    "title":        story_dict.get("title", ""),
                    "summary":      story_dict.get("summary", ""),
                    "raw_content":  story_dict.get("raw_content", story_dict.get("summary", "")),
                    "source":       story_dict.get("source", f"bank_{bank_key}"),
                    "source_url":   story_dict.get("source_url", ""),
                    "country":      story_dict.get("country", "Unknown"),
                    "pillar":       story_dict.get("pillar", pillars[0]),
                    "story_label":  story_dict.get("story_label", "TRUE STORY"),
                    "collected_at": story_dict.get("collected_at", ""),
                    "is_from_bank": True,
                    "used":         False,
                    "scores":       story_dict.get("scores", {}),
                    "weighted_score": story_dict.get("weighted_score", 0.0),
                })
                all_bank_candidates.append(candidate)
                skip_ids.add(story_id)   # prevent duplicates within this pull
                pulled += 1
                if pulled >= 4:          # max 4 per bank per run
                    break
            except Exception as exc:
                log.warning(f"Malformed bank story skipped: {exc}")

    return all_bank_candidates[:15]


def _pillar_to_bank_key(pillar: str) -> Optional[str]:
    """Maps a pillar value to the most appropriate bank key."""
    for bank_key, pillars in _BANK_PILLAR_MAP.items():
        if pillar in pillars:
            # Prefer specific banks over evergreen
            if bank_key != "evergreen":
                return bank_key
    # Fall back to evergreen for misc pillars
    return "evergreen"

"""
video/template_engine.py – Quizzaro Template Engine
=====================================================
Manages the 8 Short templates.  Responsibilities:
  1. Select the next template using weighted rotation (no streak > 2)
  2. Read strategy_config.json to weight top-performing templates higher
  3. Return a TemplateConfig object that VideoComposer uses to
     parameterise the frame renderer (which template-specific UI to draw)

The actual pixel-level drawing happens inside video_renderer.py (_render_frame).
This module owns the *selection logic* and *configuration contract*.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")

ALL_TEMPLATES = [
    "true_false",
    "multiple_choice",
    "direct_question",
    "guess_answer",
    "quick_challenge",
    "only_geniuses",
    "memory_test",
    "visual_question",
]

# Default weights (equal). Overridden by strategy_config.
BASE_WEIGHTS = {t: 1.0 for t in ALL_TEMPLATES}


@dataclass
class TemplateConfig:
    name: str               # e.g. "multiple_choice"
    show_options: bool      # True for multiple_choice, true_false
    option_count: int       # 4 for MC, 2 for T/F, 0 for others
    badge_label: str        # Text shown in the top badge
    timer_seconds: int      # Always 5 in this project
    answer_seconds: int     # Always 5 in this project


TEMPLATE_CONFIGS: dict[str, TemplateConfig] = {
    "true_false": TemplateConfig(
        name="true_false", show_options=True, option_count=2,
        badge_label="TRUE OR FALSE?", timer_seconds=5, answer_seconds=5,
    ),
    "multiple_choice": TemplateConfig(
        name="multiple_choice", show_options=True, option_count=4,
        badge_label="MULTIPLE CHOICE", timer_seconds=5, answer_seconds=5,
    ),
    "direct_question": TemplateConfig(
        name="direct_question", show_options=False, option_count=0,
        badge_label="QUICK QUESTION", timer_seconds=5, answer_seconds=5,
    ),
    "guess_answer": TemplateConfig(
        name="guess_answer", show_options=False, option_count=0,
        badge_label="GUESS THE ANSWER", timer_seconds=5, answer_seconds=5,
    ),
    "quick_challenge": TemplateConfig(
        name="quick_challenge", show_options=False, option_count=0,
        badge_label="⚡ QUICK CHALLENGE", timer_seconds=5, answer_seconds=5,
    ),
    "only_geniuses": TemplateConfig(
        name="only_geniuses", show_options=False, option_count=0,
        badge_label="🧠 ONLY GENIUSES", timer_seconds=5, answer_seconds=5,
    ),
    "memory_test": TemplateConfig(
        name="memory_test", show_options=False, option_count=0,
        badge_label="🔁 MEMORY TEST", timer_seconds=5, answer_seconds=5,
    ),
    "visual_question": TemplateConfig(
        name="visual_question", show_options=False, option_count=0,
        badge_label="👁 VISUAL QUIZ", timer_seconds=5, answer_seconds=5,
    ),
}


class TemplateEngine:

    def __init__(self) -> None:
        self._history: list[str] = []

    def _load_weights(self) -> dict[str, float]:
        weights = BASE_WEIGHTS.copy()
        if STRATEGY_CONFIG_PATH.exists():
            try:
                cfg = json.loads(STRATEGY_CONFIG_PATH.read_text())
                top = cfg.get("top_templates", [])
                bad = set(cfg.get("underperforming_templates", []))
                for t in top[:3]:
                    if t in weights:
                        weights[t] = 3.0     # 3× boost for top performers
                for t in bad:
                    if t in weights:
                        weights[t] = 0.3     # suppress underperformers
            except Exception:
                pass
        return weights

    def pick_template(self) -> TemplateConfig:
        """
        Weighted random selection that suppresses any template used
        more than twice in the last 8 picks (streak prevention).
        """
        weights = self._load_weights()
        recent = self._history[-8:]
        streak_counts: dict[str, int] = {}
        for t in recent:
            streak_counts[t] = streak_counts.get(t, 0) + 1

        # Zero-weight any template at streak ≥ 2
        adjusted = {
            t: (w if streak_counts.get(t, 0) < 2 else 0.0)
            for t, w in weights.items()
        }

        # If all zeroed (shouldn't happen), reset
        if sum(adjusted.values()) == 0:
            adjusted = weights.copy()

        templates = list(adjusted.keys())
        ws = [adjusted[t] for t in templates]
        chosen = random.choices(templates, weights=ws, k=1)[0]

        self._history.append(chosen)
        return TEMPLATE_CONFIGS[chosen]

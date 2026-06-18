"""
intelligence/story_flow.py

Defines the narrative structures ("Story Templates") referenced throughout
the channel constitution.  Each template breaks a video into named stages
with target duration percentages, used to guide script generation and,
later, to let the Growth Manager track which structures retain best.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class StoryStage:
    name:          str
    purpose:       str
    duration_pct:  int   # approximate % of total video duration


@dataclass
class StoryTemplate:
    template_name: str
    hook_type:     str
    stages:        List[StoryStage] = field(default_factory=list)

    def stage_names(self) -> List[str]:
        return [s.name for s in self.stages]

    def to_guidance_text(self) -> str:
        lines = [f"Story structure '{self.template_name}' ({len(self.stages)} stages):"]
        for i, s in enumerate(self.stages, start=1):
            lines.append(f"  {i}. {s.name} (~{s.duration_pct}% of video) — {s.purpose}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Templates — one per primary hook_type
# ─────────────────────────────────────────────────────────────────────────────

_TEMPLATES: Dict[str, StoryTemplate] = {

    "danger": StoryTemplate(
        template_name="danger_escalation",
        hook_type="danger",
        stages=[
            StoryStage("Hook",       "Stop the scroll with the threat itself.",          10),
            StoryStage("Threat",     "Name the subject and why it is dangerous.",        20),
            StoryStage("Fact",       "Deliver the strongest supporting fact.",           35),
            StoryStage("Result",     "Show the consequence or scale of the danger.",     25),
            StoryStage("Question",   "Leave the viewer with a provocative question.",    10),
        ],
    ),

    "mystery": StoryTemplate(
        template_name="mystery_reveal",
        hook_type="mystery",
        stages=[
            StoryStage("Hook",        "Pose the unexplained phenomenon.",                10),
            StoryStage("Question",    "Frame the central mystery explicitly.",           20),
            StoryStage("Reveal",      "Introduce the subject behind the mystery.",       30),
            StoryStage("Explanation", "Share what science currently knows (and doesn't).",30),
            StoryStage("CTA",         "Invite the viewer to think or follow for more.",  10),
        ],
    ),

    "size": StoryTemplate(
        template_name="size_comparison",
        hook_type="size",
        stages=[
            StoryStage("Hook",          "State the scale claim immediately.",            10),
            StoryStage("Comparison",    "Compare to something familiar (bus, human, etc.).",25),
            StoryStage("Fact",          "Add a supporting numerical fact.",               30),
            StoryStage("Bigger Reveal", "Escalate with an even more extreme comparison.", 25),
            StoryStage("Question",      "Ask the viewer to imagine the scale.",           10),
        ],
    ),

    "intelligence": StoryTemplate(
        template_name="intelligence_showcase",
        hook_type="intelligence",
        stages=[
            StoryStage("Hook",       "Claim the subject is smarter than expected.",      10),
            StoryStage("Behavior",   "Describe the specific intelligent behavior.",      30),
            StoryStage("Evidence",   "Cite the scientific evidence or study.",           35),
            StoryStage("Conclusion", "State what this means / why it matters.",          15),
            StoryStage("CTA",        "Prompt the viewer to follow for more discoveries.",10),
        ],
    ),

    "speed": StoryTemplate(
        template_name="speed_record",
        hook_type="speed",
        stages=[
            StoryStage("Hook",       "State the speed claim immediately.",               10),
            StoryStage("Reveal",     "Name the subject.",                                15),
            StoryStage("Fact",       "Give the precise speed figure.",                   35),
            StoryStage("Comparison", "Compare to a familiar fast object.",               30),
            StoryStage("Question",   "Challenge the viewer's intuition.",                10),
        ],
    ),

    "survival": StoryTemplate(
        template_name="survival_extreme",
        hook_type="survival",
        stages=[
            StoryStage("Hook",       "State the extreme survival claim.",                10),
            StoryStage("Reveal",     "Name the subject and its environment.",            20),
            StoryStage("Fact",       "Explain the mechanism that enables survival.",     35),
            StoryStage("Result",     "Show what this means in extreme terms.",           25),
            StoryStage("Question",   "Ask whether the viewer could endure this.",        10),
        ],
    ),

    "comparison": StoryTemplate(
        template_name="head_to_head",
        hook_type="comparison",
        stages=[
            StoryStage("Hook",        "Frame the matchup immediately.",                  10),
            StoryStage("Subject A",   "Introduce the first subject's strength.",         25),
            StoryStage("Subject B",   "Introduce the second subject's strength.",        25),
            StoryStage("Evidence",    "Give the deciding fact.",                         30),
            StoryStage("CTA",         "Ask the viewer who they think wins.",             10),
        ],
    ),
}

# Templates that share a structure with one already defined above
_ALIASES: Dict[str, str] = {
    "impossible": "mystery",
    "weirdness":  "mystery",
    "record":     "size",
    "behavior":   "intelligence",
    "discovery":  "mystery",
}


class StoryFlowEngine:

    def get_template(self, hook_type: str) -> StoryTemplate:
        key = hook_type if hook_type in _TEMPLATES else _ALIASES.get(hook_type, "danger")
        return _TEMPLATES.get(key, _TEMPLATES["danger"])

    def get_template_by_name(self, template_name: str) -> Optional[StoryTemplate]:
        for t in _TEMPLATES.values():
            if t.template_name == template_name:
                return t
        return None

    def list_templates(self) -> List[StoryTemplate]:
        return list(_TEMPLATES.values())

    def build_guidance(self, hook_type: str) -> str:
        """Return human-readable stage guidance for inclusion in an LLM prompt."""
        return self.get_template(hook_type).to_guidance_text()

    def recommended_template(self, topic_dna: Dict, category: str) -> StoryTemplate:
        """
        Pick the template whose hook_type matches the dominant topic_dna
        dimension, falling back to a category-appropriate default.
        """
        if topic_dna:
            scored = [
                (str(k).lower(), int(v))
                for k, v in topic_dna.items()
                if isinstance(v, (int, float)) and str(k).lower() in _TEMPLATES
            ]
            if scored:
                scored.sort(key=lambda kv: kv[1], reverse=True)
                top_key, top_val = scored[0]
                if top_val >= 50:
                    return _TEMPLATES[top_key]

        category_default = {
            "ocean": "danger", "animals": "danger", "space": "mystery",
            "nature": "mystery", "birds": "speed", "insects": "survival",
        }.get(category, "danger")
        return _TEMPLATES[category_default]


_instance: Optional[StoryFlowEngine] = None

def get_story_flow() -> StoryFlowEngine:
    global _instance
    if _instance is None:
        _instance = StoryFlowEngine()
    return _instance

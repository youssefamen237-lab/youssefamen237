"""
utils/models.py
Karma Vault Stories — Shared Data Models
Single authoritative definition of all pipeline data structures.
Every engine imports from here. No engine defines its own ad-hoc dicts.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
from config.constants import ContentPillar, StoryLabel


# ─────────────────────────────────────────────
# TREND SIGNAL
# ─────────────────────────────────────────────

@dataclass
class TrendSignal:
    """
    One viral trend keyword or phrase detected by the trend hunter.
    Used to bias story collection and SEO title generation.
    """
    keyword: str
    search_volume_estimate: int     # relative, not absolute
    source: str                     # "serpapi" | "tavily" | "newsapi" | "reddit" | "zenserp"
    category: str                   # "dark_news" | "viral_true_crime" | "paranormal" | "betrayal"
    region: str = "global"
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────
# STORY CANDIDATE
# ─────────────────────────────────────────────

@dataclass
class StoryCandidate:
    """
    One raw story candidate before scoring.
    Produced by story collectors, enriched by scorer, persisted by bank manager.
    """
    id: str                         # deterministic hash of title+source
    title: str
    summary: str                    # 100–500 word summary / original text
    raw_content: str                # full original text if available
    source: str                     # "reddit" | "newsapi" | "rss" | "bank_verified_real" | etc.
    source_url: str
    country: str                    # e.g. "Egypt", "USA", "India", "Unknown"
    pillar: str                     # ContentPillar value string
    story_label: str                # StoryLabel value string (with country substituted)
    collected_at: str               = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_from_bank: bool              = False
    used: bool                      = False

    # Filled by story_scorer
    scores: dict                    = field(default_factory=dict)
    weighted_score: float           = 0.0
    score_rationale: str            = ""
    is_selected: bool               = False
    selection_rank: int             = 0

    # Filled by script writer (Phase 3)
    script_blueprint: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["script_blueprint"] = self.script_blueprint
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "StoryCandidate":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def score_summary(self) -> str:
        if not self.scores:
            return "unscored"
        parts = ", ".join(f"{k}={v:.1f}" for k, v in self.scores.items())
        return f"total={self.weighted_score:.2f} [{parts}]"


# ─────────────────────────────────────────────
# DAILY RUN CONTEXT
# ─────────────────────────────────────────────

@dataclass
class DailyRunContext:
    """
    Complete state object passed through every engine in one pipeline run.
    Engines mutate this in-place; main_pipeline reads the final state.
    """
    run_id: str
    started_at: str                 = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Trend hunting output
    trend_signals: list[TrendSignal] = field(default_factory=list)
    trending_keywords: list[str]     = field(default_factory=list)

    # Story collection output
    raw_candidates: list[StoryCandidate]    = field(default_factory=list)
    scored_candidates: list[StoryCandidate] = field(default_factory=list)
    selected_story: Optional[StoryCandidate] = None

    # Script output (Phase 3)
    script_blueprint: Optional[dict]        = None
    seo_metadata: Optional[dict]            = None

    # Audio output (Phase 4)
    narration_audio_path: Optional[str]     = None
    narration_duration_sec: float           = 0.0
    voice_gender: str                       = "male"
    tts_provider_used: str                  = ""

    # Visual output (Phase 5)
    scene_assets: list[dict]                = field(default_factory=list)
    thumbnail_path: Optional[str]           = None
    thumbnail_template_id: str              = ""

    # Render output (Phase 6)
    long_video_path: Optional[str]          = None
    short_video_path: Optional[str]         = None

    # Upload output (Phase 7)
    youtube_video_id: Optional[str]         = None
    youtube_short_id: Optional[str]         = None
    yt_pack_used: int                       = 0
    upload_status: str                      = "pending"

    # Stage tracking
    stages_completed: list[str]             = field(default_factory=list)
    stage_errors: list[dict]                = field(default_factory=list)

    # Force overrides (from workflow_dispatch inputs)
    force_pillar: Optional[str]             = None
    dry_run: bool                           = False

    def mark_stage(self, stage: str) -> None:
        self.stages_completed.append(stage)

    def to_summary_dict(self) -> dict:
        return {
            "run_id":           self.run_id,
            "started_at":       self.started_at,
            "selected_story":   self.selected_story.title if self.selected_story else None,
            "pillar":           self.selected_story.pillar if self.selected_story else None,
            "country":          self.selected_story.country if self.selected_story else None,
            "voice_gender":     self.voice_gender,
            "tts_provider":     self.tts_provider_used,
            "thumbnail_tpl":    self.thumbnail_template_id,
            "youtube_video_id": self.youtube_video_id,
            "youtube_short_id": self.youtube_short_id,
            "yt_pack_used":     self.yt_pack_used,
            "upload_status":    self.upload_status,
            "stages_completed": self.stages_completed,
            "candidates_collected": len(self.raw_candidates),
            "candidates_scored":    len(self.scored_candidates),
            "errors":           len(self.stage_errors),
        }

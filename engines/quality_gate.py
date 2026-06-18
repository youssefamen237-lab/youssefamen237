"""
engines/quality_gate.py
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)

_PASS_THRESHOLD = 75
_REAL_PROVIDERS = frozenset({
    "pexels", "pixabay", "coverr", "internet_archive",
    "vecteezy", "unsplash", "pexels_photo", "pixabay_photo", "freepik",
})


@dataclass
class QualityGateInput:
    queue_id:           str
    topic_name:         str
    category:           str
    curiosity_score:    int
    visual_availability:int
    facts:              List[Dict]
    media_items:        List          # each item: MediaItem | None
    script:             Dict
    audio_path:         Optional[str]
    audio_duration:     float
    title:              Optional[str]
    description:        Optional[str]
    hashtags:           List[str]     = field(default_factory=list)


@dataclass
class QualityScore:
    total:            int
    passed:           bool
    gate_scores:      Dict[str, int]
    rejection_reason: Optional[str] = None


class QualityGate:

    def score(self, inp: QualityGateInput) -> QualityScore:
        g1 = self._gate_topic(inp)
        g2 = self._gate_facts(inp)
        g3 = self._gate_visual(inp)
        g4 = self._gate_audio_script(inp)
        g5 = self._gate_metadata(inp)

        total = g1 + g2 + g3 + g4 + g5
        passed = total >= _PASS_THRESHOLD

        gate_scores = {
            "topic":        g1,
            "facts":        g2,
            "visual":       g3,
            "audio_script": g4,
            "metadata":     g5,
        }

        rejection_reason: Optional[str] = None
        if not passed:
            weakest = min(gate_scores, key=gate_scores.get)
            rejection_reason = (
                f"Quality score {total}/100 (threshold {_PASS_THRESHOLD}). "
                f"Weakest gate: {weakest} ({gate_scores[weakest]}/20)."
            )

        logger.info(
            "quality_scored",
            queue_id=inp.queue_id[:8],
            total=total,
            passed=passed,
            gates=gate_scores,
        )
        return QualityScore(
            total=total,
            passed=passed,
            gate_scores=gate_scores,
            rejection_reason=rejection_reason,
        )

    # ── Gate 1: Topic quality ─────────────────────────────────────────────────

    @staticmethod
    def _gate_topic(inp: QualityGateInput) -> int:
        cs = inp.curiosity_score
        va = inp.visual_availability

        curiosity_pts = (
            10 if cs >= 80 else
             7 if cs >= 60 else
             5 if cs >= 40 else 2
        )
        visual_pts = (
            10 if va >= 80 else
             7 if va >= 60 else
             5 if va >= 40 else 2
        )
        return min(curiosity_pts + visual_pts, 20)

    # ── Gate 2: Facts quality ─────────────────────────────────────────────────

    @staticmethod
    def _gate_facts(inp: QualityGateInput) -> int:
        if not inp.facts:
            return 0
        qualified = [f for f in inp.facts if int(f.get("confidence_score", 0)) >= 65]
        count_pts = min(len(qualified) * 4, 10)
        confidences = [int(f.get("confidence_score", 0)) for f in inp.facts]
        avg_conf = sum(confidences) / max(len(confidences), 1)
        conf_pts = (
            10 if avg_conf >= 80 else
             7 if avg_conf >= 65 else
             4 if avg_conf >= 50 else 1
        )
        return min(count_pts + conf_pts, 20)

    # ── Gate 3: Visual quality ────────────────────────────────────────────────

    @staticmethod
    def _gate_visual(inp: QualityGateInput) -> int:
        n_total = max(len(inp.media_items), 1)
        found   = [m for m in inp.media_items if m is not None]
        n_found = len(found)

        coverage_pts = min(int((n_found / n_total) * 15), 15)

        ai_count = sum(
            1 for m in found
            if hasattr(m, "provider") and m.provider not in _REAL_PROVIDERS
        )
        ai_ratio = ai_count / max(n_found, 1)
        ai_pts = 5 if ai_ratio <= 0.4 else 3 if ai_ratio <= 0.7 else 1

        return min(coverage_pts + ai_pts, 20)

    # ── Gate 4: Audio / Script quality ───────────────────────────────────────

    @staticmethod
    def _gate_audio_script(inp: QualityGateInput) -> int:
        hook_pts = 8 if inp.script.get("hook") else 0

        dur = inp.audio_duration
        audio_pts = (
            7 if dur >= 10 else
            4 if dur >   0 else 0
        )

        seg_count = len(inp.script.get("segments", []))
        seg_pts = (
            5 if seg_count >= 3 else
            2 if seg_count >= 1 else 0
        )
        return min(hook_pts + audio_pts + seg_pts, 20)

    # ── Gate 5: Metadata quality ──────────────────────────────────────────────

    @staticmethod
    def _gate_metadata(inp: QualityGateInput) -> int:
        title = inp.title or ""
        desc  = inp.description or ""
        tags  = inp.hashtags or []

        title_pts = (
            10 if 30 <= len(title) <= 100 else
             5 if len(title) > 0          else 0
        )
        desc_pts = (
            5 if len(desc) >= 100 else
            2 if len(desc) >= 30  else 0
        )
        tag_pts = (
            5 if len(tags) >= 3 else
            2 if len(tags) >= 1 else 0
        )
        return min(title_pts + desc_pts + tag_pts, 20)


_instance: Optional[QualityGate] = None

def get_quality_gate() -> QualityGate:
    global _instance
    if _instance is None:
        _instance = QualityGate()
    return _instance

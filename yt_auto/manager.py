"""
Central Manager for analyzing content performance and optimizing strategy.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from yt_auto.config import Config
from yt_auto.youtube_uploader import YouTubeUploader


class ContentAnalyzer:
    """Analyzes video performance and provides recommendations."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.uploader = YouTubeUploader(cfg.youtube_oauths)
        self.analysis_file = cfg.state_path.parent / "analysis.json"
        self.load_analysis()

    def load_analysis(self) -> None:
        """Load previous analysis."""
        if self.analysis_file.exists():
            with open(self.analysis_file) as f:
                self.analysis = json.load(f)
        else:
            self.analysis = {
                "templates": {},
                "voices": {},
                "times": {},
                "backgrounds": {},
                "ctas": {},
                "titles": {},
                "lengths": {},
                "posting_times": {},
                "thumbnails": {},
            }

    def save_analysis(self) -> None:
        """Save analysis to file."""
        self.analysis_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.analysis_file, "w") as f:
            json.dump(self.analysis, f, indent=2)

    def analyze_short_performance(self, video_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Analyze performance of a published short."""
        try:
            stats = self.uploader.get_video_stats(video_id)

            performance_score = self._calculate_performance_score(stats)

            template = metadata.get("template", "unknown")
            self._record_metric("templates", template, performance_score)

            voice = metadata.get("voice", "unknown")
            self._record_metric("voices", voice, performance_score)

            posting_time = metadata.get("posting_time", "unknown")
            self._record_metric("posting_times", posting_time, performance_score)

            background = metadata.get("background_id", "unknown")
            self._record_metric("backgrounds", background, performance_score)

            cta = metadata.get("cta_index", 0)
            self._record_metric("ctas", str(cta), performance_score)

            title_pattern = metadata.get("title_pattern", "standard")
            self._record_metric("titles", title_pattern, performance_score)

            return {
                "video_id": video_id,
                "performance_score": performance_score,
                "views": stats.get("views", 0),
                "likes": stats.get("likes", 0),
                "comments": stats.get("comments", 0),
                "shares": stats.get("shares", 0),
                "watch_time": stats.get("watch_time", 0),
            }
        except Exception as e:
            return {
                "video_id": video_id,
                "error": str(e),
                "performance_score": 0,
            }

    def analyze_long_performance(self, video_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Analyze performance of a published long-form video."""
        try:
            stats = self.uploader.get_video_stats(video_id)

            performance_score = self._calculate_performance_score(stats, is_long=True)

            video_length = metadata.get("length_seconds", 300)
            self._record_metric("lengths", str(video_length // 60), performance_score)

            return {
                "video_id": video_id,
                "performance_score": performance_score,
                "views": stats.get("views", 0),
                "likes": stats.get("likes", 0),
                "comments": stats.get("comments", 0),
                "watch_time": stats.get("watch_time", 0),
                "average_view_duration": stats.get("average_view_duration", 0),
            }
        except Exception as e:
            return {
                "video_id": video_id,
                "error": str(e),
                "performance_score": 0,
            }

    def get_best_performers(self, category: str, limit: int = 3) -> list[str]:
        """Get best performing items in a category."""
        if category not in self.analysis:
            return []

        items = self.analysis[category]
        sorted_items = sorted(items.items(), key=lambda x: x[1].get("avg_score", 0), reverse=True)

        return [item[0] for item in sorted_items[:limit]]

    def get_recommendations(self) -> dict[str, Any]:
        """Get optimization recommendations."""
        recommendations = {
            "best_templates": self.get_best_performers("templates", limit=3),
            "best_voices": self.get_best_performers("voices", limit=2),
            "best_posting_times": self.get_best_performers("posting_times", limit=2),
            "best_ctas": self.get_best_performers("ctas", limit=3),
            "best_title_patterns": self.get_best_performers("titles", limit=2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self._generate_summary(),
        }
        return recommendations

    def _calculate_performance_score(self, stats: dict[str, Any], is_long: bool = False) -> float:
        """Calculate normalized performance score."""
        views = float(stats.get("views", 0))
        likes = float(stats.get("likes", 0))
        comments = float(stats.get("comments", 0))
        watch_time = float(stats.get("watch_time", 0))

        # Engagement rate components
        engagement_rate = (likes + comments * 2) / max(views, 1) if views > 0 else 0

        if is_long:
            avg_duration = float(stats.get("average_view_duration", 0))
            duration_score = min(avg_duration / 60, 1.0)  # Normalized to 1 minute
            score = (engagement_rate * 100) * 0.5 + duration_score * 50
        else:
            score = engagement_rate * 100

        return min(score, 100)  # Cap at 100

    def _record_metric(self, category: str, item: str, score: float) -> None:
        """Record a metric for analysis."""
        if category not in self.analysis:
            self.analysis[category] = {}

        if item not in self.analysis[category]:
            self.analysis[category][item] = {
                "scores": [],
                "count": 0,
                "avg_score": 0,
            }

        self.analysis[category][item]["scores"].append(score)
        self.analysis[category][item]["count"] += 1
        self.analysis[category][item]["avg_score"] = sum(
            self.analysis[category][item]["scores"]
        ) / len(self.analysis[category][item]["scores"])

        # Keep only last 50 scores to avoid memory issues
        if len(self.analysis[category][item]["scores"]) > 50:
            self.analysis[category][item]["scores"] = self.analysis[category][item]["scores"][-50:]

        self.save_analysis()

    def _generate_summary(self) -> str:
        """Generate summary of analysis."""
        best_template = self.get_best_performers("templates", limit=1)
        best_time = self.get_best_performers("posting_times", limit=1)
        best_voice = self.get_best_performers("voices", limit=1)

        summary = "Analysis Summary: "
        if best_template:
            summary += f"Best template: {best_template[0]}. "
        if best_time:
            summary += f"Best posting time: {best_time[0]}. "
        if best_voice:
            summary += f"Best voice: {best_voice[0]}."

        return summary


class StrategyOptimizer:
    """Automatically optimizes content strategy based on performance."""

    def __init__(self, cfg: Config, analyzer: ContentAnalyzer):
        self.cfg = cfg
        self.analyzer = analyzer
        self.strategy_file = cfg.state_path.parent / "strategy.json"
        self.load_strategy()

    def load_strategy(self) -> None:
        """Load current strategy."""
        if self.strategy_file.exists():
            with open(self.strategy_file) as f:
                self.strategy = json.load(f)
        else:
            self.strategy = self._generate_default_strategy()

    def save_strategy(self) -> None:
        """Save strategy to file."""
        self.strategy_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.strategy_file, "w") as f:
            json.dump(self.strategy, f, indent=2)

    def _generate_default_strategy(self) -> dict[str, Any]:
        """Generate default strategy."""
        return {
            "template_rotation": [
                "true_false",
                "multiple_choice",
                "direct_question",
                "guess_answer",
                "quick_challenge",
                "only_geniuses",
                "memory_test",
                "visual_question",
            ],
            "cta_rotation_index": 0,
            "voice_rotation_index": 0,
            "background_preference": "random",
            "posting_time_variance": 0.15,  # 15% variance
            "title_pattern": "varied",
            "description_style": "seo_optimized",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def optimize_for_next_content(self) -> dict[str, Any]:
        """Get optimization parameters for next content."""
        recs = self.analyzer.get_recommendations()

        optimization = {
            "recommended_template": recs["best_templates"][0] if recs["best_templates"] else None,
            "recommended_voice": recs["best_voices"][0] if recs["best_voices"] else None,
            "recommended_posting_time": recs["best_posting_times"][0] if recs["best_posting_times"] else None,
            "recommended_cta_index": recs["best_ctas"][0] if recs["best_ctas"] else None,
            "recommended_title_pattern": recs["best_title_patterns"][0] if recs["best_title_patterns"] else None,
        }

        return optimization

    def update_strategy(self) -> None:
        """Update strategy based on analysis."""
        opt = self.optimize_for_next_content()

        if opt["recommended_template"]:
            templates = self.strategy["template_rotation"]
            if opt["recommended_template"] in templates:
                templates.remove(opt["recommended_template"])
            self.strategy["template_rotation"] = [opt["recommended_template"]] + templates

        self.strategy["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save_strategy()

    def get_next_template(self) -> str:
        """Get next template in rotation."""
        templates = self.strategy["template_rotation"]
        if not templates:
            templates = self.cfg.TEMPLATES.copy()

        return templates[0]

    def rotate_template(self) -> None:
        """Rotate to next template."""
        if self.strategy["template_rotation"]:
            template = self.strategy["template_rotation"].pop(0)
            self.strategy["template_rotation"].append(template)
            self.save_strategy()

    def should_update_strategy(self) -> bool:
        """Check if strategy should be updated."""
        last_update = self.strategy.get("updated_at")
        if not last_update:
            return True

        try:
            dt = datetime.fromisoformat(last_update)
            hours_since = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            return hours_since >= 24
        except (ValueError, AttributeError):
            return True


class RiskManager:
    """Manages risk and prevents strikes/bans."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.risk_file = cfg.state_path.parent / "risk.json"
        self.load_risk()

    def load_risk(self) -> None:
        """Load risk history."""
        if self.risk_file.exists():
            with open(self.risk_file) as f:
                self.risk_data = json.load(f)
        else:
            self.risk_data = {
                "strikes": [],
                "warnings": [],
                "copyright_claims": [],
                "spam_flags": [],
                "risk_level": "low",
            }

    def save_risk(self) -> None:
        """Save risk data."""
        self.risk_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.risk_file, "w") as f:
            json.dump(self.risk_data, f, indent=2)

    def record_strike(self, video_id: str, reason: str) -> None:
        """Record a YouTube strike."""
        strike = {
            "video_id": video_id,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.risk_data["strikes"].append(strike)
        self._update_risk_level()
        self.save_risk()

    def record_copyright_claim(self, video_id: str, claimant: str) -> None:
        """Record a copyright claim."""
        claim = {
            "video_id": video_id,
            "claimant": claimant,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.risk_data["copyright_claims"].append(claim)
        self._update_risk_level()
        self.save_risk()

    def record_warning(self, warning: str) -> None:
        """Record a warning."""
        self.risk_data["warnings"].append({
            "warning": warning,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._update_risk_level()
        self.save_risk()

    def is_safe_to_publish(self) -> bool:
        """Check if it's safe to publish."""
        strikes = len(self.risk_data["strikes"])
        return strikes < 3

    def get_risk_level(self) -> str:
        """Get current risk level."""
        strikes = len(self.risk_data["strikes"])
        claims = len(self.risk_data["copyright_claims"])
        warnings = len(self.risk_data["warnings"])

        total_risk = strikes * 30 + claims * 10 + warnings * 5

        if total_risk > 50:
            return "critical"
        elif total_risk > 30:
            return "high"
        elif total_risk > 10:
            return "medium"
        else:
            return "low"

    def _update_risk_level(self) -> None:
        """Update risk level based on data."""
        self.risk_data["risk_level"] = self.get_risk_level()

    def get_recommendations(self) -> list[str]:
        """Get risk mitigation recommendations."""
        recs = []

        if len(self.risk_data["strikes"]) > 0:
            recs.append("Channel has strikes. Review content policies.")

        if len(self.risk_data["copyright_claims"]) > 0:
            recs.append("Copyright claims detected. Use only royalty-free content.")

        if len(self.risk_data["warnings"]) > 0:
            recs.append("Warnings issued. Review recent content.")

        if len(self.risk_data["strikes"]) >= 2:
            recs.append("CRITICAL: High strike count. Pause publishing and review.")

        return recs

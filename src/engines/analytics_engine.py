from datetime import datetime, timezone
import json

from core.config import CONFIG
from core.state import StateStore
from integrations.youtube_engine import YouTubeEngine


class AnalyticsEngine:
    def __init__(self) -> None:
        self.state = StateStore()
        self.youtube = YouTubeEngine()

    def run(self) -> None:
        state = self.state.get()
        rows = []
        for item in state.get("uploads", [])[-50:]:
            stats = self.youtube.fetch_video_stats(item["video_id"])
            if stats:
                rows.append({**stats, "type": item["type"], "created_at": item["created_at"]})

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "videos": rows,
            "best_by_views": sorted(rows, key=lambda x: x["views"], reverse=True)[:5],
        }
        (CONFIG.data_dir / "analytics_report.json").write_text(json.dumps(report, indent=2))

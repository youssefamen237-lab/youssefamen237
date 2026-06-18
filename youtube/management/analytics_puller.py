"""
youtube/management/analytics_puller.py

Pulls per-video performance data for recently published videos and writes
daily snapshots to performance_metrics, then refreshes each topic's rolling
avg_retention / avg_ctr / total_views from the latest snapshots.

Run via: python -m youtube.management.analytics_puller
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import structlog

from storage.supabase_client import get_db
from youtube.management.management_client import get_management_client

logger = structlog.get_logger(__name__)

_LOOKBACK_DAYS = 30   # only pull metrics for videos published within this window
_DATA_LAG_DAYS = 2    # YouTube Analytics reporting lag — query "2 days ago"


class AnalyticsPuller:

    def __init__(self) -> None:
        self._db     = get_db()
        self._client = get_management_client()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, days_ago: int = _DATA_LAG_DAYS) -> Dict[str, int]:
        target_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
        start = end = target_date.isoformat()

        videos = self._eligible_videos()
        summary = {
            "date": start, "videos_checked": len(videos),
            "metrics_recorded": 0, "no_data_yet": 0,
            "topics_updated": 0, "errors": 0,
        }

        topics_touched: set = set()

        for v in videos:
            yt_id = v.get("youtube_video_id")
            if not yt_id:
                continue

            try:
                metrics = self._client.query_video_analytics(yt_id, start, end)
            except Exception as exc:
                logger.warning("analytics_pull_failed", yt_id=yt_id, error=str(exc)[:150])
                summary["errors"] += 1
                continue

            if not metrics:
                summary["no_data_yet"] += 1
                continue

            try:
                self._db.upsert_metrics(yt_id, metrics)
                summary["metrics_recorded"] += 1
            except Exception as exc:
                logger.warning("metrics_insert_failed", yt_id=yt_id, error=str(exc)[:150])
                summary["errors"] += 1
                continue

            topic_id = v.get("topic_id")
            if topic_id:
                topics_touched.add(topic_id)

        for topic_id in topics_touched:
            if self._refresh_topic_performance(topic_id):
                summary["topics_updated"] += 1

        logger.info("analytics_pull_complete", **summary)
        return summary

    # ── Internal ──────────────────────────────────────────────────────────────

    def _eligible_videos(self) -> List[Dict]:
        recent = self._db.get_recent_published(limit=200)
        cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)

        out: List[Dict] = []
        for r in recent:
            pub_dt = self._parse_dt(r.get("published_at"))
            if pub_dt is not None and pub_dt >= cutoff:
                out.append(r)
        return out

    def _refresh_topic_performance(self, topic_id: str) -> bool:
        """
        Recompute rolling avg_retention / avg_ctr / total_views for a topic
        across ALL its published videos, using each video's latest
        performance_metrics snapshot.
        """
        try:
            published = [
                r for r in self._db.get_recent_published(limit=200)
                if r.get("topic_id") == topic_id and r.get("youtube_video_id")
            ]
            if not published:
                return False

            retentions: List[float] = []
            ctrs:       List[float] = []
            total_views = 0

            for p in published:
                latest = self._db.get_latest_metrics(p["youtube_video_id"])
                if not latest:
                    continue
                retentions.append(float(latest.get("retention_percentage") or 0))
                ctrs.append(float(latest.get("ctr") or 0))
                total_views += int(latest.get("views") or 0)

            if not retentions:
                return False

            self._db.update_topic_performance(
                topic_id=topic_id,
                avg_retention=round(sum(retentions) / len(retentions), 2),
                avg_ctr=round(sum(ctrs) / len(ctrs), 2),
                total_views=total_views,
            )
            return True
        except Exception as exc:
            logger.debug("topic_performance_refresh_failed", topic_id=str(topic_id)[:8], error=str(exc)[:100])
            return False

    @staticmethod
    def _parse_dt(raw: Optional[str]):
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None


_instance: Optional[AnalyticsPuller] = None

def get_analytics_puller() -> AnalyticsPuller:
    global _instance
    if _instance is None:
        _instance = AnalyticsPuller()
    return _instance


if __name__ == "__main__":
    import json
    result = get_analytics_puller().run()
    print(json.dumps(result, indent=2))

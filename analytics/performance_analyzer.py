"""
analytics/performance_analyzer.py

Aggregates recent performance_metrics + published_log records into
learning_memory entries.  This is the "what happened" layer — channel_os
reads these memories to decide "what to do about it".

Run via: python -m analytics.performance_analyzer
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional
import structlog

from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_LOOKBACK_DAYS    = 30
_MIN_SAMPLE_SIZE  = 3
_WINNER_TOP_N     = 5
_FAILURE_BOTTOM_N = 5

# (min_inclusive, max_exclusive, bucket_name) — for video_type == "short"
_DURATION_BUCKETS = [
    (0, 20, "very_short"),
    (20, 30, "short"),
    (30, 45, "medium_short"),
    (45, 99999, "long"),
]


class PerformanceAnalyzer:

    def __init__(self) -> None:
        self._db = get_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> Dict[str, int]:
        records = self._load_records()
        summary = {"records_analyzed": len(records), "memories_written": 0}

        if not records:
            logger.info("performance_analysis_no_data")
            return summary

        summary["memories_written"] += self._category_insights(records)
        summary["memories_written"] += self._voice_insights(records)
        summary["memories_written"] += self._length_insights(records)
        summary["memories_written"] += self._retention_benchmarks(records)
        summary["memories_written"] += self._winner_failure_patterns(records)

        logger.info("performance_analysis_complete", **summary)
        return summary

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_records(self) -> List[Dict]:
        """
        Join published_log with each video's latest performance_metrics
        snapshot.  Only includes videos with at least one recorded metric.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
        published = self._db.get_recent_published(limit=300)

        records: List[Dict] = []
        for p in published:
            pub_dt = self._parse_dt(p.get("published_at"))
            if pub_dt is None or pub_dt < cutoff:
                continue

            yt_id = p.get("youtube_video_id")
            if not yt_id:
                continue

            metrics = self._db.get_latest_metrics(yt_id)
            if not metrics:
                continue

            records.append({
                "youtube_video_id":    yt_id,
                "video_type":          p.get("video_type"),
                "category":            p.get("category"),
                "voice_gender":        p.get("voice_gender"),
                "title":               p.get("title"),
                "quality_score":       p.get("quality_score"),
                "duration_seconds":    p.get("duration_seconds"),
                "published_at":        pub_dt,
                "views":               int(metrics.get("views") or 0),
                "retention":           float(metrics.get("retention_percentage") or 0),
                "ctr":                 float(metrics.get("ctr") or 0),
                "watch_time":          float(metrics.get("watch_time_minutes") or 0),
                "revenue":             float(metrics.get("estimated_revenue_usd") or 0),
                "subscribers_gained":  int(metrics.get("subscribers_gained") or 0),
            })
        return records

    # ── Category insights ────────────────────────────────────────────────────

    def _category_insights(self, records: List[Dict]) -> int:
        by_cat: Dict[str, List[Dict]] = {}
        for r in records:
            cat = r.get("category")
            if cat:
                by_cat.setdefault(cat, []).append(r)

        written = 0
        for cat, rows in by_cat.items():
            if len(rows) < _MIN_SAMPLE_SIZE:
                continue
            value = {
                "category":          cat,
                "video_count":       len(rows),
                "avg_retention":     round(mean(r["retention"] for r in rows), 2),
                "avg_ctr":           round(mean(r["ctr"] for r in rows), 2),
                "avg_views":         round(mean(r["views"] for r in rows), 1),
                "total_revenue_usd": round(sum(r["revenue"] for r in rows), 4),
            }
            self._write_memory("category_insight", cat, value, len(rows))
            written += 1
        return written

    # ── Voice insights ────────────────────────────────────────────────────────

    def _voice_insights(self, records: List[Dict]) -> int:
        by_voice: Dict[str, List[Dict]] = {}
        for r in records:
            g = r.get("voice_gender")
            if g in ("male", "female"):
                by_voice.setdefault(g, []).append(r)

        written = 0
        for gender, rows in by_voice.items():
            if len(rows) < _MIN_SAMPLE_SIZE:
                continue
            value = {
                "voice_gender":     gender,
                "video_count":      len(rows),
                "avg_retention":    round(mean(r["retention"] for r in rows), 2),
                "avg_ctr":          round(mean(r["ctr"] for r in rows), 2),
                "avg_subs_gained":  round(mean(r["subscribers_gained"] for r in rows), 3),
            }
            self._write_memory("voice_insight", gender, value, len(rows))
            written += 1

        if "female" in by_voice and "male" in by_voice:
            f_rows, m_rows = by_voice["female"], by_voice["male"]
            if len(f_rows) >= _MIN_SAMPLE_SIZE and len(m_rows) >= _MIN_SAMPLE_SIZE:
                f_ret = mean(r["retention"] for r in f_rows)
                m_ret = mean(r["retention"] for r in m_rows)
                diff_pct = round((f_ret - m_ret) / m_ret * 100, 2) if m_ret > 0 else 0.0
                value = {
                    "female_avg_retention": round(f_ret, 2),
                    "male_avg_retention":   round(m_ret, 2),
                    "female_vs_male_pct":   diff_pct,
                    "leader":               "female" if f_ret >= m_ret else "male",
                }
                self._write_memory("voice_insight", "comparison", value, len(f_rows) + len(m_rows))
                written += 1
        return written

    # ── Length insights (shorts only) ────────────────────────────────────────

    def _length_insights(self, records: List[Dict]) -> int:
        shorts = [
            r for r in records
            if r.get("video_type") == "short" and r.get("duration_seconds")
        ]
        by_bucket: Dict[str, List[Dict]] = {}
        for r in shorts:
            bucket = self._duration_bucket(int(r["duration_seconds"]))
            by_bucket.setdefault(bucket, []).append(r)

        written = 0
        for bucket, rows in by_bucket.items():
            if len(rows) < _MIN_SAMPLE_SIZE:
                continue
            value = {
                "duration_bucket":      bucket,
                "video_count":          len(rows),
                "avg_retention":        round(mean(r["retention"] for r in rows), 2),
                "avg_ctr":              round(mean(r["ctr"] for r in rows), 2),
                "avg_duration_seconds": round(mean(r["duration_seconds"] for r in rows), 1),
            }
            self._write_memory("length_insight", f"short_{bucket}", value, len(rows))
            written += 1
        return written

    @staticmethod
    def _duration_bucket(seconds: int) -> str:
        for lo, hi, name in _DURATION_BUCKETS:
            if lo <= seconds < hi:
                return name
        return "long"

    # ── Retention benchmarks ──────────────────────────────────────────────────

    def _retention_benchmarks(self, records: List[Dict]) -> int:
        written = 0
        for video_type in ("short", "long"):
            values = [r["retention"] for r in records if r.get("video_type") == video_type]
            if len(values) < _MIN_SAMPLE_SIZE:
                continue
            value = {
                "avg_retention": round(mean(values), 2),
                "max_retention": round(max(values), 2),
                "min_retention": round(min(values), 2),
                "sample_size":   len(values),
            }
            self._write_memory("retention_benchmark", video_type, value, len(values))
            written += 1
        return written

    # ── Winner / failure patterns (shorts only) ──────────────────────────────

    def _winner_failure_patterns(self, records: List[Dict]) -> int:
        shorts = [r for r in records if r.get("video_type") == "short"]
        if len(shorts) < _MIN_SAMPLE_SIZE * 2:
            return 0

        ranked = sorted(shorts, key=lambda r: r["retention"], reverse=True)
        winners  = ranked[:_WINNER_TOP_N]
        failures = ranked[-_FAILURE_BOTTOM_N:]

        written = 0

        winner_dna = self._summarize_dna(winners)
        if winner_dna:
            self._write_memory(
                "winner_pattern", "top_shorts", winner_dna, len(winners),
                confidence=min(90.0, 30.0 + len(winners) * 8.0),
            )
            written += 1

        failure_dna = self._summarize_dna(failures)
        if failure_dna:
            self._write_memory(
                "failure_pattern", "bottom_shorts", failure_dna, len(failures),
                confidence=min(90.0, 30.0 + len(failures) * 8.0),
            )
            written += 1

        return written

    @staticmethod
    def _summarize_dna(rows: List[Dict]) -> Optional[Dict]:
        if not rows:
            return None

        def _mode(values: List[Optional[str]]) -> Optional[str]:
            clean = [v for v in values if v]
            return max(set(clean), key=clean.count) if clean else None

        durations = [r["duration_seconds"] for r in rows if r.get("duration_seconds")]

        return {
            "video_count":          len(rows),
            "avg_retention":        round(mean(r["retention"] for r in rows), 2),
            "avg_ctr":              round(mean(r["ctr"] for r in rows), 2),
            "dominant_category":    _mode([r.get("category") for r in rows]),
            "dominant_voice":       _mode([r.get("voice_gender") for r in rows]),
            "avg_duration_seconds": round(mean(durations), 1) if durations else None,
            "video_ids":            [r["youtube_video_id"] for r in rows],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _write_memory(
        self, memory_type: str, memory_key: str, value: Dict, data_points: int,
        confidence: Optional[float] = None,
    ) -> None:
        if confidence is None:
            confidence = min(95.0, 40.0 + data_points * 5.0)
        try:
            self._db.upsert_memory(
                memory_type=memory_type, memory_key=memory_key,
                memory_value=value, confidence=round(confidence, 2),
                data_points=data_points,
            )
        except Exception as exc:
            logger.warning(
                "memory_write_failed", memory_type=memory_type,
                memory_key=memory_key, error=str(exc)[:120],
            )

    @staticmethod
    def _parse_dt(raw: Optional[str]):
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None


_instance: Optional[PerformanceAnalyzer] = None

def get_performance_analyzer() -> PerformanceAnalyzer:
    global _instance
    if _instance is None:
        _instance = PerformanceAnalyzer()
    return _instance


if __name__ == "__main__":
    import json
    result = get_performance_analyzer().run()
    print(json.dumps(result, indent=2))

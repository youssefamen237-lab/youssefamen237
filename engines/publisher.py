"""
engines/publisher.py
"""
from __future__ import annotations
import os, tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import structlog

from storage.supabase_client import get_db
from storage.redis_client import get_redis
from storage.r2_client import get_r2
from storage.cleanup_manager import CleanupManager
from youtube.upload.upload_client import get_upload_client
from youtube.upload.upload_scheduler import get_upload_scheduler

logger = structlog.get_logger(__name__)


@dataclass
class PublishResult:
    success:          bool
    youtube_video_id: Optional[str] = None
    error:            Optional[str] = None


class Publisher:

    def __init__(self) -> None:
        self._db        = get_db()
        self._redis     = get_redis()
        self._r2        = get_r2()
        self._upload    = get_upload_client()
        self._scheduler = get_upload_scheduler()
        self._cleanup   = CleanupManager()

    # ── Public API ────────────────────────────────────────────────────────────

    def publish(self, queue_id: str, local_video_path: Optional[str] = None) -> PublishResult:
        """
        Publish an approved queue job to YouTube.

        If local_video_path is not provided (or no longer exists — production
        and publishing typically run in separate workflow executions), the
        final video is downloaded from R2 using final_video_r2_path.
        """
        job = self._db.get_video_job(queue_id)
        if not job:
            return PublishResult(False, error=f"Queue job {queue_id} not found.")

        if job.get("status") not in ("approved", "scheduled"):
            return PublishResult(
                False, error=f"Queue job {queue_id} has status "
                              f"'{job.get('status')}', expected 'approved'."
            )

        downloaded_temp: Optional[str] = None
        if local_video_path is None or not os.path.exists(local_video_path):
            final_r2_key = job.get("final_video_r2_path")
            if not final_r2_key:
                return PublishResult(False, error="Queue job has no final_video_r2_path to publish.")

            fd, downloaded_temp = tempfile.mkstemp(suffix=".mp4", prefix=f"yta_pub_{queue_id[:8]}_")
            os.close(fd)
            try:
                self._r2.download_file(final_r2_key, downloaded_temp)
            except Exception as exc:
                os.unlink(downloaded_temp)
                return PublishResult(False, error=f"Failed to download final video from R2: {exc}")
            local_video_path = downloaded_temp

        try:
            return self._do_publish(queue_id, job, local_video_path)
        finally:
            if downloaded_temp:
                try:
                    os.unlink(downloaded_temp)
                except OSError:
                    pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _do_publish(self, queue_id: str, job: dict, local_video_path: str) -> PublishResult:
        video_type  = job["video_type"]
        title       = job.get("title") or "Untitled"
        description = job.get("description") or ""
        hashtags    = job.get("hashtags") or []
        tags        = [h.lstrip("#") for h in hashtags]

        topic_id = job.get("topic_id")
        category: Optional[str] = None
        if topic_id:
            topic = self._db.get_topic_by_id(topic_id)
            if topic:
                category = topic.get("category")

        scheduled_dt   = self._scheduler.compute_publish_time(video_type)
        publish_now    = self._scheduler.should_publish_now(scheduled_dt)
        publish_at_iso = None if publish_now else self._scheduler.to_iso(scheduled_dt)
        privacy        = "public" if publish_now else "private"

        result = self._upload.upload_video(
            file_path=local_video_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
            publish_at=publish_at_iso,
            is_short=(video_type == "short"),
        )

        if not result.success:
            self._db.log_job_error(queue_id, "publish", result.error or "unknown upload error")
            return PublishResult(False, error=result.error)

        yt_id   = result.video_id
        now_iso = datetime.now(timezone.utc).isoformat()

        self._db.insert_published_record({
            "queue_id":         queue_id,
            "topic_id":         topic_id,
            "youtube_video_id": yt_id,
            "video_type":       video_type,
            "title":            title,
            "category":         category,
            "voice_gender":     job.get("voice_gender"),
            "voice_id":         job.get("voice_id"),
            "quality_score":    job.get("quality_score"),
            "published_at":     now_iso,
            "upload_key_used":  result.key_used,
            "publish_window":   self._scheduler.to_iso(scheduled_dt),
        })

        self._db.update_video_status(queue_id, "published", extra={
            "youtube_video_id": yt_id,
            "upload_key_used":  result.key_used,
            "published_at":     now_iso,
        })

        if topic_id:
            self._db.mark_topic_published(topic_id, video_type)

        try:
            self._redis.record_last_publish(video_type)
        except Exception:
            pass

        try:
            self._cleanup.cleanup_after_upload(queue_id)
        except Exception as exc:
            logger.warning("post_publish_cleanup_failed", queue_id=queue_id[:8], error=str(exc)[:100])

        logger.info(
            "video_published",
            queue_id=queue_id[:8], youtube_video_id=yt_id,
            video_type=video_type, scheduled=not publish_now,
        )
        return PublishResult(True, youtube_video_id=yt_id)


_instance: Optional[Publisher] = None

def get_publisher() -> Publisher:
    global _instance
    if _instance is None:
        _instance = Publisher()
    return _instance

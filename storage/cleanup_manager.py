"""
storage/cleanup_manager.py

Automated R2 storage lifecycle manager for the YouTube Automation System.

Responsibilities
────────────────
  1. Post-upload cleanup    Delete raw clips and intermediate audio immediately
                            after a video is successfully uploaded to YouTube.

  2. Retention enforcement  Delete final MP4s from R2 after 30 days
                            (they are safe on YouTube; R2 storage is not free).

  3. Orphan cleanup         Purge raw clips and audio files that were never
                            cleaned up because a job failed or was killed mid-run.

  4. Storage health report  Summarise byte usage per folder for the war room.

Called by
─────────
  • publisher.py              — immediately after a confirmed YouTube upload
  • .github/workflows/storage_cleanup.yml  — daily scheduled run at 03:00 UTC
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import structlog

from storage.r2_client import R2Client, R2Paths, get_r2
from storage.supabase_client import SupabaseClient, get_db

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Retention policy constants (mirrors channel_config values as hard defaults)
# ─────────────────────────────────────────────────────────────────────────────

class RetentionPolicy:
    RAW_CLIPS_MAX_HOURS:  int = 6    # Delete orphaned raw clips after 6 h
    AUDIO_MAX_HOURS:      int = 6    # Delete orphaned intermediate audio after 6 h
    SUBTITLES_MAX_DAYS:   int = 7    # Keep subtitle files for 7 days
    THUMBNAILS_MAX_DAYS:  int = 30   # Keep thumbnails for 30 days
    FINALS_MAX_DAYS:      int = 30   # Keep final MP4s for 30 days post-upload
    R2_FREE_TIER_BYTES:   int = 10 * 1024 ** 3  # 10 GB free tier ceiling


# ─────────────────────────────────────────────────────────────────────────────
# CleanupManager
# ─────────────────────────────────────────────────────────────────────────────

class CleanupManager:
    """
    Handles all R2 storage lifecycle tasks.
    Instantiated once per pipeline run; not a singleton.
    """

    def __init__(self) -> None:
        self.r2: R2Client = get_r2()
        self.db: SupabaseClient = get_db()
        self._retention_days_finals: int = self._load_retention_days()

    # ── Configuration ─────────────────────────────────────────────────────────

    def _load_retention_days(self) -> int:
        """
        Read r2_retention_days_final from Supabase channel_config.
        Falls back to RetentionPolicy constant if config is unavailable.
        """
        try:
            raw = self.db.get_config("r2_retention_days_final")
            if raw is not None:
                return int(str(raw).strip('"'))
        except Exception:
            pass
        return RetentionPolicy.FINALS_MAX_DAYS

    # ═════════════════════════════════════════════════════════════════════════
    # 1. POST-UPLOAD CLEANUP
    # Called immediately after a confirmed YouTube upload.
    # ═════════════════════════════════════════════════════════════════════════

    def cleanup_after_upload(self, queue_id: str) -> Dict[str, int]:
        """
        Delete raw footage clips and intermediate audio for a finished job.
        Final MP4, subtitle, and thumbnail are kept per the retention policy.

        Returns a dict summarising what was deleted:
            {raw_clips_deleted, audio_files_deleted, bytes_freed}
        """
        result: Dict[str, int] = {
            "raw_clips_deleted": 0,
            "audio_files_deleted": 0,
            "bytes_freed": 0,
        }

        # ── Raw clips ────────────────────────────────────────────────────────
        raw_objects = self.r2.list_prefix(R2Paths.raw_prefix(queue_id))
        raw_bytes = sum(obj["size_bytes"] for obj in raw_objects)
        raw_deleted = self.r2.delete_prefix(R2Paths.raw_prefix(queue_id))
        result["raw_clips_deleted"] = raw_deleted
        result["bytes_freed"] += raw_bytes

        # ── Intermediate audio ────────────────────────────────────────────────
        audio_objects = self.r2.list_prefix(R2Paths.audio_prefix(queue_id))
        audio_bytes = sum(obj["size_bytes"] for obj in audio_objects)
        audio_deleted = self.r2.delete_prefix(R2Paths.audio_prefix(queue_id))
        result["audio_files_deleted"] = audio_deleted
        result["bytes_freed"] += audio_bytes

        logger.info(
            "post_upload_cleanup_done",
            queue_id=queue_id[:8],
            raw_deleted=raw_deleted,
            audio_deleted=audio_deleted,
            bytes_freed=result["bytes_freed"],
        )
        return result

    # ═════════════════════════════════════════════════════════════════════════
    # 2. EXPIRED FINALS CLEANUP
    # Deletes final MP4s + thumbnails older than retention_days_finals.
    # Only runs on records that have a confirmed youtube_video_id.
    # ═════════════════════════════════════════════════════════════════════════

    def cleanup_expired_finals(self, dry_run: bool = False) -> Dict[str, int]:
        """
        Scan published_log for records whose published_at is older than the
        retention window and delete the corresponding R2 final + thumbnail.

        dry_run=True logs what would be deleted without touching R2.
        Returns: {inspected, finals_deleted, thumbnails_deleted, bytes_freed}
        """
        result: Dict[str, int] = {
            "inspected": 0,
            "finals_deleted": 0,
            "thumbnails_deleted": 0,
            "bytes_freed": 0,
        }

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days_finals)
        cutoff_iso = cutoff.isoformat()

        published = self.db.get_recent_published(limit=2_000)

        for record in published:
            pub_at_raw = record.get("published_at")
            if not pub_at_raw:
                continue

            # Parse published_at; Supabase returns ISO strings
            try:
                pub_at = datetime.fromisoformat(
                    pub_at_raw.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue

            if pub_at >= cutoff:
                continue   # Still within retention window

            result["inspected"] += 1
            queue_id = record.get("queue_id")
            if not queue_id:
                continue

            # ── Final MP4 ────────────────────────────────────────────────────
            final_key = R2Paths.final_video(queue_id)
            if self.r2.file_exists(final_key):
                size = self.r2.get_file_size(final_key) or 0
                if not dry_run:
                    if self.r2.delete_file(final_key):
                        result["finals_deleted"] += 1
                        result["bytes_freed"] += size
                else:
                    logger.info(
                        "dry_run_would_delete_final",
                        queue_id=queue_id[:8],
                        key=final_key,
                        size_bytes=size,
                    )
                    result["finals_deleted"] += 1
                    result["bytes_freed"] += size

            # ── Thumbnail ────────────────────────────────────────────────────
            thumb_key = R2Paths.thumbnail(queue_id)
            if self.r2.file_exists(thumb_key):
                t_size = self.r2.get_file_size(thumb_key) or 0
                if not dry_run:
                    if self.r2.delete_file(thumb_key):
                        result["thumbnails_deleted"] += 1
                        result["bytes_freed"] += t_size
                else:
                    result["thumbnails_deleted"] += 1
                    result["bytes_freed"] += t_size

        logger.info(
            "expired_finals_cleanup_done",
            dry_run=dry_run,
            **result,
        )
        return result

    # ═════════════════════════════════════════════════════════════════════════
    # 3. ORPHAN CLEANUP
    # Removes raw clips and audio that were never cleaned up because the job
    # that created them failed, was killed mid-run, or is stuck in error state.
    # ═════════════════════════════════════════════════════════════════════════

    def cleanup_orphaned_raw_clips(
        self, older_than_hours: int = RetentionPolicy.RAW_CLIPS_MAX_HOURS
    ) -> int:
        """
        Delete any object under media/raw/ whose last_modified is older than
        older_than_hours.  Returns the count of deleted objects.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        all_objects = self.r2.list_prefix("media/raw/")

        to_delete = [
            obj["key"]
            for obj in all_objects
            if self._is_older_than(obj["last_modified"], cutoff)
        ]

        deleted = 0
        for key in to_delete:
            if self.r2.delete_file(key):
                deleted += 1

        if deleted:
            logger.info(
                "orphaned_raw_clips_deleted",
                count=deleted,
                older_than_hours=older_than_hours,
            )
        return deleted

    def cleanup_orphaned_audio(
        self, older_than_hours: int = RetentionPolicy.AUDIO_MAX_HOURS
    ) -> int:
        """
        Delete any object under audio/ whose last_modified is older than
        older_than_hours.  Returns the count of deleted objects.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        all_objects = self.r2.list_prefix("audio/")

        to_delete = [
            obj["key"]
            for obj in all_objects
            if self._is_older_than(obj["last_modified"], cutoff)
        ]

        deleted = 0
        for key in to_delete:
            if self.r2.delete_file(key):
                deleted += 1

        if deleted:
            logger.info(
                "orphaned_audio_deleted",
                count=deleted,
                older_than_hours=older_than_hours,
            )
        return deleted

    def cleanup_orphaned_subtitles(
        self, older_than_days: int = RetentionPolicy.SUBTITLES_MAX_DAYS
    ) -> int:
        """Delete subtitle files older than older_than_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        all_objects = self.r2.list_prefix("subtitles/")

        to_delete = [
            obj["key"]
            for obj in all_objects
            if self._is_older_than(obj["last_modified"], cutoff)
        ]

        deleted = 0
        for key in to_delete:
            if self.r2.delete_file(key):
                deleted += 1

        if deleted:
            logger.info("orphaned_subtitles_deleted", count=deleted)
        return deleted

    # ═════════════════════════════════════════════════════════════════════════
    # 4. STORAGE HEALTH REPORT
    # ═════════════════════════════════════════════════════════════════════════

    def get_storage_health_report(self) -> Dict:
        """
        Compute byte usage per logical folder and emit a health summary.
        Used by the daily_dashboard and the COS weekly review.
        """
        folders = {
            "raw_clips": "media/raw/",
            "audio": "audio/",
            "subtitles": "subtitles/",
            "thumbnails": "thumbnails/",
            "finals": "finals/",
            "music": "music/",
            "archive": "archive/",
        }

        usage: Dict[str, int] = {}
        for label, prefix in folders.items():
            usage[f"{label}_bytes"] = self.r2.get_storage_usage_bytes(prefix)

        total_bytes: int = sum(usage.values())
        total_gb: float = round(total_bytes / (1024 ** 3), 4)
        free_tier_used_pct: float = round(
            (total_bytes / RetentionPolicy.R2_FREE_TIER_BYTES) * 100, 2
        )

        report = {
            **usage,
            "total_bytes": total_bytes,
            "total_gb": total_gb,
            "free_tier_used_pct": free_tier_used_pct,
            "free_tier_ceiling_gb": RetentionPolicy.R2_FREE_TIER_BYTES / (1024 ** 3),
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
        }

        level = logging.WARNING if free_tier_used_pct > 75 else logging.INFO
        logger.log(
            level,
            "storage_health_report",
            total_gb=total_gb,
            free_tier_used_pct=free_tier_used_pct,
        )
        return report

    # ═════════════════════════════════════════════════════════════════════════
    # 5. FULL SCHEDULED CLEANUP
    # Called by .github/workflows/storage_cleanup.yml every night at 03:00 UTC
    # ═════════════════════════════════════════════════════════════════════════

    def run_full_cleanup(self, dry_run: bool = False) -> Dict:
        """
        Execute every cleanup task in sequence and return a unified report.
        dry_run=True performs a complete inspection pass without deleting anything.
        """
        logger.info("full_cleanup_started", dry_run=dry_run)

        report: Dict = {
            "dry_run": dry_run,
            "orphaned_raw_clips_deleted": 0,
            "orphaned_audio_deleted": 0,
            "orphaned_subtitles_deleted": 0,
            "expired_finals": {},
            "storage_health": {},
        }

        # Step 1 — Orphan cleanup (raw clips)
        if not dry_run:
            report["orphaned_raw_clips_deleted"] = self.cleanup_orphaned_raw_clips()

        # Step 2 — Orphan cleanup (audio)
        if not dry_run:
            report["orphaned_audio_deleted"] = self.cleanup_orphaned_audio()

        # Step 3 — Orphan cleanup (subtitles)
        if not dry_run:
            report["orphaned_subtitles_deleted"] = self.cleanup_orphaned_subtitles()

        # Step 4 — Expired finals (respects dry_run)
        report["expired_finals"] = self.cleanup_expired_finals(dry_run=dry_run)

        # Step 5 — Storage health report
        report["storage_health"] = self.get_storage_health_report()

        logger.info(
            "full_cleanup_complete",
            dry_run=dry_run,
            finals_deleted=report["expired_finals"].get("finals_deleted", 0),
            bytes_freed=report["expired_finals"].get("bytes_freed", 0),
            storage_gb=report["storage_health"].get("total_gb", 0),
        )
        return report

    # ═════════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _is_older_than(last_modified: datetime, cutoff: datetime) -> bool:
        """
        Compare a boto3 last_modified datetime (always timezone-aware UTC)
        against a cutoff datetime.  Handles the edge case where last_modified
        might be naive by assuming UTC.
        """
        if last_modified is None:
            return False
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        return last_modified < cutoff

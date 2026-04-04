"""
pipelines/run_weekly.py
=======================
Orchestrates the weekly long-form compilation:
  fetch last N Shorts → compile → upload → DB log
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from config.api_keys import validate_all
from config.settings import CHANNEL_NAME, COMPILATION_MAX_CLIPS, YT_DEFAULT_TAGS
from core.long_compiler import LongCompiler
from database.db import Database
from upload.uploader import YouTubeUploader
from utils.logger import get_logger, log_pipeline_end, log_pipeline_start

logger = get_logger(__name__)


@dataclass
class WeeklyPipelineResult:
    """Outcome of the weekly compilation pipeline run."""
    success:          bool
    video_id:         Optional[str]   = None
    youtube_video_id: Optional[str]   = None
    youtube_url:      Optional[str]   = None
    duration_secs:    Optional[float] = None
    clip_count:       Optional[int]   = None
    error:            Optional[str]   = None


def _build_weekly_title() -> str:
    now  = datetime.now(timezone.utc)
    week = now.isocalendar()[1]
    year = now.isocalendar()[0]
    return f"Psychology Facts Compilation — Week {week}, {year} | {CHANNEL_NAME}"


def _build_weekly_description(clip_count: int, duration: float) -> str:
    mins = int(duration // 60)
    secs = int(duration % 60)
    return (
        f"🧠 {clip_count} mind-blowing psychology facts in {mins}m {secs}s.\n\n"
        f"Every fact in this compilation will change how you see human behaviour. "
        f"From cognitive biases to social psychology experiments — "
        f"this week's best psychology insights in one video.\n\n"
        f"📌 {_build_weekly_title()}\n\n"
        f"#psychology #psychologyfacts #mindset #mentalhealth "
        f"#brainscience #compilation #shorts"
    )


class WeeklyPipeline:
    """
    Compiles and uploads the weekly long-form video.

    Parameters
    ----------
    db        : Shared Database instance.
    dry_run   : If True, skip YouTube upload.
    privacy   : YouTube privacy status.
    max_clips : Override clip count for this run.
    """

    def __init__(
        self,
        db:        Optional[Database] = None,
        dry_run:   bool = False,
        privacy:   str  = "public",
        max_clips: int  = COMPILATION_MAX_CLIPS,
    ) -> None:
        self._db        = db or Database()
        self._dry_run   = dry_run
        self._privacy   = privacy
        self._max_clips = max_clips
        self._compiler  = LongCompiler(db=self._db, max_clips=max_clips)
        self._uploader  = YouTubeUploader(db=self._db)

    # ── Public ─────────────────────────────────────────────────────────────

    def run(self) -> WeeklyPipelineResult:
        """
        Execute all compilation pipeline stages.

        Returns
        -------
        WeeklyPipelineResult — always returns, never raises.
        """
        stage = "init"
        try:
            # ── 1. Compile ────────────────────────────────────────────────
            stage = "compile"
            logger.info("[Weekly] Starting compilation (max %d clips) …", self._max_clips)
            compilation = self._compiler.compile(max_clips=self._max_clips)
            logger.info(
                "[Weekly] Compiled: %s  %.1fs  %d clips",
                compilation.video_path.name,
                compilation.duration_secs,
                compilation.clip_count,
            )

            # ── 2. DB — log video ─────────────────────────────────────────
            stage = "db_video"
            video_id = self._db.insert_video(
                script_id="compilation",        # no single script source
                video_type="compilation",
                file_path=str(compilation.video_path),
                file_size_bytes=compilation.video_path.stat().st_size,
                duration_secs=compilation.duration_secs,
                resolution="1080x1920",
            )

            # ── 3. Build metadata ─────────────────────────────────────────
            title       = _build_weekly_title()
            description = _build_weekly_description(
                compilation.clip_count, compilation.duration_secs
            )
            tags = list(dict.fromkeys(
                ["psychology compilation", "psychology facts compilation",
                 "weekly psychology", "brain facts"] + YT_DEFAULT_TAGS
            ))

            # ── 4. Upload ─────────────────────────────────────────────────
            if self._dry_run:
                logger.info("[Weekly] DRY RUN — skipping YouTube upload.")
                return WeeklyPipelineResult(
                    success=True,
                    video_id=video_id,
                    duration_secs=compilation.duration_secs,
                    clip_count=compilation.clip_count,
                )

            stage = "upload"
            logger.info("[Weekly] Uploading compilation …")
            upload = self._uploader.upload_compilation(
                video_path=compilation.video_path,
                video_id=video_id,
                title=title,
                description=description,
                tags=tags,
                topic="weekly psychology compilation",
                privacy=self._privacy,
            )

            if upload.success:
                logger.info(
                    "[Weekly] Uploaded: %s  %s",
                    upload.youtube_video_id, upload.youtube_url,
                )
                return WeeklyPipelineResult(
                    success=True,
                    video_id=video_id,
                    youtube_video_id=upload.youtube_video_id,
                    youtube_url=upload.youtube_url,
                    duration_secs=compilation.duration_secs,
                    clip_count=compilation.clip_count,
                )
            else:
                return WeeklyPipelineResult(
                    success=False,
                    video_id=video_id,
                    clip_count=compilation.clip_count,
                    error=f"upload_failed: {upload.error_message}",
                )

        except Exception as exc:
            logger.exception("[Weekly] Stage='%s' error: %s", stage, exc)
            return WeeklyPipelineResult(success=False, error=f"{stage}: {exc}")


# ── Entry point ─────────────────────────────────────────────────────────────

def run_weekly_compilation(
    dry_run:   bool = False,
    privacy:   str  = "public",
    max_clips: int  = COMPILATION_MAX_CLIPS,
) -> WeeklyPipelineResult:
    """
    Top-level function called by main.py.

    Parameters
    ----------
    dry_run   : Skip YouTube upload.
    privacy   : YouTube privacy ('public' | 'unlisted' | 'private').
    max_clips : Max Shorts to include in the compilation.

    Returns
    -------
    WeeklyPipelineResult.
    """
    log_pipeline_start("weekly")
    validate_all()

    db       = Database()
    pipeline = WeeklyPipeline(
        db=db, dry_run=dry_run, privacy=privacy, max_clips=max_clips
    )
    result = pipeline.run()

    log_pipeline_end(
        "weekly",
        success=result.success,
        detail=(
            f"yt_id={result.youtube_video_id}  "
            f"clips={result.clip_count}  "
            f"duration={result.duration_secs:.1f}s"
            if result.success else result.error
        ),
    )

    stats = db.stats()
    logger.info("DB stats: %s", stats)

    return result

"""
pipelines/run_short.py
======================
Orchestrates a single Short end-to-end:
  research → script → tts → visuals → edit → upload → DB log

Produces one finished, uploaded YouTube Short per invocation.
Called N times (default: 4) by main.py for each daily run.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.api_keys import validate_all
from config.settings import DAILY_SHORTS_COUNT
from core.research import ResearchEngine, TopicSeed
from core.script_generator import GenerationError, ScriptGenerator
from core.tts import TTSEngine
from core.video_editor import VideoEditor
from core.visuals import VisualsEngine
from database.db import Database
from upload.quota_tracker import QuotaTracker
from upload.uploader import YouTubeUploader
from utils.logger import get_logger, log_pipeline_end, log_pipeline_start

logger = get_logger(__name__)


@dataclass
class ShortPipelineResult:
    """Outcome of one complete Short pipeline run."""
    success:          bool
    script_id:        Optional[str] = None
    video_id:         Optional[str] = None
    youtube_video_id: Optional[str] = None
    youtube_url:      Optional[str] = None
    duration_secs:    Optional[float] = None
    topic:            Optional[str] = None
    error:            Optional[str] = None


class ShortPipeline:
    """
    Runs a single Short through every stage of the pipeline.

    Parameters
    ----------
    db          : Shared Database instance (created if None).
    dry_run     : If True, skip the YouTube upload step.
    privacy     : YouTube privacy status ('public' | 'unlisted' | 'private').
    """

    def __init__(
        self,
        db:      Optional[Database] = None,
        dry_run: bool = False,
        privacy: str  = "public",
    ) -> None:
        self._db        = db or Database()
        self._dry_run   = dry_run
        self._privacy   = privacy

        self._research   = ResearchEngine()
        self._generator  = ScriptGenerator(db=self._db)
        self._tts        = TTSEngine()
        self._visuals    = VisualsEngine()
        self._editor     = VideoEditor()
        self._uploader   = YouTubeUploader(db=self._db)
        self._tracker    = QuotaTracker(db=self._db)

    # ── Public ─────────────────────────────────────────────────────────────

    def run(self, seed: Optional[TopicSeed] = None) -> ShortPipelineResult:
        """
        Execute all pipeline stages for one Short.

        Parameters
        ----------
        seed : Pre-fetched TopicSeed.  If None, one is fetched from Tavily.

        Returns
        -------
        ShortPipelineResult — always returns (never raises) so the batch
        runner can collect partial successes.
        """
        stage = "init"
        try:
            # ── 1. Research ────────────────────────────────────────────────
            stage = "research"
            if seed is None:
                seeds = self._research.get_topic_seeds(count=1)
                seed  = seeds[0]
            logger.info("[Short] Topic: '%s'", seed.keyword)

            # ── 2. Script generation + dedup ──────────────────────────────
            stage = "script"
            script = self._generator.generate(seed=seed)
            logger.info(
                "[Short] Script ready: id=%s hook='%s'",
                script.script_id, script.hook[:60],
            )

            # ── 3. TTS audio ───────────────────────────────────────────────
            stage = "tts"
            tts = self._tts.generate(
                hook=script.hook,
                body=script.body,
                script_id=script.script_id,
            )
            logger.info(
                "[Short] TTS done: %.2fs audio  hook_end=%.2fs",
                tts.duration_secs, tts.hook_end_secs,
            )

            # ── 4. Visuals ─────────────────────────────────────────────────
            stage = "visuals"
            clip = self._visuals.fetch_clip(
                topic=script.topic,
                required_duration=tts.duration_secs + 2.0,   # headroom
            )
            logger.info(
                "[Short] Clip fetched: %s (%ds, source=%s)",
                clip.local_path.name, clip.duration, clip.source,
            )

            # ── 5. Video edit ──────────────────────────────────────────────
            stage = "edit"
            edit = self._editor.render(
                script_id=script.script_id,
                hook_text=script.hook,
                body_text=script.body,
                tts_result=tts,
                clip_result=clip,
            )
            logger.info(
                "[Short] Video rendered: %s  %.2fs  zoom-%s@%.3f",
                edit.video_path.name,
                edit.duration_secs,
                edit.zoom_direction,
                edit.zoom_factor,
            )

            # ── 6. DB — log video ─────────────────────────────────────────
            stage = "db_video"
            video_id = self._db.insert_video(
                script_id=script.script_id,
                video_type="short",
                file_path=str(edit.video_path),
                file_size_bytes=edit.video_path.stat().st_size,
                duration_secs=edit.duration_secs,
                resolution="1080x1920",
            )
            self._db.mark_script_used(script.script_id)

            # ── 7. Upload ──────────────────────────────────────────────────
            if self._dry_run:
                logger.info("[Short] DRY RUN — skipping YouTube upload.")
                return ShortPipelineResult(
                    success=True,
                    script_id=script.script_id,
                    video_id=video_id,
                    duration_secs=edit.duration_secs,
                    topic=script.topic,
                )

            stage = "upload"
            upload = self._uploader.upload_short(
                video_path=edit.video_path,
                video_id=video_id,
                title=script.title,
                description=script.description,
                tags=script.tags,
                topic=script.topic,
                privacy=self._privacy,
            )

            if upload.success:
                logger.info(
                    "[Short] Uploaded: %s  %s",
                    upload.youtube_video_id, upload.youtube_url,
                )
                return ShortPipelineResult(
                    success=True,
                    script_id=script.script_id,
                    video_id=video_id,
                    youtube_video_id=upload.youtube_video_id,
                    youtube_url=upload.youtube_url,
                    duration_secs=edit.duration_secs,
                    topic=script.topic,
                )
            else:
                logger.error("[Short] Upload failed: %s", upload.error_message)
                return ShortPipelineResult(
                    success=False,
                    script_id=script.script_id,
                    video_id=video_id,
                    topic=script.topic,
                    error=f"upload_failed: {upload.error_message}",
                )

        except GenerationError as exc:
            logger.error("[Short] Stage='%s' GenerationError: %s", stage, exc)
            return ShortPipelineResult(success=False, error=f"{stage}: {exc}")
        except Exception as exc:
            logger.exception("[Short] Stage='%s' unexpected error: %s", stage, exc)
            return ShortPipelineResult(success=False, error=f"{stage}: {exc}")


# ── Batch runner ────────────────────────────────────────────────────────────

def run_daily_batch(
    count:   int  = DAILY_SHORTS_COUNT,
    dry_run: bool = False,
    privacy: str  = "public",
) -> list[ShortPipelineResult]:
    """
    Generate and upload `count` Shorts in sequence.

    Fetches all topic seeds upfront, then processes each one.
    Failures on individual Shorts are logged and skipped so a single
    bad clip doesn't abort the entire daily batch.

    Parameters
    ----------
    count   : Number of Shorts to produce (default from settings).
    dry_run : Skip YouTube upload step.
    privacy : YouTube privacy status.

    Returns
    -------
    List of ShortPipelineResult, one per attempted Short.
    """
    log_pipeline_start("short")
    validate_all()

    db       = Database()
    research = ResearchEngine()
    pipeline = ShortPipeline(db=db, dry_run=dry_run, privacy=privacy)

    logger.info("Daily batch: generating %d Shorts …", count)
    seeds   = research.get_topic_seeds(count=count)
    results: list[ShortPipelineResult] = []

    for i, seed in enumerate(seeds, 1):
        logger.info("── Short %d/%d ─────────────────────────", i, count)
        result = pipeline.run(seed=seed)
        results.append(result)

        # Brief cooldown between uploads (anti-bot humanization)
        if i < count:
            import random
            cooldown = random.uniform(8.0, 25.0)
            logger.info("Cooldown: %.1fs before next Short …", cooldown)
            time.sleep(cooldown)

    successes = sum(1 for r in results if r.success)
    log_pipeline_end(
        "short",
        success=successes > 0,
        detail=f"{successes}/{count} Shorts succeeded",
    )

    stats = db.stats()
    logger.info("DB stats: %s", stats)

    return results

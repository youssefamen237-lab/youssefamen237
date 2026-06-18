"""
pipelines/longform_pipeline.py

End-to-end production of ONE long-form (5-8 minute, 1920x1080) video.
Mirrors short_pipeline.py but with: more facts, longer script (15-25
segments), landscape media, and thumbnail generation.
"""
from __future__ import annotations
import os, shutil, tempfile
from dataclasses import dataclass
from typing import Optional
import structlog

from storage.supabase_client import get_db
from storage.redis_client import get_redis
from storage.r2_client import R2Paths, get_r2

from engines.topic_selector import get_topic_selector, TopicSelection
from engines.fact_research import get_fact_research
from engines.script_writer import get_script_writer
from engines.voice_generator import get_voice_generator
from engines.media_fetcher import get_media_fetcher
from engines.subtitle_engine import get_subtitle_engine
from engines.video_assembler import get_assembler, VideoAssemblyJob
from engines.metadata_generator import get_metadata_generator
from engines.thumbnail_generator import get_thumbnail_generator
from engines.quality_gate import get_quality_gate, QualityGateInput

from intelligence.hook_selector import get_hook_selector
from intelligence.music_selector import get_music_selector

from protection.policy_guard import get_policy_guard
from protection.fact_verifier import get_fact_verifier
from protection.duplicate_guard import get_duplicate_guard
from protection.visual_verifier import get_visual_verifier
from protection.copyright_checker import get_copyright_checker

from pipelines.short_pipeline import PipelineResult

logger = structlog.get_logger(__name__)

_MAX_TOPIC_ATTEMPTS    = 4
_FACT_COUNT            = 18
_VISUAL_MIN_CONFIDENCE = 55


class LongformPipeline:

    def __init__(self) -> None:
        self._db        = get_db()
        self._redis     = get_redis()
        self._r2        = get_r2()

        self._topic_sel = get_topic_selector()
        self._facts     = get_fact_research()
        self._script    = get_script_writer()
        self._voice     = get_voice_generator()
        self._media     = get_media_fetcher()
        self._subs      = get_subtitle_engine()
        self._assembler = get_assembler()
        self._meta      = get_metadata_generator()
        self._thumb     = get_thumbnail_generator()
        self._gate      = get_quality_gate()

        self._hooks     = get_hook_selector()
        self._music     = get_music_selector()

        self._policy        = get_policy_guard()
        self._fact_verifier = get_fact_verifier()
        self._dup           = get_duplicate_guard()
        self._visual        = get_visual_verifier()
        self._copyright     = get_copyright_checker()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> PipelineResult:
        excluded_topics: list = []

        for _ in range(_MAX_TOPIC_ATTEMPTS):
            try:
                topic = self._topic_sel.select_next(video_type="long", exclude_ids=excluded_topics)
            except RuntimeError as exc:
                return PipelineResult(False, status="failed", reason=str(exc))

            policy = self._policy.check_topic(topic.topic_name, topic.category)
            if not policy.allowed:
                logger.warning("long_topic_blocked_by_policy", topic=topic.topic_name, reason=policy.reason)
                excluded_topics.append(topic.topic_id)
                self._redis.clear_topic_cooldown(topic.topic_id)
                continue

            result = self._produce_for_topic(topic)

            if result.status == "duplicate_retry":
                excluded_topics.append(topic.topic_id)
                self._redis.clear_topic_cooldown(topic.topic_id)
                continue

            return result

        return PipelineResult(
            False, status="failed",
            reason="Exhausted topic attempts — all duplicates or policy-blocked.",
        )

    # ── Per-topic production ──────────────────────────────────────────────────

    def _produce_for_topic(self, topic: TopicSelection) -> PipelineResult:
        job = self._db.create_video_job(topic_id=topic.topic_id, video_type="long", priority=5)
        queue_id = job["queue_id"]
        work_dir = tempfile.mkdtemp(prefix=f"yta_long_{queue_id[:8]}_")

        try:
            return self._run_stages(queue_id, topic, work_dir)
        except Exception as exc:
            logger.error("long_pipeline_exception", queue_id=queue_id[:8], error=str(exc)[:300])
            self._db.log_job_error(queue_id, "pipeline", str(exc)[:500])
            return PipelineResult(False, queue_id=queue_id, status="failed", reason=str(exc)[:300])
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ── Stage pipeline ────────────────────────────────────────────────────────

    def _run_stages(self, queue_id: str, topic: TopicSelection, work_dir: str) -> PipelineResult:
        db = self._db

        # ── Research ─────────────────────────────────────────────────────────
        db.update_video_status(queue_id, "researching")
        facts = self._facts.research(topic.topic_id, topic.topic_name, topic.category, count=_FACT_COUNT)
        facts = self._fact_verifier.verify_facts(facts, topic.topic_name)
        facts = self._fact_verifier.filter_usable(facts)
        facts = self._policy.filter_facts(facts)

        # ── Hook + Script ────────────────────────────────────────────────────
        db.update_video_status(queue_id, "scripting")
        hook_type = self._hooks.select_hook_type(topic.topic_dna, topic.category)
        hook = self._hooks.select_hook(hook_type, topic.topic_name)

        script = self._script.write_script(
            topic_name=topic.topic_name, category=topic.category,
            facts=facts, video_type="long", hook_type=hook_type,
        )
        if hook.hook_id is not None:
            script["hook"] = hook.hook_text
            sentences = [script["hook"]] + [s["sentence"] for s in script["segments"]]
            script["full_text"] = " ".join(s.strip() for s in sentences if s.strip())

        policy_check = self._policy.check_script_text(script["full_text"])
        if not policy_check.allowed:
            db.update_video_status(queue_id, "rejected", extra={
                "script": script,
                "rejection_reason": f"policy:{policy_check.reason}",
            })
            return PipelineResult(True, queue_id=queue_id, status="rejected", reason=policy_check.reason)

        dup = self._dup.check_full_text(script["full_text"])
        if dup.is_duplicate:
            db.update_video_status(queue_id, "rejected", extra={
                "script": script,
                "rejection_reason": f"duplicate:{dup.reason}",
            })
            return PipelineResult(True, queue_id=queue_id, status="duplicate_retry", reason=dup.reason)

        # ── Voice ────────────────────────────────────────────────────────────
        db.update_video_status(queue_id, "voicing", extra={"script": script})
        voice = self._voice.generate(
            script_text=script["full_text"], queue_id=queue_id,
            gender=self._pick_gender(), local_dir=work_dir,
        )

        # ── Media ────────────────────────────────────────────────────────────
        db.update_video_status(queue_id, "fetching_media", extra={
            "voice_gender":  voice.voice_gender,
            "voice_id":      voice.voice_id,
            "audio_r2_path": voice.r2_audio_path,
        })
        media_dir = os.path.join(work_dir, "media")
        media_items = self._media.fetch_all_segments(script["segments"], media_dir, video_type="long")
        media_items = self._visual.verify_batch(
            media_items, topic.topic_name, topic.category, min_confidence=_VISUAL_MIN_CONFIDENCE
        )
        media_items = self._refetch_missing(media_items, script["segments"], media_dir, topic, "long")

        # ── Subtitles + Music ────────────────────────────────────────────────
        srt_path = os.path.join(work_dir, "subtitles.srt")
        self._subs.generate_srt(
            alignment=voice.alignment, output_path=srt_path,
            full_text=script["full_text"], audio_duration=voice.duration_seconds,
        )
        music = self._music.select_track(topic.category, download_dir=work_dir)

        # ── Assembly ─────────────────────────────────────────────────────────
        db.update_video_status(queue_id, "assembling")
        final_path = os.path.join(work_dir, "final.mp4")
        self._assembler.assemble(VideoAssemblyJob(
            queue_id=queue_id, video_type="long",
            audio_path=voice.local_audio_path,
            media_items=media_items,
            output_path=final_path,
            subtitle_path=srt_path,
            music_path=music.local_path,
            alignment=voice.alignment,
            script_segments=script["segments"],
        ))

        # ── Metadata ─────────────────────────────────────────────────────────
        meta = self._meta.generate(
            topic_name=topic.topic_name, category=topic.category,
            script=script, facts=facts, video_type="long",
        )

        title_dup = self._dup.check_title(meta.title)
        if title_dup.is_duplicate:
            db.update_video_status(queue_id, "rejected", extra={
                "rejection_reason": f"duplicate_title:{title_dup.reason}",
            })
            return PipelineResult(True, queue_id=queue_id, status="duplicate_retry", reason=title_dup.reason)

        # ── Thumbnail ────────────────────────────────────────────────────────
        thumb_paths = self._thumb.generate(
            video_path=final_path, title=meta.title, hook=script["hook"],
            topic_name=topic.topic_name, output_dir=work_dir, count=1,
        )
        thumb_local = thumb_paths[0]

        # ── Quality Gate ─────────────────────────────────────────────────────
        db.update_video_status(queue_id, "quality_check")
        qscore = self._gate.score(QualityGateInput(
            queue_id=queue_id, topic_name=topic.topic_name, category=topic.category,
            curiosity_score=topic.curiosity_score, visual_availability=topic.visual_availability,
            facts=facts, media_items=media_items, script=script,
            audio_path=voice.local_audio_path, audio_duration=voice.duration_seconds,
            title=meta.title, description=meta.description, hashtags=meta.hashtags,
        ))

        if not qscore.passed:
            db.update_video_status(queue_id, "rejected", extra={
                "quality_score":    qscore.total,
                "gate_scores":      qscore.gate_scores,
                "rejection_reason": qscore.rejection_reason,
                "title":            meta.title,
                "description":      meta.description,
                "hashtags":         meta.hashtags,
            })
            return PipelineResult(
                True, queue_id=queue_id, status="rejected",
                quality_score=qscore.total, reason=qscore.rejection_reason,
            )

        # ── Upload deliverables to R2 ────────────────────────────────────────
        final_r2_key = R2Paths.final_video(queue_id)
        self._r2.upload_file(final_path, final_r2_key, content_type="video/mp4")

        thumb_r2_key: Optional[str] = R2Paths.thumbnail(queue_id)
        try:
            self._r2.upload_file(thumb_local, thumb_r2_key, content_type="image/jpeg")
        except Exception:
            thumb_r2_key = None

        sub_r2_key: Optional[str] = R2Paths.subtitle(queue_id)
        try:
            self._r2.upload_file(srt_path, sub_r2_key, content_type="text/plain")
        except Exception:
            sub_r2_key = None

        # ── Register assets / dedup / hook usage ────────────────────────────
        self._copyright.register_assets(
            media_items, queue_id, topic_tags=[topic.topic_name.lower(), topic.category]
        )
        self._dup.register(script["full_text"], meta.title, script["full_text"])
        self._hooks.register_usage(hook)

        # ── Approve ──────────────────────────────────────────────────────────
        db.update_video_status(queue_id, "approved", extra={
            "final_video_r2_path": final_r2_key,
            "thumbnail_r2_path":   thumb_r2_key,
            "subtitle_r2_path":    sub_r2_key,
            "title":               meta.title,
            "description":         meta.description,
            "hashtags":            meta.hashtags,
            "quality_score":       qscore.total,
            "gate_scores":         qscore.gate_scores,
        })

        logger.info(
            "long_video_approved",
            queue_id=queue_id[:8], topic=topic.topic_name, score=qscore.total,
            segments=len(script["segments"]), duration=round(voice.duration_seconds, 1),
        )
        return PipelineResult(True, queue_id=queue_id, status="approved", quality_score=qscore.total)

    # ── Helpers (shared logic with ShortPipeline) ────────────────────────────

    def _pick_gender(self) -> str:
        try:
            rule = self._db.get_rule("voice_split")
            weights = rule if isinstance(rule, dict) else {"female": 70, "male": 30}
        except Exception:
            weights = {"female": 70, "male": 30}

        import random
        items = [(k, max(0, int(v))) for k, v in weights.items() if k in ("female", "male")]
        if not items:
            return "female"

        total = sum(w for _, w in items) or 1
        r = random.uniform(0, total)
        cumulative = 0.0
        for gender, w in items:
            cumulative += w
            if r <= cumulative:
                return gender
        return "female"

    def _refetch_missing(
        self, media_items: list, segments: list, media_dir: str,
        topic: TopicSelection, video_type: str,
    ) -> list:
        retry_indices = [i for i, m in enumerate(media_items) if m is None]
        if not retry_indices:
            return media_items

        broadened = [
            {
                "sentence":     segments[i].get("sentence", topic.topic_name),
                "search_query": topic.topic_name,
            }
            for i in retry_indices
        ]

        new_items = self._media.fetch_all_segments(broadened, media_dir, video_type=video_type)
        new_items = self._visual.verify_batch(
            new_items, topic.topic_name, topic.category, min_confidence=_VISUAL_MIN_CONFIDENCE
        )

        for idx, item in zip(retry_indices, new_items):
            media_items[idx] = item

        return media_items


_instance: Optional[LongformPipeline] = None

def get_longform_pipeline() -> LongformPipeline:
    global _instance
    if _instance is None:
        _instance = LongformPipeline()
    return _instance

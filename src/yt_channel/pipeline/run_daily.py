from __future__ import annotations

import json
import logging
import os
import random
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.settings import Settings
from ..dedupe import DedupeEngine
from ..logging_setup import setup_logging
from ..question_bank import DatasetRegistry, QuestionGenerator
from ..question_bank.safety import SafetyFilter
from ..render.ffmpeg import ffprobe_duration
from ..render.shorts_templates import BrandKit, render_short
from ..render.thumbnail import ThumbnailStyle, make_long_thumbnail
from ..providers import ProviderManager
from ..seo import Copywriter
from ..state import StateDB
from ..utils.hashing import sha256_hex
from ..utils.text import normalize_for_hash
from ..brain.bandit import BetaBandit
from ..brain.analyzer import Analyzer
from ..brain.planner import Planner, PlannedVideo
from ..youtube import build_youtube_service, build_analytics_service, YouTubeUploader, YouTubeMetricsFetcher

logger = logging.getLogger(__name__)


@dataclass
class VideoOutcome:
    kind: str
    status: str
    plan: Dict[str, Any]
    video_id: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None


@dataclass
class RunReport:
    run_id: str
    run_enabled: bool
    dry_run: bool
    outcomes: List[VideoOutcome]
    errors: List[str]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_text_or_raise(safety: SafetyFilter, text: str, field: str) -> None:
    if not safety.is_safe(text):
        raise RuntimeError(f"Blocked by safety filter: {field}")


def _pick_unique_question(
    *,
    qgen: QuestionGenerator,
    dedupe: DedupeEngine,
    db: StateDB,
    safety: SafetyFilter,
    topic: str,
    template_id: str,
    answer_cooldown_days: int,
    max_tries: int = 60,
):
    recent_q = db.recent_questions(limit=250)
    recent_titles = db.recent_titles(limit=80)

    for _ in range(max_tries):
        item = qgen.generate(topic=topic, template_id=template_id)
        if not item:
            continue

        # Safety
        if not safety.is_safe(item.question_text) or not safety.is_safe(item.answer_text):
            continue

        # Answer cooldown
        ans_key = sha256_hex("answer:" + normalize_for_hash(item.answer_text))
        if db.is_answer_on_cooldown(ans_key, cooldown_days=answer_cooldown_days):
            continue

        dq = dedupe.check_text(kind="question", text=item.question_text, recent_pool=recent_q)
        if not dq.ok:
            continue

        da = dedupe.check_text(kind="answer", text=item.answer_text, recent_pool=[])
        if not da.ok:
            continue

        # Title/description repetition handled later, but also avoid near duplicate question-as-title patterns
        if any(normalize_for_hash(item.question_text).startswith(normalize_for_hash(t)[:30]) for t in recent_titles):
            pass

        # Register
        dedupe.register_text(kind="question", text=item.question_text)
        dedupe.register_text(kind="answer", text=item.answer_text)
        db.touch_answer(ans_key)
        return item

    raise RuntimeError("Unable to find a unique safe question (dedupe exhausted)")


def _write_artifacts(settings: Settings, report: RunReport) -> None:
    _ensure_dir(settings.artifacts_dir)
    json_path = settings.artifacts_dir / "run_report.json"
    md_path = settings.artifacts_dir / "run_report.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False)

    lines = []
    lines.append(f"# Run Report\n")
    lines.append(f"Run ID: `{report.run_id}`\n")
    lines.append(f"RUN_ENABLED: `{report.run_enabled}`\n")
    lines.append(f"DRY_RUN: `{report.dry_run}`\n")
    lines.append("\n## Outcomes\n")
    for o in report.outcomes:
        vid = o.video_id or "-"
        title = o.title or "-"
        lines.append(f"- **{o.kind}** — {o.status} — {vid} — {title}\n")
        if o.error:
            lines.append(f"  - Error: {o.error}\n")
    if report.errors:
        lines.append("\n## Errors\n")
        for e in report.errors:
            lines.append(f"- {e}\n")

    md_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    setup_logging()

    settings = Settings.from_yaml_defaults()
    _ensure_dir(settings.out_dir)
    _ensure_dir(settings.state_dir)

    run_id = uuid.uuid4().hex[:12]
    report = RunReport(run_id=run_id, run_enabled=settings.run_enabled, dry_run=settings.dry_run, outcomes=[], errors=[])

    db_path = settings.state_dir / "channel.db"
    db = StateDB(db_path)

    safety = SafetyFilter(settings.banned_keywords_file)

    # Providers / RNG
    rng = random.Random()
    rng.seed(int.from_bytes(os.urandom(8), "big") ^ int(uuid.uuid4().int & 0xFFFFFFFF))

    datasets = DatasetRegistry(settings.datasets_dir)
    qgen = QuestionGenerator(rng=rng, datasets=datasets)

    dedupe = DedupeEngine(db=db, fuzzy_threshold=settings.fuzzy_threshold, semantic_enabled=True)

    providers = ProviderManager(settings=settings, db=db, rng=rng, safety=safety)

    # YouTube clients
    youtube_service = None
    analytics_service = None
    uploader = None
    metrics_fetcher = None

    if not settings.dry_run:
        try:
            youtube_service = build_youtube_service(
                client_id=settings.yt_client_id,
                client_secret=settings.yt_client_secret,
                refresh_token=settings.yt_refresh_token,
            )
            uploader = YouTubeUploader(service=youtube_service, rng=rng)
            if settings.analytics_enabled:
                try:
                    analytics_service = build_analytics_service(
                        client_id=settings.yt_client_id,
                        client_secret=settings.yt_client_secret,
                        refresh_token=settings.yt_refresh_token,
                    )
                except Exception:
                    analytics_service = None
            metrics_fetcher = YouTubeMetricsFetcher(youtube_service=youtube_service, analytics_service=analytics_service)
        except Exception as e:
            logger.exception("YouTube auth init failed")
            report.errors.append(f"YouTube auth init failed: {e}")
            youtube_service = None
            uploader = None

    # If this is a real run, we must have a working uploader.
    if not settings.dry_run and uploader is None:
        report.errors.append(
            "Fatal: YouTube uploader is unavailable. Check OAuth secrets (YT_CLIENT_ID_*, "
            "YT_CLIENT_SECRET_*, YT_REFRESH_TOKEN_*) and that the refresh token includes YouTube upload scopes."
        )
        _write_artifacts(settings, report)
        logger.error("Fatal: YouTube uploader is unavailable; aborting real run.")
        raise SystemExit(1)

    # Analyzer / bandit
    bandit = BetaBandit(rng=rng, db=db)
    if metrics_fetcher is not None:
        analyzer = Analyzer(db=db, metrics=metrics_fetcher, bandit=bandit)
        try:
            analyzer.refresh_metrics(days_back=min(30, settings.analytics_days_back))
            analyzer.update_bandit_from_recent(days_back=14)
        except Exception as e:
            logger.warning("Analyzer failed: %s", e)
            report.errors.append(f"Analyzer failed: {e}")
    else:
        analyzer = None

    if not settings.run_enabled:
        _write_artifacts(settings, report)
        return

    planner = Planner(settings=settings, db=db, bandit=bandit, rng=rng)
    plans = planner.plan_daily()

    # Brand kit
    font_regular = settings.fonts_dir / "DejaVuSans.ttf"
    font_bold = settings.fonts_dir / "DejaVuSans-Bold.ttf"
    brand = BrandKit(font_regular=font_regular, font_bold=font_bold)

    copywriter = Copywriter(rng=rng, db=db)

    # Execute plan
    for plan in plans:
        outcome = VideoOutcome(kind=plan.kind, status="planned", plan=asdict(plan))
        report.outcomes.append(outcome)

        try:
            if plan.kind == "short":
                item = _pick_unique_question(
                    qgen=qgen,
                    dedupe=dedupe,
                    db=db,
                    safety=safety,
                    topic=plan.topic,
                    template_id=plan.template_id,
                    answer_cooldown_days=settings.answer_cooldown_days,
                )

                seo = copywriter.make(kind="short", topic=item.topic, question_text=item.question_text)
                _safe_text_or_raise(safety, seo.title, "title")
                _safe_text_or_raise(safety, seo.description, "description")

                bg_pick = providers.pick_background()

                tts_out = settings.out_dir / "tts" / f"{run_id}_{item.question_id}.mp3"
                tts_res = providers.tts_question(text=item.question_text, gender=plan.voice_gender, out_path=tts_out)

                tts_dur = ffprobe_duration(tts_res.audio_path)

                music_pick = None
                if plan.with_music and settings.music_enabled_default:
                    music_pick = providers.pick_music()

                out_vid = settings.out_dir / "shorts" / f"{run_id}_{item.question_id}_{plan.template_id}.mp4"

                w, h = (int(x) for x in settings.shorts_resolution.split("x"))

                render_short(
                    out_path=out_vid,
                    bg_image=bg_pick.path,
                    question_text=item.question_text,
                    answer_text=item.answer_text,
                    choices=item.choices,
                    template_id=plan.template_id,
                    tts_audio=tts_res.audio_path,
                    tts_duration=tts_dur,
                    music_audio=music_pick.path if music_pick else None,
                    music_volume_db=settings.music_volume_db,
                    countdown_seconds=plan.countdown_seconds,
                    answer_seconds=plan.answer_seconds,
                    fps=settings.shorts_fps,
                    resolution=(w, h),
                    brand=brand,
                    with_music=bool(plan.with_music and music_pick is not None),
                )

                metadata = {
                    "slot": plan.slot,
                    "with_music": bool(plan.with_music and music_pick is not None),
                    "tts_provider": tts_res.provider_key,
                    "bg_provider": bg_pick.provider_key,
                    "music_provider": music_pick.provider_key if music_pick else None,
                    "bg_image_id": bg_pick.asset_id,
                    "music_track_id": music_pick.asset_id if music_pick else None,
                    "title_style_id": seo.title_style_id,
                }

                # Record planned row before upload
                db.add_video_record(
                    kind="short",
                    publish_at=plan.publish_at or "NOW",
                    template_id=plan.template_id,
                    topic=item.topic,
                    difficulty=item.difficulty,
                    countdown_seconds=plan.countdown_seconds,
                    voice_gender=plan.voice_gender,
                    music_track_id=music_pick.asset_id if music_pick else "",
                    bg_image_id=bg_pick.asset_id,
                    title_style_id=seo.title_style_id,
                    question_id=item.question_id,
                    question_text=item.question_text,
                    answer_text=item.answer_text,
                    title=seo.title,
                    description=seo.description,
                    tags=seo.tags,
                    metadata=metadata,
                    status="rendered",
                )

                video_id = None
                if not settings.dry_run and uploader is not None:
                    res = uploader.upload_video(
                        video_path=out_vid,
                        title=seo.title,
                        description=seo.description,
                        tags=seo.tags,
                        category_id=settings.yt_category_id_shorts,
                        privacy_status=plan.privacy_status,
                        publish_at=plan.publish_at,
                        thumbnail_path=None,
                        is_made_for_kids=False,
                    )
                    video_id = res.video_id
                    db.mark_uploaded(question_id=item.question_id, video_id=video_id)

                outcome.status = "ok"
                outcome.video_id = video_id
                outcome.title = seo.title

            elif plan.kind == "long":
                # Long-form episode (new content, not a shorts compilation)
                # Build episode questions
                questions = []
                for _ in range(40):
                    q = _pick_unique_question(
                        qgen=qgen,
                        dedupe=dedupe,
                        db=db,
                        safety=safety,
                        topic=rng.choice(["capital", "flag", "currency", "planets", "math"]),
                        template_id="classic",
                        answer_cooldown_days=settings.answer_cooldown_days,
                    )
                    questions.append(q)

                # Long title & SEO
                long_focus = "Capitals, Flags & Quick Trivia"
                seo = copywriter.make(kind="long", topic="episode_mix", question_text=long_focus)
                _safe_text_or_raise(safety, seo.title, "title")
                _safe_text_or_raise(safety, seo.description, "description")

                bg_pick = providers.pick_background()

                # Render a simplified long episode by concatenating segments
                from ..render.long_templates import render_long_episode

                out_vid = settings.out_dir / "long" / f"{run_id}_episode.mp4"
                thumb_path = settings.out_dir / "long" / f"{run_id}_thumb.jpg"

                w, h = (int(x) for x in settings.long_resolution.split("x"))

                render_long_episode(
                    out_path=out_vid,
                    bg_image=bg_pick.path,
                    questions=questions,
                    providers=providers,
                    voice_gender=plan.voice_gender,
                    countdown_seconds=plan.countdown_seconds,
                    answer_seconds=plan.answer_seconds,
                    fps=settings.long_fps,
                    resolution=(w, h),
                    brand=brand,
                    music_enabled=True,
                    music_pick=providers.pick_music(),
                    music_volume_db=settings.music_volume_db,
                )

                make_long_thumbnail(
                    out_path=thumb_path,
                    bg_image=bg_pick.path,
                    title_text=seo.title,
                    style=ThumbnailStyle(font_bold=font_bold, font_regular=font_regular),
                    rng=rng,
                )

                metadata = {
                    "slot": plan.slot,
                    "with_music": True,
                    "bg_provider": bg_pick.provider_key,
                    "bg_image_id": bg_pick.asset_id,
                    "title_style_id": seo.title_style_id,
                }

                db.add_video_record(
                    kind="long",
                    publish_at=plan.publish_at or "",
                    template_id=plan.template_id,
                    topic="episode_mix",
                    difficulty=2,
                    countdown_seconds=plan.countdown_seconds,
                    voice_gender=plan.voice_gender,
                    music_track_id="",
                    bg_image_id=bg_pick.asset_id,
                    title_style_id=seo.title_style_id,
                    question_id=f"episode_{run_id}",
                    question_text="",
                    answer_text="",
                    title=seo.title,
                    description=seo.description,
                    tags=seo.tags,
                    metadata=metadata,
                    status="rendered",
                )

                video_id = None
                if not settings.dry_run and uploader is not None:
                    res = uploader.upload_video(
                        video_path=out_vid,
                        title=seo.title,
                        description=seo.description,
                        tags=seo.tags,
                        category_id=settings.yt_category_id_long,
                        privacy_status=plan.privacy_status,
                        publish_at=plan.publish_at,
                        thumbnail_path=thumb_path,
                        is_made_for_kids=False,
                    )
                    video_id = res.video_id
                    db.mark_uploaded(question_id=f"episode_{run_id}", video_id=video_id)

                outcome.status = "ok"
                outcome.video_id = video_id
                outcome.title = seo.title

            else:
                outcome.status = "skipped"

        except Exception as e:
            logger.exception("Plan item failed")
            outcome.status = "failed"
            outcome.error = str(e)
            report.errors.append(str(e))

    _write_artifacts(settings, report)

    # On real runs, fail the workflow if anything did not upload successfully.
    if not settings.dry_run and settings.run_enabled:
        if not report.outcomes:
            logger.error("No planned outcomes produced; failing run.")
            raise SystemExit(1)
        failed = [o for o in report.outcomes if o.status != "ok"]
        if failed:
            logger.error("One or more planned items failed (%d).", len(failed))
            raise SystemExit(1)
        uploaded = [o for o in report.outcomes if o.status == "ok" and o.video_id]
        if not uploaded:
            logger.error("No videos uploaded (missing video_id); failing run.")
            raise SystemExit(1)


if __name__ == "__main__":
    main()

"""
main_pipeline.py
Karma Vault Stories — Main Orchestration Pipeline
Runs the full autonomous media factory in GitHub Actions.
Each engine receives and mutates the DailyRunContext object.
No engine is called in isolation — all outputs chain into the next stage.
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import validate_critical_secrets
from utils.logger import get_logger, PipelineRunLogger
from utils.file_manager import (
    generate_run_id, ensure_run_workspace,
    cleanup_run_workspace, append_publication_log,
    emergency_export, load_json, save_json,
)
from utils.models import DailyRunContext

log = get_logger("main_pipeline")


def build_run_context() -> DailyRunContext:
    run_id = generate_run_id()
    ctx = DailyRunContext(run_id=run_id)
    ctx.force_pillar = os.environ.get("FORCE_PILLAR", "").strip() or None
    ctx.dry_run      = os.environ.get("DRY_RUN", "false").lower() == "true"
    if ctx.force_pillar:
        log.info(f"Force pillar override: {ctx.force_pillar}")
    if ctx.dry_run:
        log.info("DRY RUN MODE — YouTube upload will be skipped.")
    return ctx


def run_pipeline() -> int:
    ctx     = build_run_context()
    run_log = PipelineRunLogger(ctx.run_id)
    ensure_run_workspace(ctx.run_id)

    log.info("=" * 62)
    log.info(f"  KARMA VAULT STORIES — Pipeline Run {ctx.run_id}")
    log.info("=" * 62)

    secrets = validate_critical_secrets()
    log.info(f"Secrets: writing={secrets['writing_available']} | "
             f"tts={secrets['tts_available']} | "
             f"visuals={secrets['visuals_available']} | "
             f"yt_packs={secrets['active_yt_packs']}")

    if not secrets["writing_available"]:
        log.error("CRITICAL: No writing model API key present. Aborting.")
        run_log.finalize(status="failed_no_writing_key")
        return 1


    # ═══════════════════════════════════════════════════════
    # PHASE 7a — ANALYTICS SYNC + HEURISTICS UPDATE
    # Runs BEFORE story selection so learned weights influence today's decisions
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("analytics_collector")
    try:
        from engines.analytics_collector import run_analytics_collector
        ctx = run_analytics_collector(ctx)
        run_log.stage_success("analytics_collector", {})
    except Exception as exc:
        run_log.stage_failure("analytics_collector", exc, fatal=False)
        log.warning("Analytics collection failed (non-fatal) — using existing heuristics.")

    run_log.stage_start("heuristics_engine")
    try:
        from engines.heuristics_engine import run_heuristics_engine
        ctx = run_heuristics_engine(ctx)
        run_log.stage_success("heuristics_engine", {})
    except Exception as exc:
        run_log.stage_failure("heuristics_engine", exc, fatal=False)
        log.warning("Heuristics update failed (non-fatal) — continuing with existing weights.")

    # ═══════════════════════════════════════════════════════
    # PHASE 2 — STORY COLLECTION & SCORING
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("trend_hunter")
    try:
        from engines.trend_hunter import run_trend_hunter
        ctx = run_trend_hunter(ctx)
        run_log.stage_success("trend_hunter", {"signals": len(ctx.trend_signals)})
    except Exception as exc:
        run_log.stage_failure("trend_hunter", exc, fatal=False)
        log.warning("Trend hunter failed — continuing without trend signals.")

    run_log.stage_start("story_collector")
    try:
        from engines.story_collector import run_story_collector
        ctx = run_story_collector(ctx)
        run_log.stage_success("story_collector", {"candidates": len(ctx.raw_candidates)})
    except Exception as exc:
        run_log.stage_failure("story_collector", exc, fatal=False)

    run_log.stage_start("paranormal_collector")
    try:
        from engines.paranormal_collector import run_paranormal_collector
        ctx = run_paranormal_collector(ctx)
        run_log.stage_success("paranormal_collector", {"total": len(ctx.raw_candidates)})
    except Exception as exc:
        run_log.stage_failure("paranormal_collector", exc, fatal=False)

    run_log.stage_start("story_bank_manager")
    try:
        from engines.story_bank_manager import run_story_bank_manager
        ctx = run_story_bank_manager(ctx)
        run_log.stage_success("story_bank_manager", {"total": len(ctx.raw_candidates)})
    except Exception as exc:
        run_log.stage_failure("story_bank_manager", exc, fatal=False)

    if not ctx.raw_candidates:
        log.error("Zero candidates after all collection phases. Aborting.")
        run_log.finalize(status="failed_no_candidates")
        return 1

    run_log.stage_start("story_scorer")
    try:
        from engines.story_scorer import run_story_scorer
        ctx = run_story_scorer(ctx)
        run_log.stage_success("story_scorer", {
            "scored":   len(ctx.scored_candidates),
            "selected": ctx.selected_story.title[:60] if ctx.selected_story else None,
        })
    except Exception as exc:
        run_log.stage_failure("story_scorer", exc, fatal=True)

    if not ctx.selected_story:
        log.error("No story selected. Aborting.")
        run_log.finalize(status="failed_no_story_selected")
        return 1

    try:
        from engines.story_bank_manager import enrich_banks_after_scoring
        enrich_banks_after_scoring(ctx)
    except Exception as exc:
        log.warning(f"Bank enrichment non-fatal: {exc}")

    # ═══════════════════════════════════════════════════════
    # PHASE 3 — SCRIPT WRITING & SEO
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("script_writer")
    try:
        from engines.script_writer import run_script_writer
        ctx = run_script_writer(ctx)
        if not ctx.script_blueprint:
            raise RuntimeError("Script writer produced no blueprint.")
        total_words = sum(
            len((p.get("narration") or "").split())
            for p in ctx.script_blueprint.get("parts", [])
        )
        run_log.stage_success("script_writer", {
            "parts":        len(ctx.script_blueprint.get("parts", [])),
            "total_words":  total_words,
            "duration_sec": ctx.script_blueprint.get("estimated_duration_sec"),
            "voice_gender": ctx.voice_gender,
        })
    except Exception as exc:
        run_log.stage_failure("script_writer", exc, fatal=True)

    run_log.stage_start("seo_optimizer")
    try:
        from engines.seo_optimizer import run_seo_optimizer
        ctx = run_seo_optimizer(ctx)
        if not ctx.seo_metadata:
            raise RuntimeError("SEO optimizer produced no metadata.")
        run_log.stage_success("seo_optimizer", {
            "title":          ctx.seo_metadata.get("title", "")[:70],
            "tags_count":     len(ctx.seo_metadata.get("tags", [])),
            "thumbnail_text": ctx.seo_metadata.get("thumbnail_text", ""),
            "formula_idx":    ctx.seo_metadata.get("formula_idx"),
            "thumb_template": ctx.thumbnail_template_id,
        })
    except Exception as exc:
        run_log.stage_failure("seo_optimizer", exc, fatal=True)

    _save_phase3_artifacts(ctx)


    # ═══════════════════════════════════════════════════════
    # PHASE 4 — VOICE GENERATION & AUDIO MIXING
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("voice_generator")
    try:
        from engines.voice_generator import run_voice_generator
        ctx = run_voice_generator(ctx)
        if not ctx.narration_audio_path:
            raise RuntimeError("Voice generator produced no audio path.")
        run_log.stage_success("voice_generator", {
            "duration_sec":  ctx.narration_duration_sec,
            "provider":      ctx.tts_provider_used,
            "voice_gender":  ctx.voice_gender,
        })
    except Exception as exc:
        run_log.stage_failure("voice_generator", exc, fatal=True)

    run_log.stage_start("audio_mixer")
    try:
        from engines.audio_mixer import run_audio_mixer
        ctx = run_audio_mixer(ctx)
        run_log.stage_success("audio_mixer", {
            "mixed_audio":   ctx.narration_audio_path,
            "final_duration": ctx.narration_duration_sec,
        })
    except Exception as exc:
        run_log.stage_failure("audio_mixer", exc, fatal=False)
        log.warning("Audio mixer failed — continuing with clean narration.")


    # ═══════════════════════════════════════════════════════
    # PHASE 5 — VISUAL SCENE BUILDER + THUMBNAIL
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("scene_builder")
    try:
        from engines.scene_builder import run_scene_builder
        ctx = run_scene_builder(ctx)
        if not ctx.scene_assets:
            raise RuntimeError("Scene builder produced no visual assets.")
        unique_assets = len({s["asset_path"] for s in ctx.scene_assets})
        run_log.stage_success("scene_builder", {
            "total_scenes":  len(ctx.scene_assets),
            "unique_assets": unique_assets,
        })
    except Exception as exc:
        run_log.stage_failure("scene_builder", exc, fatal=True)

    run_log.stage_start("thumbnail_generator")
    try:
        from engines.thumbnail_generator import run_thumbnail_generator
        ctx = run_thumbnail_generator(ctx)
        if not ctx.thumbnail_path:
            raise RuntimeError("Thumbnail generator produced no output.")
        run_log.stage_success("thumbnail_generator", {
            "thumbnail_path": ctx.thumbnail_path,
            "template":       ctx.thumbnail_template_id,
        })
    except Exception as exc:
        run_log.stage_failure("thumbnail_generator", exc, fatal=False)
        log.warning("Thumbnail generation failed (non-fatal) — upload will proceed without thumbnail.")


    # ═══════════════════════════════════════════════════════
    # PHASE 6 — VIDEO RENDERING & SHORTS EXTRACTION
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("video_renderer")
    try:
        from engines.video_renderer import run_video_renderer
        ctx = run_video_renderer(ctx)
        if not ctx.long_video_path:
            raise RuntimeError("Video renderer produced no output file.")
        from pathlib import Path as _P
        vid_mb = _P(ctx.long_video_path).stat().st_size // (1024*1024)
        run_log.stage_success("video_renderer", {
            "long_video_path": ctx.long_video_path,
            "size_mb": vid_mb,
        })
    except Exception as exc:
        run_log.stage_failure("video_renderer", exc, fatal=True)

    run_log.stage_start("shorts_extractor")
    try:
        from engines.shorts_extractor import run_shorts_extractor
        ctx = run_shorts_extractor(ctx)
        if ctx.short_video_path:
            from pathlib import Path as _P
            short_mb = _P(ctx.short_video_path).stat().st_size // (1024*1024)
            run_log.stage_success("shorts_extractor", {
                "short_video_path": ctx.short_video_path,
                "size_mb": short_mb,
            })
        else:
            log.warning("Shorts extractor produced no output (non-fatal).")
            run_log.stage_success("shorts_extractor", {"short_video_path": None})
    except Exception as exc:
        run_log.stage_failure("shorts_extractor", exc, fatal=False)
        log.warning("Shorts extraction failed (non-fatal) — upload will proceed with long video only.")


    # ═══════════════════════════════════════════════════════
    # PHASE 7b — YOUTUBE UPLOAD + EMERGENCY EXPORT
    # ═══════════════════════════════════════════════════════

    run_log.stage_start("youtube_uploader")
    try:
        from engines.youtube_uploader import run_youtube_uploader
        ctx = run_youtube_uploader(ctx)
        run_log.stage_success("youtube_uploader", {
            "video_id":    ctx.youtube_video_id,
            "short_id":    ctx.youtube_short_id,
            "status":      ctx.upload_status,
            "pack_used":   ctx.yt_pack_used,
        })
    except Exception as exc:
        run_log.stage_failure("youtube_uploader", exc, fatal=False)
        log.error("YouTube uploader raised an unexpected exception — triggering emergency export.")
        try:
            from engines.emergency_export import run_emergency_export
            ctx = run_emergency_export(ctx)
        except Exception as ee:
            log.critical(f"Emergency export also failed: {ee}")


    # ═══════════════════════════════════════════════════════

    _log_phase3_summary(ctx, run_log)
    # ── Final run summary ────────────────────────────────────
    final_status = (
        "success" if ctx.youtube_video_id
        else "emergency_exported" if "emergency_export" in ctx.stages_completed
        else "completed_no_upload"
    )
    _log_phase7_summary(ctx, run_log)
    run_log.finalize(status=final_status)
    # Cleanup run workspace to recover disk space
    try:
        from utils.file_manager import cleanup_run_workspace
        cleanup_run_workspace(ctx.run_id, keep_final_outputs=False)
    except Exception:
        pass
    return 0


def _save_phase3_artifacts(ctx: DailyRunContext) -> None:
    ws = Path(os.environ.get("GITHUB_WORKSPACE",
              str(Path(__file__).resolve().parent)))
    artifacts_dir = ws / "run_workspaces" / ctx.run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    try:
        if ctx.script_blueprint:
            bp_path = artifacts_dir / "script_blueprint.json"
            with open(bp_path, "w", encoding="utf-8") as f:
                json.dump(ctx.script_blueprint, f, indent=2,
                          ensure_ascii=False, default=str)
            log.info(f"Script blueprint saved → {bp_path.name}")
        if ctx.seo_metadata:
            seo_path = artifacts_dir / "seo_metadata.json"
            with open(seo_path, "w", encoding="utf-8") as f:
                json.dump(ctx.seo_metadata, f, indent=2,
                          ensure_ascii=False, default=str)
            log.info(f"SEO metadata saved → {seo_path.name}")
    except Exception as exc:
        log.warning(f"Could not save Phase 3 artifacts (non-fatal): {exc}")


def _log_phase3_summary(ctx: DailyRunContext, run_log: PipelineRunLogger) -> None:
    story     = ctx.selected_story
    seo       = ctx.seo_metadata or {}
    blueprint = ctx.script_blueprint or {}
    total_words = sum(
        len((p.get("narration") or "").split())
        for p in blueprint.get("parts", [])
    )
    dur = blueprint.get("estimated_duration_sec", 0)

    log.info("")
    log.info("─" * 62)
    log.info("  PHASE 3 COMPLETE — SUMMARY")
    log.info("─" * 62)
    log.info(f"  Story     : {story.title[:68] if story else 'N/A'}")
    log.info(f"  Country   : {story.country if story else 'N/A'}")
    log.info(f"  Pillar    : {story.pillar if story else 'N/A'}")
    log.info(f"  Score     : {f'{story.weighted_score:.2f}' if story else 'N/A'}")
    log.info(f"  Voice     : {ctx.voice_gender}")
    log.info(f"  YT Title  : {seo.get('title','')[:68]}")
    log.info(f"  Thumb txt : {seo.get('thumbnail_text','')}")
    log.info(f"  Tags      : {len(seo.get('tags',[]))}")
    log.info(f"  Words     : {total_words}")
    log.info(f"  Duration  : {dur // 60}m {dur % 60}s")
    log.info(f"  Stages    : {ctx.stages_completed}")
    log.info("─" * 62)

    run_log.record("phase3_title",          seo.get("title", ""))
    run_log.record("phase3_thumbnail_text", seo.get("thumbnail_text", ""))
    run_log.record("phase3_voice",          ctx.voice_gender)
    run_log.record("phase3_formula_idx",    seo.get("formula_idx"))
    run_log.record("phase3_thumb_template", ctx.thumbnail_template_id)



def _log_phase7_summary(ctx: DailyRunContext, run_log: PipelineRunLogger) -> None:
    seo       = ctx.seo_metadata or {}
    blueprint = ctx.script_blueprint or {}
    story     = ctx.selected_story
    dur       = blueprint.get("estimated_duration_sec", 0)
    log.info("")
    log.info("═" * 62)
    log.info("  KARMA VAULT STORIES — PIPELINE COMPLETE")
    log.info("═" * 62)
    log.info(f"  Run ID    : {ctx.run_id}")
    log.info(f"  Story     : {story.title[:68] if story else 'N/A'}")
    log.info(f"  Country   : {story.country if story else 'N/A'}")
    log.info(f"  Pillar    : {story.pillar if story else 'N/A'}")
    log.info(f"  Voice     : {ctx.voice_gender}")
    log.info(f"  Title     : {seo.get('title','')[:68]}")
    log.info(f"  Duration  : {dur//60}m{dur%60}s")
    log.info(f"  Video ID  : {ctx.youtube_video_id or 'not uploaded'}")
    log.info(f"  Short ID  : {ctx.youtube_short_id or 'not uploaded'}")
    log.info(f"  Status    : {ctx.upload_status}")
    log.info(f"  Stages    : {ctx.stages_completed}")
    log.info("═" * 62)
    run_log.record("youtube_video_id",  ctx.youtube_video_id)
    run_log.record("youtube_short_id",  ctx.youtube_short_id)
    run_log.record("upload_status",     ctx.upload_status)
    run_log.record("final_title",       seo.get("title", ""))
    run_log.record("stages_completed",  ctx.stages_completed)

if __name__ == "__main__":
    sys.exit(run_pipeline())

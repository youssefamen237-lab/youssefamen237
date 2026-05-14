"""
engines/emergency_export.py
Karma Vault Stories — Emergency Export Engine
Called when YouTube upload fails across all 3 credential packs.
Guarantees that generated content is NEVER lost by saving every
deliverable to a persistent, artifact-uploaded directory with a
complete machine-readable manifest for manual recovery or retry.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import (
    EMERGENCY_EXPORT_DIR, append_publication_log, load_json,
)

log = get_logger(__name__)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_emergency_export(ctx: DailyRunContext) -> DailyRunContext:
    """
    Saves all generated deliverables to EMERGENCY_EXPORT_DIR/{run_id}/.
    Creates a full manifest JSON for manual recovery.
    Appends a failure record to the publication log so future
    analytics collection skips this run correctly.
    """
    log.warning(
        f"EMERGENCY EXPORT triggered for run {ctx.run_id}. "
        f"Upload status: {ctx.upload_status}"
    )

    export_dir = EMERGENCY_EXPORT_DIR / ctx.run_id
    export_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Optional[str]] = {
        "long_video":  None,
        "short_video": None,
        "thumbnail":   None,
        "seo_metadata": None,
        "script_blueprint": None,
    }

    # ── Save long video ──────────────────────────────────────────
    if ctx.long_video_path and Path(ctx.long_video_path).exists():
        dest = export_dir / "long_video.mp4"
        shutil.copy2(ctx.long_video_path, str(dest))
        saved["long_video"] = str(dest)
        log.info(f"Emergency export: long_video.mp4 ({dest.stat().st_size // (1024*1024)}MB)")

    # ── Save short video ─────────────────────────────────────────
    if ctx.short_video_path and Path(ctx.short_video_path).exists():
        dest = export_dir / "short_video.mp4"
        shutil.copy2(ctx.short_video_path, str(dest))
        saved["short_video"] = str(dest)
        log.info(f"Emergency export: short_video.mp4 ({dest.stat().st_size // 1024}KB)")

    # ── Save thumbnail ────────────────────────────────────────────
    if ctx.thumbnail_path and Path(ctx.thumbnail_path).exists():
        dest = export_dir / "thumbnail.jpg"
        shutil.copy2(ctx.thumbnail_path, str(dest))
        saved["thumbnail"] = str(dest)
        log.info(f"Emergency export: thumbnail.jpg")

    # ── Save SEO metadata ─────────────────────────────────────────
    if ctx.seo_metadata:
        meta_path = export_dir / "seo_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(ctx.seo_metadata, f, indent=2, ensure_ascii=False, default=str)
        saved["seo_metadata"] = str(meta_path)

    # ── Save script blueprint ─────────────────────────────────────
    if ctx.script_blueprint:
        bp_path = export_dir / "script_blueprint.json"
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(ctx.script_blueprint, f, indent=2, ensure_ascii=False, default=str)
        saved["script_blueprint"] = str(bp_path)

    # ── Write recovery manifest ───────────────────────────────────
    manifest = {
        "run_id":         ctx.run_id,
        "exported_at":    datetime.now(timezone.utc).isoformat(),
        "upload_status":  ctx.upload_status,
        "reason":         "All YouTube credential packs failed or upload error.",
        "saved_files":    saved,
        "recovery_instructions": (
            "To manually upload: use long_video.mp4 + thumbnail.jpg + seo_metadata.json. "
            "Title and description are in seo_metadata.json. "
            "After successful manual upload, add the video_id to publication_log.json."
        ),
        "story": {
            "title":   ctx.selected_story.title   if ctx.selected_story else None,
            "pillar":  ctx.selected_story.pillar  if ctx.selected_story else None,
            "country": ctx.selected_story.country if ctx.selected_story else None,
        },
        "seo_title":        (ctx.seo_metadata or {}).get("title"),
        "voice_gender":     ctx.voice_gender,
        "thumbnail_template": ctx.thumbnail_template_id,
        "stages_completed": ctx.stages_completed,
        "yt_packs_tried":   "all active packs exhausted",
    }

    manifest_path = export_dir / "EMERGENCY_MANIFEST.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

    log.warning(f"Emergency manifest written: {manifest_path}")

    # ── Append failure record to publication log ──────────────────
    log_entry = {
        "run_id":              ctx.run_id,
        "youtube_video_id":   None,
        "youtube_short_id":   None,
        "title":              (ctx.seo_metadata or {}).get("title", ""),
        "pillar":             ctx.selected_story.pillar  if ctx.selected_story else "",
        "country":            ctx.selected_story.country if ctx.selected_story else "",
        "voice_gender":       ctx.voice_gender,
        "thumbnail_template_id": ctx.thumbnail_template_id,
        "formula_idx":        str((ctx.seo_metadata or {}).get("formula_idx", "0")),
        "yt_pack_used":       0,
        "upload_status":      "emergency_exported",
        "emergency_export_dir": str(export_dir),
        "analytics_collected": False,
    }
    try:
        append_publication_log(log_entry)
    except Exception as exc:
        log.warning(f"Could not write publication log during emergency export: {exc}")

    ctx.mark_stage("emergency_export")
    log.warning(
        f"Emergency export complete. {sum(1 for v in saved.values() if v)} files saved → {export_dir}"
    )
    return ctx

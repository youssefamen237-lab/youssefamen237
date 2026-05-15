"""
engines/video_renderer.py
Karma Vault Stories — FFmpeg Long-Form Video Renderer
GHA-Safe Chunked Rendering Architecture:
  Phase 1 — Render each scene_asset → individual .mp4 chunk (sequential, low memory)
  Phase 2 — Batch-concat chunks (15 per batch) → batch_N.mp4 via copy demuxer
  Phase 3 — Final concat of batch files → video_silent.mp4
  Phase 4 — Single combined FFmpeg pass: audio overlay + drawtext overlays → long_video.mp4
  Phase 5 — Cleanup all intermediate files to recover disk space

Memory ceiling: each FFmpeg process handles ≤6 seconds of video at 1920×1080.
Peak RAM per process: ~900MB (well within 7GB GHA limit).
Total render time estimate: 5–8 minutes for 98 scenes on 2-core GHA runner.
"""

import os
import re
import math
import time
import subprocess
import random
from pathlib import Path
from typing import Optional

from config.settings import (
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    VIDEO_BITRATE, AUDIO_BITRATE, AUDIO_SAMPLE_RATE,
    FFMPEG_THREADS, FFMPEG_PRESET, FFMPEG_CRF,
    FONTS_DIR, LONG_VIDEO_MAX_MINUTES,
)
from config.constants import (
    VISUAL_COLORS, AssetCategory,
    ContentPillar,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import video_path, audio_path, ensure_run_workspace

log = get_logger(__name__)

_BS       = chr(92)          # single backslash — used in FFmpeg filter escaping
_BATCH_SZ = 15               # scenes per concat batch (memory-safe on GHA)
_FFMPEG_TIMEOUT = 120        # seconds per chunk FFmpeg call
_FINAL_TIMEOUT  = 600        # seconds for final combined pass

# Pre-scale dimensions (25% larger than output to give zoompan/crop room)
_SRC_W = int(VIDEO_WIDTH  * 1.25)   # 2400
_SRC_H = int(VIDEO_HEIGHT * 1.25)   # 1350

# Drawtext font — always present on Ubuntu GHA runners
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
]


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_video_renderer(ctx: DailyRunContext) -> DailyRunContext:
    """
    Renders the full long-form video from scene_assets + mixed audio.
    Sets ctx.long_video_path on success.
    """
    if not ctx.scene_assets:
        log.error("No scene assets — cannot render video.")
        return ctx

    log.info(f"Video renderer starting. Scenes={len(ctx.scene_assets)}, "
             f"Audio={Path(ctx.narration_audio_path).name if ctx.narration_audio_path else 'NONE'}")

    ensure_run_workspace(ctx.run_id)

    # ── Phase 1: Render scene chunks ─────────────────────────────
    log.info(f"Phase 1: Rendering {len(ctx.scene_assets)} scene chunks...")
    chunk_paths = _render_all_chunks(ctx.scene_assets, ctx.run_id)
    log.info(f"Rendered {len(chunk_paths)}/{len(ctx.scene_assets)} chunks successfully.")

    if not chunk_paths:
        log.error("Zero chunks rendered — aborting.")
        return ctx

    # ── Phase 2+3: Batch concat → silent video ───────────────────
    log.info("Phase 2-3: Batch-concating chunks...")
    silent_path = video_path(ctx.run_id, "video_silent.mp4")
    ok = _batch_concat_chunks(chunk_paths, silent_path, ctx.run_id)
    if not ok or not silent_path.exists():
        log.error("Chunk concat failed — aborting.")
        return ctx
    log.info(f"Silent video: {silent_path.stat().st_size // (1024*1024)}MB")

    # Cleanup chunks to recover disk space before heavy final pass
    _cleanup_files(chunk_paths)

    # ── Phase 4: Audio + text overlay in one pass ─────────────────
    log.info("Phase 4: Audio overlay + text burn-in...")
    final_path = video_path(ctx.run_id, "long_video.mp4")
    audio_src  = ctx.narration_audio_path

    drawtext_chain = _build_drawtext_chain(
        ctx.script_blueprint or {},
        ctx.scene_assets,
        _find_font(),
    )

    ok = _apply_audio_and_text(
        silent_path, audio_src, drawtext_chain, final_path, ctx.run_id
    )

    if ok and final_path.exists() and final_path.stat().st_size > 100_000:
        ctx.long_video_path = str(final_path)
        size_mb = final_path.stat().st_size // (1024 * 1024)
        log.info(f"Long video rendered: {final_path.name} ({size_mb}MB)")
        # Only delete silent_path after confirmed good final output
        silent_path.unlink(missing_ok=True)
    else:
        # Keep silent_path intact — do NOT delete it, it IS the fallback
        log.warning("Final pass failed — keeping silent video as fallback.")
        ctx.long_video_path = str(silent_path)
    ctx.mark_stage("video_renderer")
    return ctx


# ─────────────────────────────────────────────
# PHASE 1: SCENE CHUNK RENDERING
# ─────────────────────────────────────────────

def _render_all_chunks(
    scene_assets: list[dict],
    run_id:       str,
) -> list[Path]:
    """
    Renders each scene_asset to an individual MP4 chunk sequentially.
    Sequential (not parallel) to stay within GHA 7GB RAM ceiling.
    Returns list of successfully rendered chunk paths.
    """
    chunks: list[Path] = []
    total  = len(scene_assets)

    for i, scene in enumerate(scene_assets):
        chunk_out = video_path(run_id, f"chunk_{i:04d}.mp4")
        ok = _render_single_chunk(scene, chunk_out)
        if ok:
            chunks.append(chunk_out)
        else:
            log.warning(f"Chunk {i:04d} ({scene.get('part_id','?')}) failed — "
                        f"inserting black placeholder.")
            dur = scene.get("duration_sec", 3.5)
            _render_black_placeholder(chunk_out, dur)
            if chunk_out.exists():
                chunks.append(chunk_out)

        if (i + 1) % 10 == 0:
            log.info(f"  Progress: {i+1}/{total} chunks")

    return chunks


def _render_single_chunk(scene: dict, out_path: Path) -> bool:
    """
    Renders one scene_asset to a short MP4 clip.
    Applies appropriate motion filter based on asset type and motion_type.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path   = scene.get("asset_path", "")
    asset_type   = scene.get("asset_type", "stock_photo")
    motion_type  = scene.get("motion_type", "slow_zoom_in")
    duration_sec = float(scene.get("duration_sec", 3.5))
    duration_sec = max(1.5, min(duration_sec, 8.0))

    # Validate source image exists
    if not asset_path or not Path(asset_path).exists():
        log.warning(f"Scene asset missing: {asset_path}")
        return False

    # Generated cards use static motion (they're full-frame text/graphics)
    card_types = {
        AssetCategory.EVIDENCE_CARD.value,
        AssetCategory.LOCATION_DATE_CARD.value,
        "shock_overlay",
        "cctv_frame",
        "cctv_style",
        AssetCategory.CCTV_STYLE.value,
    }
    if asset_type in card_types:
        motion_type = "static"

    vf = _build_motion_filter(motion_type, duration_sec)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-t",    str(round(duration_sec, 3)),
        "-i",    asset_path,
        "-vf",   vf,
        "-c:v",  "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf",  str(FFMPEG_CRF),
        "-r",    str(VIDEO_FPS),
        "-t",    str(round(duration_sec, 3)),
        "-threads", str(FFMPEG_THREADS),
        "-an",                  # no audio in chunks
        str(out_path),
    ]

    ok, err = _run_ffmpeg(cmd, f"chunk {out_path.stem}", _FFMPEG_TIMEOUT)
    if not ok:
        log.warning(f"Chunk render failed ({out_path.stem}): {err[-120:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 5000


def _render_black_placeholder(out_path: Path, duration_sec: float) -> None:
    """Generates a black silent MP4 as a placeholder for a failed chunk."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(1.5, round(duration_sec, 2))
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}",
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-an", str(out_path),
    ]
    _run_ffmpeg(cmd, "black_placeholder", 30)


# ─────────────────────────────────────────────
# PHASE 2+3: BATCH CONCAT
# ─────────────────────────────────────────────

def _batch_concat_chunks(
    chunk_paths: list[Path],
    final_out:   Path,
    run_id:      str,
) -> bool:
    """
    Groups chunks into batches of _BATCH_SZ, concats each batch,
    then concats the batch files into the final silent video.
    All concat operations use -c copy (no re-encode).
    """
    final_out.parent.mkdir(parents=True, exist_ok=True)

    # Single batch: just concat directly
    if len(chunk_paths) <= _BATCH_SZ:
        return _concat_with_demuxer(chunk_paths, final_out, run_id, "concat_all")

    # Multi-batch approach
    batches     = [chunk_paths[i:i+_BATCH_SZ] for i in range(0, len(chunk_paths), _BATCH_SZ)]
    batch_files: list[Path] = []

    for b_idx, batch in enumerate(batches):
        batch_out = video_path(run_id, f"batch_{b_idx:03d}.mp4")
        ok = _concat_with_demuxer(batch, batch_out, run_id, f"batch_{b_idx}")
        if ok and batch_out.exists():
            batch_files.append(batch_out)
        else:
            log.warning(f"Batch {b_idx} concat failed — skipping.")

    if not batch_files:
        return False

    # Final concat of batch files
    ok = _concat_with_demuxer(batch_files, final_out, run_id, "final_concat")
    _cleanup_files(batch_files)
    return ok


def _concat_with_demuxer(
    input_paths: list[Path],
    out_path:    Path,
    run_id:      str,
    label:       str,
) -> bool:
    """Creates a concat list file and runs ffmpeg concat demuxer (copy mode)."""
    list_path = video_path(run_id, f"concat_{label}.txt")
    list_path.parent.mkdir(parents=True, exist_ok=True)

    with open(list_path, "w", encoding="utf-8") as f:
        for p in input_paths:
            if p.exists():
                # Use absolute path, escape single quotes
                escaped = str(p.resolve()).replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f",    "concat",
        "-safe", "0",
        "-i",    str(list_path),
        "-c",    "copy",
        str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, f"concat_{label}", 300)
    list_path.unlink(missing_ok=True)

    if not ok:
        log.warning(f"Concat {label} failed: {err[-150:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 10_000


# ─────────────────────────────────────────────
# PHASE 4: AUDIO + TEXT OVERLAY
# ─────────────────────────────────────────────

def _apply_audio_and_text(
    video_path_in:   Path,
    audio_path_in:   Optional[str],
    drawtext_chain:  str,
    out_path:        Path,
    run_id:          str = "",
) -> bool:
    """
    TWO sequential FFmpeg passes — avoids filter_complex quoting entirely.

    Pass A — Audio overlay (-c:v copy, no video re-encode, fast):
      ffmpeg -i video_silent.mp4 -i audio.mp3 -c:v copy -c:a aac → _pass_audio_temp.mp4

    Pass B — Text overlays (-vf, video re-encodes once for burn-in):
      ffmpeg -i _pass_audio_temp.mp4 -vf "drawtext=..." -c:a copy → long_video.mp4

    -vf quoting is far simpler than filter_complex: no [pad] labels,
    no apostrophe/enable/single-quote interaction edge cases.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = bool(audio_path_in and Path(audio_path_in).exists())
    has_text  = bool(drawtext_chain)

    # Intermediate file for between passes
    audio_temp = (out_path.parent / f"_pass_audio_temp_{out_path.stem}.mp4"
                  if run_id == "" else
                  video_path(run_id, "_pass_audio_temp.mp4"))

    # ── Pass A: Audio overlay ──────────────────────────────────────
    if has_audio:
        pass_a_ok = _pass_audio_overlay(video_path_in, audio_path_in, audio_temp)
        if not pass_a_ok:
            log.warning("Audio overlay pass failed — continuing without audio.")
            audio_temp = video_path_in   # fall through to text pass on original
        source_for_text = audio_temp
    else:
        source_for_text = video_path_in

    # ── Pass B: Text overlays ──────────────────────────────────────
    if has_text:
        pass_b_ok = _pass_text_overlays(source_for_text, drawtext_chain, out_path)
        if has_audio and source_for_text != video_path_in:
            Path(source_for_text).unlink(missing_ok=True)
        if not pass_b_ok:
            log.error("Text overlay pass failed.")
            return False
        return True
    else:
        # No text — audio temp IS the final output
        if has_audio and source_for_text != video_path_in:
            Path(source_for_text).rename(out_path)
        else:
            import shutil
            shutil.copy2(str(video_path_in), str(out_path))
        return True


def _pass_audio_overlay(
    video_in:  Path,
    audio_in:  str,
    out_path:  Path,
) -> bool:
    """Pass A: audio overlay, video byte-copied (-c:v copy)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i",    str(video_in),
        "-i",    str(audio_in),
        "-map",  "0:v:0",
        "-map",  "1:a:0",
        "-c:v",  "copy",
        "-c:a",  "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-shortest",
        str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, "audio_overlay_pass", 300)
    if not ok:
        log.warning(f"Audio overlay pass error: {err[-150:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 10_000


def _pass_text_overlays(
    video_in:       Path,
    drawtext_chain: str,
    out_path:       Path,
) -> bool:
    """Pass B: drawtext burn-in via -vf (NOT filter_complex). Audio copied."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i",    str(video_in),
        "-vf",   drawtext_chain,
        "-c:v",  "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
        "-c:a",  "copy",
        "-threads", str(FFMPEG_THREADS),
        str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, "text_overlay_pass", _FINAL_TIMEOUT)
    if not ok:
        log.error(f"Text overlay pass error: {err[-300:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 100_000


# ─────────────────────────────────────────────
# MOTION FILTER BUILDER
# ─────────────────────────────────────────────

def _build_motion_filter(motion_type: str, duration_sec: float) -> str:
    """
    Returns a validated FFmpeg -vf filter string for the given motion type.
    All expressions use chr(92) for backslash to avoid Python SyntaxWarnings.
    """
    bs   = _BS
    d    = int(duration_sec * VIDEO_FPS)
    d    = max(d, VIDEO_FPS)           # minimum 1 second worth of frames
    zi   = round(0.24 / max(d, 1), 7)  # zoom increment for consistent 0→1.25 over duration
    dur  = round(duration_sec, 3)

    # Pre-scale dimensions (25% oversized for zoom/pan room)
    sw, sh = _SRC_W, _SRC_H
    # Center offsets for pan/drift (center crop within oversized frame)
    cx   = (sw - VIDEO_WIDTH)  // 2    # 240
    cy   = (sh - VIDEO_HEIGHT) // 2    # 135
    px   = int((sw - VIDEO_WIDTH)  * 0.85)   # ~204 — pan travel distance
    py   = int((sh - VIDEO_HEIGHT) * 0.85)   # ~114

    filters = {
        "slow_zoom_in": (
            f"scale={sw}:{sh}:flags=lanczos,"
            f"zoompan=z=min(zoom+{zi}{bs},1.25):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "slow_zoom_out": (
            f"scale={sw}:{sh}:flags=lanczos,"
            f"zoompan=z=if(lte(zoom{bs},1.0001){bs},1.25{bs},max(1.0001{bs},zoom-{zi})):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "pan_right": (
            f"scale={sw}:{sh},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x=min({px}{bs},{px}*t/{dur}):"
            f"y={cy},"
            f"format=yuv420p"
        ),
        "pan_left": (
            f"scale={sw}:{sh},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x=max(0{bs},{px}*(1-t/{dur})):"
            f"y={cy},"
            f"format=yuv420p"
        ),
        "drift_up": (
            f"scale={sw}:{sh},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x={cx}:"
            f"y=max(0{bs},{py}*(1-t/{dur})),"
            f"format=yuv420p"
        ),
        "drift_down": (
            f"scale={sw}:{sh},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x={cx}:"
            f"y=min({py}{bs},{py}*t/{dur}),"
            f"format=yuv420p"
        ),
        "shake": (
            f"scale={sw}:{sh},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x={cx}+10*sin(t*8):"
            f"y={cy}+6*cos(t*10),"
            f"format=yuv420p"
        ),
        "static": (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"format=yuv420p"
        ),
    }
    return filters.get(motion_type, filters["slow_zoom_in"])


# ─────────────────────────────────────────────
# DRAWTEXT OVERLAY CHAIN
# ─────────────────────────────────────────────

def _build_drawtext_chain(
    blueprint:    dict,
    scene_assets: list[dict],
    font_path:    str,
) -> str:
    """
    Builds the drawtext -vf filter chain for all timed text overlays.
    ALL text values passed through _escape_drawtext() — no raw apostrophes.
    enable= uses NO surrounding single quotes — clean for -vf context.
    """
    parts   = blueprint.get("parts", [])
    filters: list[str] = []
    fp      = font_path.replace(":", "\\:")
    bs      = _BS

    # ── 1. +18 badge ─────────────────────────────────────────────
    badge_text = _escape_drawtext("+18")
    filters.append(
        f"drawtext=text='{badge_text}':"
        f"fontfile={fp}:"
        f"fontsize=46:fontcolor=white:"
        f"x=30:y=25:"
        f"box=1:boxcolor=0x8B0000@0.92:boxborderw=14:"
        f"enable=between(t{bs},0{bs},8.0)"
    )

    # ── 2. Intro story label ──────────────────────────────────────
    story_label = blueprint.get("story_label", "")
    if story_label:
        safe_label = _escape_drawtext(story_label.upper()[:40])
        filters.append(
            f"drawtext=text='{safe_label}':"
            f"fontfile={fp}:"
            f"fontsize=68:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-165:"
            f"box=1:boxcolor=0x8B0000@0.88:boxborderw=18:"
            f"enable=between(t{bs},0.3{bs},3.5)"
        )

    # ── 3. CTA overlay ───────────────────────────────────────────
    cta_scene = next((s for s in scene_assets if s.get("cta_overlay")), None)
    if cta_scene:
        cta_start = float(cta_scene.get("start_time_sec", 120.0))
        cta_end   = cta_start + float(cta_scene.get("duration_sec", 3.5))
        cta_text  = _escape_drawtext("SUBSCRIBE FOR DAILY DARK FILES")
        filters.append(
            f"drawtext=text='{cta_text}':"
            f"fontfile={fp}:"
            f"fontsize=52:fontcolor=0xFFD700:"
            f"x=(w-text_w)/2:y=h-110:"
            f"box=1:boxcolor=black@0.75:boxborderw=12:"
            f"enable=between(t{bs},{cta_start:.2f}{bs},{cta_end:.2f})"
        )

    # ── 4. Outro text ─────────────────────────────────────────────
    total_dur = blueprint.get("total_narration_sec")
    if not total_dur and scene_assets:
        last = scene_assets[-1]
        total_dur = last.get("start_time_sec", 0) + last.get("duration_sec", 0)
    if total_dur and float(total_dur) > 20:
        outro_start = max(0.0, float(total_dur) - 18.0)
        # FIX: _escape_drawtext converts apostrophe → U+2019 (right single quote)
        # so TOMORROW'S does not break the surrounding text='...' delimiter
        outro_text  = _escape_drawtext("TOMORROW'S FILE IS DARKER")
        filters.append(
            f"drawtext=text='{outro_text}':"
            f"fontfile={fp}:"
            f"fontsize=82:fontcolor=white:"
            f"borderw=5:bordercolor=0x8B0000:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable=between(t{bs},{outro_start:.2f}{bs},32767)"
        )

    return ",".join(filters) if filters else ""


def _escape_drawtext(text: str) -> str:
    """Escapes special characters for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\u2019")   # replace apostrophe with right-single-quote
    text = text.replace(":",  "\\:")
    return text


def _find_font() -> str:
    """Returns the best available bold font path on the GHA runner."""
    # Check FONTS_DIR first for downloaded fonts
    for f in FONTS_DIR.glob("*.ttf"):
        return str(f)
    for fp in _FONT_PATHS:
        if Path(fp).exists():
            return fp
    return _FONT_PATHS[0]   # fallback even if not found — FFmpeg will error gracefully


# ─────────────────────────────────────────────
# FFmpeg RUNNER
# ─────────────────────────────────────────────

def _run_ffmpeg(
    args:        list[str],
    description: str,
    timeout_sec: int = 120,
) -> tuple[bool, str]:
    """
    Runs an FFmpeg command via subprocess.
    Returns (success, stderr_tail).
    Never raises — all failures are logged and returned as (False, error_msg).
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if result.returncode != 0:
            return False, result.stderr[-400:]
        return True, ""
    except subprocess.TimeoutExpired:
        msg = f"FFmpeg timed out after {timeout_sec}s for: {description}"
        log.warning(msg)
        return False, msg
    except Exception as exc:
        log.warning(f"FFmpeg subprocess error ({description}): {exc}")
        return False, str(exc)


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _cleanup_files(paths: list[Path]) -> None:
    """Deletes a list of temp files to recover GHA disk space."""
    deleted = 0
    for p in paths:
        try:
            if p.exists():
                p.unlink()
                deleted += 1
        except OSError:
            pass
    if deleted:
        log.debug(f"Cleaned up {deleted} temp files.")

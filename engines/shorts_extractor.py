"""
engines/shorts_extractor.py
Karma Vault Stories — YouTube Shorts Extraction Engine
Renders the 35-50 second vertical (1080×1920) Short from the escalation/climax
scene pool. Fast-cut pacing (1.5-2.5s), aggressive text overlays, hook caption,
"FULL STORY ON CHANNEL" closer. Audio from blueprint short_clip data.
Uses the same validated crop+scale approach as the long-form renderer.
"""

import random
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import (
    SHORT_WIDTH, SHORT_HEIGHT, VIDEO_FPS,
    AUDIO_BITRATE, AUDIO_SAMPLE_RATE,
    FFMPEG_THREADS, FFMPEG_PRESET, FFMPEG_CRF,
    FONTS_DIR,
)
from config.constants import AssetCategory
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import video_path, audio_path, ensure_run_workspace
from engines.video_renderer import (
    _run_ffmpeg, _concat_with_demuxer, _cleanup_files,
    _find_font, _escape_drawtext, _FFMPEG_TIMEOUT, _BS,
)

log = get_logger(__name__)

# Short video target parameters
_SHORT_MIN_SEC  = 35.0
_SHORT_MAX_SEC  = 50.0
_SHORT_CUT_MIN  = 1.4   # faster cuts than long video
_SHORT_CUT_MAX  = 2.6
_SHORT_BATCH_SZ = 25    # all short clips fit in one batch

# Vertical pre-scale (25% oversized for motion room)
_SRC_W_V = int(SHORT_WIDTH  * 1.25)   # 1350
_SRC_H_V = int(SHORT_HEIGHT * 1.25)   # 2400

# Center crop offsets within oversized vertical frame
_CX_V = (_SRC_W_V - SHORT_WIDTH)  // 2   # 135
_CY_V = (_SRC_H_V - SHORT_HEIGHT) // 2   # 240


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_shorts_extractor(ctx: DailyRunContext) -> DailyRunContext:
    """
    Renders the YouTube Short and sets ctx.short_video_path.
    Draws visuals from the escalation/climax scene pool.
    """
    if not ctx.scene_assets:
        log.error("No scene assets — cannot render short.")
        return ctx

    log.info("Shorts extractor starting...")
    ensure_run_workspace(ctx.run_id)
    blueprint = ctx.script_blueprint or {}

    # ── Step 1: Select visual pool for the short ─────────────────
    short_scenes = _select_short_scene_pool(ctx)
    log.info(f"Short visual pool: {len(short_scenes)} scenes selected")

    if not short_scenes:
        log.error("No suitable scenes for short — aborting.")
        return ctx

    # ── Step 2: Render vertical scene clips ──────────────────────
    log.info("Rendering short scene clips (1080×1920)...")
    clip_paths = _render_short_clips(short_scenes, ctx.run_id)
    log.info(f"Short clips rendered: {len(clip_paths)}")

    if not clip_paths:
        log.error("Zero short clips rendered — aborting.")
        return ctx

    # ── Step 3: Concat clips → silent short video ────────────────
    silent_short = video_path(ctx.run_id, "short_silent.mp4")
    ok = _concat_with_demuxer(clip_paths, silent_short, ctx.run_id, "short_concat")
    _cleanup_files(clip_paths)

    if not ok or not silent_short.exists():
        log.error("Short concat failed.")
        return ctx
    log.info(f"Short silent video: {silent_short.stat().st_size // 1024}KB")

    # ── Step 4: Audio + text overlay ─────────────────────────────
    short_audio = _get_short_audio_path(blueprint, ctx.run_id)
    final_short = video_path(ctx.run_id, "short_video.mp4")

    hook_text   = (blueprint.get("short_clip") or {}).get("hook_caption", "WAIT FOR IT")
    ok = _apply_short_audio_and_text(
        silent_short, short_audio, hook_text, final_short
    )
    silent_short.unlink(missing_ok=True)

    if ok and final_short.exists() and final_short.stat().st_size > 50_000:
        ctx.short_video_path = str(final_short)
        log.info(f"Short video: {final_short.name} "
                 f"({final_short.stat().st_size // 1024}KB)")
    else:
        log.warning("Short render failed — short_video_path not set.")

    ctx.mark_stage("shorts_extractor")
    return ctx


# ─────────────────────────────────────────────
# SCENE POOL SELECTION
# ─────────────────────────────────────────────

def _select_short_scene_pool(ctx: DailyRunContext) -> list[dict]:
    """
    Selects the best 15-25 scenes for the short, targeting _SHORT_MAX_SEC total.
    Priority: escalation/climax stock photos → hook → any stock photo.
    Avoids evidence cards and shock overlays (short uses text overlays instead).
    """
    scene_assets = ctx.scene_assets or []

    stock_types = {
        "stock_photo",
        "ai_still",
        AssetCategory.STOCK_PHOTO.value,
        AssetCategory.AI_DRAMATIC_STILL.value,
    }

    def is_stock(s: dict) -> bool:
        return s.get("asset_type", "") in stock_types

    # Tier 1: horror-graded escalation/climax scenes
    tier1 = [s for s in scene_assets
             if is_stock(s) and s.get("horror_grading")
             and s.get("part_id") in ("escalation", "climax")]

    # Tier 2: any escalation/climax stock
    tier2 = [s for s in scene_assets
             if is_stock(s) and s.get("part_id") in ("escalation", "climax")
             and s not in tier1]

    # Tier 3: hook and first_sign (good for opening)
    tier3 = [s for s in scene_assets
             if is_stock(s) and s.get("part_id") in ("hook", "first_sign")]

    # Tier 4: any remaining stock
    tier4 = [s for s in scene_assets
             if is_stock(s) and s not in tier1 + tier2 + tier3]

    # Build pool: start with tier1+2 (most dramatic), prepend some tier3 for opening
    pool = (tier3[:3] + tier1[:8] + tier2[:6] + tier4[:4])

    if not pool:
        pool = [s for s in scene_assets if Path(s.get("asset_path", "")).exists()]

    # Assign fast short-specific durations and deduplicate by asset_path
    seen_paths: set[str] = set()
    result: list[dict] = []
    total_sec = 0.0

    for scene in pool:
        ap = scene.get("asset_path", "")
        if not ap or not Path(ap).exists():
            continue
        if ap in seen_paths:
            continue
        seen_paths.add(ap)

        dur = round(random.uniform(_SHORT_CUT_MIN, _SHORT_CUT_MAX), 2)
        if total_sec + dur > _SHORT_MAX_SEC + 2.0:
            break

        short_scene = dict(scene)  # copy so we don't mutate original
        short_scene["duration_sec"]  = dur
        short_scene["motion_type"]   = _short_motion_for_tier(len(result))
        result.append(short_scene)
        total_sec += dur

    # Ensure minimum duration by repeating scenes if necessary
    while total_sec < _SHORT_MIN_SEC and result:
        extra = dict(result[len(result) % len(result)])
        extra["duration_sec"] = round(random.uniform(_SHORT_CUT_MIN, _SHORT_CUT_MAX), 2)
        extra["motion_type"]  = _short_motion_for_tier(len(result))
        result.append(extra)
        total_sec += extra["duration_sec"]

    return result[:30]   # safety cap


def _short_motion_for_tier(idx: int) -> str:
    """Assigns motion types for short clips — faster and more aggressive than long form."""
    options = [
        "slow_zoom_in", "pan_right", "drift_up", "pan_left",
        "slow_zoom_out", "drift_down", "slow_zoom_in", "shake",
    ]
    return options[idx % len(options)]


# ─────────────────────────────────────────────
# SHORT CLIP RENDERING (VERTICAL 1080×1920)
# ─────────────────────────────────────────────

def _render_short_clips(
    scenes: list[dict],
    run_id: str,
) -> list[Path]:
    """Renders each selected scene to a 1080×1920 vertical MP4 clip."""
    clips: list[Path] = []
    for i, scene in enumerate(scenes):
        out  = video_path(run_id, f"short_clip_{i:04d}.mp4")
        ok   = _render_short_scene(scene, out)
        if ok:
            clips.append(out)
        else:
            log.warning(f"Short clip {i} failed — inserting black.")
            _render_short_black(out, scene.get("duration_sec", 2.0))
            if out.exists():
                clips.append(out)
    return clips


def _render_short_scene(scene: dict, out_path: Path) -> bool:
    """
    Renders one scene to 1080×1920 vertical MP4.
    Landscape source images are center-cropped to portrait aspect ratio.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ap  = scene.get("asset_path", "")
    if not ap or not Path(ap).exists():
        return False

    dur = round(float(scene.get("duration_sec", 2.0)), 3)
    dur = max(1.4, min(dur, 4.0))
    vf  = _build_short_motion_filter(
        scene.get("motion_type", "slow_zoom_in"), dur
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-t",    str(dur),
        "-i",    ap,
        "-vf",   vf,
        "-c:v",  "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf",  str(FFMPEG_CRF),
        "-r",    str(VIDEO_FPS),
        "-t",    str(dur),
        "-threads", str(FFMPEG_THREADS),
        "-an",
        str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, f"short_clip_{out_path.stem}", _FFMPEG_TIMEOUT)
    if not ok:
        log.warning(f"Short clip render failed: {err[-100:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 5000


def _build_short_motion_filter(motion_type: str, duration_sec: float) -> str:
    """
    Returns vertical 1080×1920 motion filter.
    Source landscape (1920×1080) → center-crop to portrait → oversized → motion.
    """
    bs  = _BS
    dur = round(duration_sec, 3)
    d   = int(duration_sec * VIDEO_FPS)
    d   = max(d, VIDEO_FPS)
    zi  = round(0.24 / max(d, 1), 7)

    sw, sh = _SRC_W_V, _SRC_H_V   # 1350×2400
    cx, cy = _CX_V, _CY_V         # 135, 240
    px  = int((sw - SHORT_WIDTH)  * 0.85)   # ~114
    py  = int((sh - SHORT_HEIGHT) * 0.85)   # ~204

    # Step 1 of all filters: convert landscape → portrait
    # scale height to match short height, then crop width
    # 1920×1080 → scale to ?×2400: ratio = 2400/1080 = 2.22
    # new_w = 1920 * 2.22 ≈ 4267, then crop center 1080
    landscape_to_portrait = (
        f"scale=-1:{sh}:flags=lanczos,"
        f"crop={sw}:{sh}:(iw-{sw})/2:0"
    )

    filters = {
        "slow_zoom_in": (
            f"{landscape_to_portrait},"
            f"zoompan=z=min(zoom+{zi}{bs},1.25):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={SHORT_WIDTH}x{SHORT_HEIGHT}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "slow_zoom_out": (
            f"{landscape_to_portrait},"
            f"zoompan=z=if(lte(zoom{bs},1.0001){bs},1.25{bs},max(1.0001{bs},zoom-{zi})):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={SHORT_WIDTH}x{SHORT_HEIGHT}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "pan_right": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:"
            f"x=min({px}{bs},{px}*t/{dur}):y={cy},"
            f"format=yuv420p"
        ),
        "pan_left": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:"
            f"x=max(0{bs},{px}*(1-t/{dur})):y={cy},"
            f"format=yuv420p"
        ),
        "drift_up": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:"
            f"x={cx}:y=max(0{bs},{py}*(1-t/{dur})),"
            f"format=yuv420p"
        ),
        "drift_down": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:"
            f"x={cx}:y=min({py}{bs},{py}*t/{dur}),"
            f"format=yuv420p"
        ),
        "shake": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:"
            f"x={cx}+10*sin(t*9):y={cy}+6*cos(t*11),"
            f"format=yuv420p"
        ),
        "static": (
            f"{landscape_to_portrait},"
            f"crop={SHORT_WIDTH}:{SHORT_HEIGHT}:(iw-{SHORT_WIDTH})/2:(ih-{SHORT_HEIGHT})/2,"
            f"format=yuv420p"
        ),
    }
    return filters.get(motion_type, filters["slow_zoom_in"])


def _render_short_black(out_path: Path, duration_sec: float) -> None:
    """Black placeholder for a failed short clip."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(1.4, round(duration_sec, 2))
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={SHORT_WIDTH}x{SHORT_HEIGHT}:r={VIDEO_FPS}",
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-an", str(out_path),
    ]
    _run_ffmpeg(cmd, "short_black_placeholder", 20)


# ─────────────────────────────────────────────
# SHORT AUDIO + TEXT OVERLAY
# ─────────────────────────────────────────────

def _apply_short_audio_and_text(
    video_in:    Path,
    audio_in:    Optional[Path],
    hook_text:   str,
    out_path:    Path,
) -> bool:
    """
    Combines short audio + burns in three text overlays:
      1. Hook caption (first 1.5s) — giant, aggressive
      2. Implied shock text (mid-video)
      3. "FULL STORY ON CHANNEL" (last 4s)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = audio_in and audio_in.exists()
    font_path = _find_font().replace(":", "\\:")

    hook_safe   = _escape_drawtext(hook_text.upper()[:20])
    closer_text = "FULL STORY ON CHANNEL"

    # Build drawtext filters for the short
    text_chain = ",".join([
        # Hook caption — massive, immediate
        (f"drawtext=text='{hook_safe}':"
         f"fontfile={font_path}:"
         f"fontsize=105:"
         f"fontcolor=white:"
         f"borderw=6:bordercolor=0xCC0000:"
         f"x=(w-text_w)/2:y=(h-text_h)/2-60:"
         f"enable='between(t\\,0\\,1.8)'"),
        # Closing CTA
        (f"drawtext=text='{closer_text}':"
         f"fontfile={font_path}:"
         f"fontsize=65:"
         f"fontcolor=white:"
         f"box=1:boxcolor=0x8B0000@0.90:boxborderw=16:"
         f"x=(w-text_w)/2:y=h-200:"
         f"enable='between(t\\,32\\,32767)'"),
    ])

    if has_audio:
        cmd = [
            "ffmpeg", "-y",
            "-i",   str(video_in),
            "-i",   str(audio_in),
            "-filter_complex",
            f"[0:v]{text_chain}[vout]",
            "-map", "[vout]",
            "-map", "1:a:0",
            "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
            "-threads", str(FFMPEG_THREADS),
            "-shortest",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i",   str(video_in),
            "-vf",  text_chain,
            "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
            "-threads", str(FFMPEG_THREADS),
            "-an",
            str(out_path),
        ]

    ok, err = _run_ffmpeg(cmd, "short_audio_text_pass", 180)
    if not ok:
        log.error(f"Short audio+text pass failed: {err[-200:]}")
    return ok


# ─────────────────────────────────────────────
# AUDIO PATH RESOLUTION
# ─────────────────────────────────────────────

def _get_short_audio_path(blueprint: dict, run_id: str) -> Optional[Path]:
    """
    Returns the short clip audio path.
    Priority: blueprint short_clip.mixed_audio_path → short_clip.audio_path
              → narration_short.mp3 → None
    """
    short_clip = blueprint.get("short_clip") or {}

    for key in ("mixed_audio_path", "audio_path"):
        p = short_clip.get(key, "")
        if p and Path(p).exists():
            return Path(p)

    # Check workspace for narration_short.mp3
    fallback = audio_path(run_id, "narration_short.mp3")
    if fallback.exists():
        return fallback

    fallback2 = audio_path(run_id, "short_final_audio.mp3")
    if fallback2.exists():
        return fallback2

    log.warning("No short clip audio found — short will be silent.")
    return None

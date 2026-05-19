"""
engines/shorts_extractor.py
Karma Vault Stories — YouTube Shorts Extraction Engine
True 9:16 vertical: scale=iw*H/ih:H,crop=W:H:(iw-W)/2:0
Guaranteed fill with zero black bars from any landscape source.
"""

import random
import re
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

_SHORT_MIN_SEC  = 35.0
_SHORT_MAX_SEC  = 50.0
_SHORT_CUT_MIN  = 1.4
_SHORT_CUT_MAX  = 2.6

# Subtitle style for shorts (slightly larger than long-form)
_SHORT_SUBTITLE_STYLE = (
    "FontName=Liberation Sans Bold"
    ",FontSize=28"
    ",PrimaryColour=&H00FFFFFF"
    ",OutlineColour=&H00000000"
    ",BackColour=&H70000000"
    ",BorderStyle=3"
    ",Outline=2"
    ",Shadow=0"
    ",Alignment=2"
    ",MarginV=120"
)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_shorts_extractor(ctx: DailyRunContext) -> DailyRunContext:
    if not ctx.scene_assets:
        log.error("No scene assets — cannot render short.")
        return ctx

    log.info("Shorts extractor starting...")
    ensure_run_workspace(ctx.run_id)
    blueprint = ctx.script_blueprint or {}

    short_scenes = _select_short_scene_pool(ctx)
    log.info(f"Short visual pool: {len(short_scenes)} scenes")

    if not short_scenes:
        log.error("No suitable scenes for short — aborting.")
        return ctx

    log.info("Rendering short scene clips (true 1080x1920 vertical)...")
    clip_paths = _render_short_clips(short_scenes, ctx.run_id)
    log.info(f"Short clips rendered: {len(clip_paths)}")

    if not clip_paths:
        log.error("Zero short clips rendered — aborting.")
        return ctx

    silent_short = video_path(ctx.run_id, "short_silent.mp4")
    ok = _concat_with_demuxer(clip_paths, silent_short, ctx.run_id, "short_concat")
    _cleanup_files(clip_paths)

    if not ok or not silent_short.exists():
        log.error("Short concat failed.")
        return ctx

    short_audio = _get_short_audio_path(blueprint, ctx.run_id)
    final_short = video_path(ctx.run_id, "short_video.mp4")
    hook_text   = (blueprint.get("short_clip") or {}).get("hook_caption", "WAIT FOR IT")

    # Generate short SRT from short_clip narration if available
    srt_path = _generate_short_srt(blueprint, ctx.run_id)

    ok = _apply_short_audio_and_text(
        silent_short, short_audio, hook_text, srt_path, final_short
    )
    silent_short.unlink(missing_ok=True)

    if ok and final_short.exists() and final_short.stat().st_size > 50_000:
        ctx.short_video_path = str(final_short)
        log.info(f"Short video: {final_short.name} ({final_short.stat().st_size // 1024}KB)")
    else:
        log.warning("Short render failed — short_video_path not set.")

    ctx.mark_stage("shorts_extractor")
    return ctx


# ─────────────────────────────────────────────
# SCENE POOL SELECTION
# ─────────────────────────────────────────────

def _select_short_scene_pool(ctx: DailyRunContext) -> list[dict]:
    scene_assets = ctx.scene_assets or []
    stock_types  = {
        "stock_photo", "ai_still",
        AssetCategory.STOCK_PHOTO.value,
        AssetCategory.AI_DRAMATIC_STILL.value,
    }

    def is_stock(s: dict) -> bool:
        return s.get("asset_type", "") in stock_types

    tier1 = [s for s in scene_assets
             if is_stock(s) and s.get("horror_grading")
             and s.get("part_id") in ("escalation", "climax")]
    tier2 = [s for s in scene_assets
             if is_stock(s) and s.get("part_id") in ("escalation", "climax")
             and s not in tier1]
    tier3 = [s for s in scene_assets
             if is_stock(s) and s.get("part_id") in ("hook", "first_sign")]
    tier4 = [s for s in scene_assets
             if is_stock(s) and s not in tier1 + tier2 + tier3]

    pool = tier3[:3] + tier1[:8] + tier2[:6] + tier4[:4]
    if not pool:
        pool = [s for s in scene_assets if Path(s.get("asset_path", "")).exists()]

    seen_paths: set[str] = set()
    result: list[dict]   = []
    total_sec = 0.0

    for scene in pool:
        ap = scene.get("asset_path", "")
        if not ap or not Path(ap).exists() or ap in seen_paths:
            continue
        seen_paths.add(ap)
        dur = round(random.uniform(_SHORT_CUT_MIN, _SHORT_CUT_MAX), 2)
        if total_sec + dur > _SHORT_MAX_SEC + 2.0:
            break
        short_scene = dict(scene)
        short_scene["duration_sec"] = dur
        short_scene["motion_type"]  = _short_motion_for_idx(len(result))
        result.append(short_scene)
        total_sec += dur

    # Pad to minimum duration if needed
    while total_sec < _SHORT_MIN_SEC and result:
        extra = dict(result[len(result) % len(result)])
        extra["duration_sec"] = round(random.uniform(_SHORT_CUT_MIN, _SHORT_CUT_MAX), 2)
        extra["motion_type"]  = _short_motion_for_idx(len(result))
        result.append(extra)
        total_sec += extra["duration_sec"]

    return result[:30]


def _short_motion_for_idx(idx: int) -> str:
    options = [
        "slow_zoom_in", "pan_right", "drift_up", "pan_left",
        "slow_zoom_out", "drift_down", "slow_zoom_in", "shake",
    ]
    return options[idx % len(options)]


# ─────────────────────────────────────────────
# SHORT CLIP RENDERING — GUARANTEED TRUE 9:16
# ─────────────────────────────────────────────

def _render_short_clips(scenes: list[dict], run_id: str) -> list[Path]:
    clips: list[Path] = []
    for i, scene in enumerate(scenes):
        out = video_path(run_id, f"short_clip_{i:04d}.mp4")
        ok  = _render_short_scene(scene, out)
        if ok:
            clips.append(out)
        else:
            _render_short_black(out, scene.get("duration_sec", 2.0))
            if out.exists():
                clips.append(out)
    return clips


def _render_short_scene(scene: dict, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ap  = scene.get("asset_path", "")
    if not ap or not Path(ap).exists():
        return False

    dur = round(float(scene.get("duration_sec", 2.0)), 3)
    dur = max(1.4, min(dur, 4.0))
    vf  = _build_short_motion_filter(scene.get("motion_type", "slow_zoom_in"), dur)

    cmd = [
        "ffmpeg", "-y", "-loop", "1",
        "-t", str(dur), "-i", ap,
        "-vf", vf,
        "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
        "-r", str(VIDEO_FPS),
        "-t", str(dur),
        "-threads", str(FFMPEG_THREADS),
        "-an", str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, f"short_clip_{out_path.stem}", _FFMPEG_TIMEOUT)
    if not ok:
        log.warning(f"Short clip render failed: {err[-120:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 5000


def _build_short_motion_filter(motion_type: str, duration_sec: float) -> str:
    """
    Converts any source to guaranteed 1080x1920 (9:16) with NO black bars.

    Core transform (landscape 1920x1080 → portrait 1080x1920):
      scale=iw*1920/ih:1920   → scales height to 1920, width auto
                                  For 1920x1080: new_w = 1920*1920/1080 = 3413
      crop=1080:1920:(iw-1080)/2:0  → center-crop to exact 1080 wide

    This formula works for ANY landscape aspect ratio — 16:9, 4:3, 21:9.
    The result is mathematically guaranteed 1080x1920 with zero black bars.

    Motion: applied within a 12%-oversized portrait frame for zoom/pan room.
    """
    bs  = _BS
    dur = round(duration_sec, 3)
    d   = max(int(duration_sec * VIDEO_FPS), VIDEO_FPS)
    zi  = round(0.20 / max(d, 1), 7)

    W, H = SHORT_WIDTH, SHORT_HEIGHT   # 1080, 1920

    # Step 1: guaranteed landscape→portrait, fills frame completely
    to_portrait = (
        f"scale=iw*{H}/ih:{H}:flags=lanczos,"
        f"crop={W}:{H}:(iw-{W})/2:0"
    )

    # Step 2 (for motion): oversized portrait for zoom/pan room
    OW = int(W * 1.12)   # 1209
    OH = int(H * 1.12)   # 2150
    cx = (OW - W) // 2   # 64
    cy = (OH - H) // 2   # 115
    px = int((OW - W) * 0.80)
    py = int((OH - H) * 0.80)

    filters = {
        "slow_zoom_in": (
            f"{to_portrait},"
            f"scale={OW}:{OH}:flags=lanczos,"
            f"zoompan=z=min(zoom+{zi}{bs},1.12):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={W}x{H}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "slow_zoom_out": (
            f"{to_portrait},"
            f"scale={OW}:{OH}:flags=lanczos,"
            f"zoompan=z=if(lte(zoom{bs},1.0001){bs},1.12{bs},max(1.0001{bs},zoom-{zi})):"
            f"x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:"
            f"d={d}:s={W}x{H}:fps={VIDEO_FPS},"
            f"format=yuv420p"
        ),
        "pan_right": (
            f"{to_portrait},"
            f"scale={OW}:{OH},"
            f"crop={W}:{H}:x=min({px}{bs},{px}*t/{dur}):y={cy},"
            f"format=yuv420p"
        ),
        "pan_left": (
            f"{to_portrait},"
            f"scale={OW}:{OH},"
            f"crop={W}:{H}:x=max(0{bs},{px}*(1-t/{dur})):y={cy},"
            f"format=yuv420p"
        ),
        "drift_up": (
            f"{to_portrait},"
            f"scale={OW}:{OH},"
            f"crop={W}:{H}:x={cx}:y=max(0{bs},{py}*(1-t/{dur})),"
            f"format=yuv420p"
        ),
        "drift_down": (
            f"{to_portrait},"
            f"scale={OW}:{OH},"
            f"crop={W}:{H}:x={cx}:y=min({py}{bs},{py}*t/{dur}),"
            f"format=yuv420p"
        ),
        "shake": (
            f"{to_portrait},"
            f"scale={OW}:{OH},"
            f"crop={W}:{H}:x={cx}+10*sin(t*9):y={cy}+6*cos(t*11),"
            f"format=yuv420p"
        ),
        "static": (
            f"{to_portrait},"
            f"format=yuv420p"
        ),
    }
    return filters.get(motion_type, filters["slow_zoom_in"])


def _render_short_black(out_path: Path, duration_sec: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={SHORT_WIDTH}x{SHORT_HEIGHT}:r={VIDEO_FPS}",
        "-t", str(max(1.4, round(duration_sec, 2))),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-an", str(out_path),
    ]
    _run_ffmpeg(cmd, "short_black_placeholder", 20)


# ─────────────────────────────────────────────
# SHORT SUBTITLE GENERATION
# ─────────────────────────────────────────────

def _generate_short_srt(blueprint: dict, run_id: str) -> Optional[Path]:
    """
    Generates an SRT file for the short clip narration.
    Uses the short_clip.narration field from the blueprint.
    """
    short_clip = blueprint.get("short_clip") or {}
    narration  = (short_clip.get("narration") or "").strip()
    if not narration:
        return None

    srt_path = video_path(run_id, "short_subtitles.srt")
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    words    = narration.split()
    target_duration = float(short_clip.get("duration_target_sec", 42.0))
    rate     = len(words) / max(target_duration, 1.0)
    chunk_sz = 6   # slightly shorter lines for portrait format
    chunks   = [words[i:i + chunk_sz] for i in range(0, len(words), chunk_sz)]

    entries: list[str] = []
    t = 0.0
    for idx, chunk in enumerate(chunks):
        text      = " ".join(chunk)
        chunk_dur = len(chunk) / max(rate, 0.5)
        chunk_dur = max(1.5, min(chunk_dur, 4.0))
        h  = int(t // 3600); m = int((t % 3600) // 60)
        s  = int(t % 60);   ms = int((t - int(t)) * 1000)
        te = t + chunk_dur
        he = int(te // 3600); me = int((te % 3600) // 60)
        se = int(te % 60);   mse = int((te - int(te)) * 1000)
        entries.append(
            f"{idx+1}\n"
            f"{h:02d}:{m:02d}:{s:02d},{ms:03d} --> {he:02d}:{me:02d}:{se:02d},{mse:03d}\n"
            f"{text}"
        )
        t += chunk_dur

    if not entries:
        return None

    srt_path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return srt_path


# ─────────────────────────────────────────────
# SHORT AUDIO + TEXT OVERLAY
# ─────────────────────────────────────────────

def _apply_short_audio_and_text(
    video_in:  Path,
    audio_in:  Optional[Path],
    hook_text: str,
    srt_path:  Optional[Path],
    out_path:  Path,
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = audio_in and audio_in.exists()
    fp        = _find_font().replace(":", "\\:")
    font_opt  = f"fontfile={fp}:"
    bs        = _BS

    hook_safe   = _escape_drawtext(hook_text.upper()[:20])
    closer_text = "FULL STORY ON CHANNEL"

    # Drawtext overlays for hook (opening) and closer (end)
    drawtext_filters = ",".join([
        (
            f"drawtext=text='{hook_safe}':{font_opt}"
            f"fontsize=100:fontcolor=white:"
            f"borderw=6:bordercolor=0xCC0000:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-80:"
            f"enable=between(t{bs},0{bs},2.0)"
        ),
        (
            f"drawtext=text='{_escape_drawtext(closer_text)}':{font_opt}"
            f"fontsize=62:fontcolor=white:"
            f"box=1:boxcolor=0x8B0000@0.90:boxborderw=16:"
            f"x=(w-text_w)/2:y=h-250:"
            f"enable=between(t{bs},32{bs},32767)"
        ),
    ])

    # Build combined filter chain
    vf_parts: list[str] = [drawtext_filters]
    if srt_path and srt_path.exists():
        srt_str = str(srt_path).replace("\\", "\\\\").replace(":", "\\:")
        vf_parts.append(
            f"subtitles='{srt_str}'"
            f":force_style='{_SHORT_SUBTITLE_STYLE}'"
        )
    vf = ",".join(vf_parts)

    def _attempt(vf_str: str) -> bool:
        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_in), "-i", str(audio_in),
                "-filter_complex", f"[0:v]{vf_str}[vout]",
                "-map", "[vout]", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
                "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
                "-threads", str(FFMPEG_THREADS),
                "-shortest", str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", str(video_in),
                "-vf", vf_str,
                "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
                "-threads", str(FFMPEG_THREADS),
                "-an", str(out_path),
            ]
        ok, err = _run_ffmpeg(cmd, "short_audio_text_pass", 180)
        if not ok:
            log.warning(f"Short text pass error: {err[-200:]}")
            out_path.unlink(missing_ok=True)
        return ok and out_path.exists()

    # Attempt 1: full chain with subtitles
    if _attempt(vf):
        return True

    # Attempt 2: drawtext only, no subtitles
    log.warning("Short full pass failed — retrying drawtext only.")
    if _attempt(drawtext_filters):
        return True

    # Attempt 3: strip fontfile= and retry
    log.warning("Short drawtext pass failed — retrying without fontfile.")
    chain_nf = re.sub(r":fontfile=[^:,\[\]]+", "", drawtext_filters)
    chain_nf = re.sub(r"fontfile=[^:,\[\]]+:", "", chain_nf)
    return _attempt(chain_nf)


# ─────────────────────────────────────────────
# AUDIO PATH RESOLUTION
# ─────────────────────────────────────────────

def _get_short_audio_path(blueprint: dict, run_id: str) -> Optional[Path]:
    short_clip = blueprint.get("short_clip") or {}
    for key in ("mixed_audio_path", "audio_path"):
        p = short_clip.get(key, "")
        if p and Path(p).exists():
            return Path(p)
    for fname in ("narration_short.mp3", "short_final_audio.mp3"):
        p = audio_path(run_id, fname)
        if p.exists():
            return p
    log.warning("No short clip audio found — short will be silent.")
    return None

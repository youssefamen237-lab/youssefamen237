"""
engines/video_renderer.py  — Phase B
Adds two Phase B capabilities to the existing renderer:

1. VIDEO CLIP SCENE ASSETS
   When scene_builder passes T2V-generated clips (asset_type="video_clip"),
   _render_single_chunk loops the clip with -stream_loop instead of
   using -loop 1 for static images.

2. ASSEMBLYAI WORD-LEVEL SUBTITLE SYNC
   _generate_srt_file checks for word_timestamps.json produced by
   assemblyai_sync.py. If present it builds a perfectly-timed SRT
   (every subtitle chunk maps to exact spoken milliseconds).
   Falls back to the existing approximated timing if not available.

All other logic (two-pass audio/text, motion filters, drawtext chain)
is unchanged from the previous version.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import (
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    AUDIO_BITRATE, AUDIO_SAMPLE_RATE,
    FFMPEG_THREADS, FFMPEG_PRESET, FFMPEG_CRF,
    FONTS_DIR,
)
from config.constants import AssetCategory
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import video_path, audio_path, ensure_run_workspace

log = get_logger(__name__)

_BS             = chr(92)
_BATCH_SZ       = 15
_FFMPEG_TIMEOUT = 120
_FINAL_TIMEOUT  = 600

_SRC_W = int(VIDEO_WIDTH  * 1.25)
_SRC_H = int(VIDEO_HEIGHT * 1.25)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

_SUBTITLE_STYLE = (
    "FontName=Liberation Sans Bold"
    ",FontSize=26"
    ",PrimaryColour=&H00FFFFFF"
    ",OutlineColour=&H00000000"
    ",BackColour=&H60000000"
    ",BorderStyle=3"
    ",Outline=2"
    ",Shadow=0"
    ",Alignment=2"
    ",MarginV=55"
)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_video_renderer(ctx: DailyRunContext) -> DailyRunContext:
    if not ctx.scene_assets:
        log.error("No scene assets — cannot render video.")
        return ctx

    log.info(
        f"Video renderer starting. "
        f"Scenes={len(ctx.scene_assets)}, "
        f"T2V_clips={sum(1 for s in ctx.scene_assets if s.get('asset_type')=='video_clip')}"
    )
    ensure_run_workspace(ctx.run_id)

    # Phase 1: chunks
    chunk_paths = _render_all_chunks(ctx.scene_assets, ctx.run_id)
    if not chunk_paths:
        log.error("Zero chunks rendered — aborting.")
        return ctx

    # Phase 2+3: concat
    silent_path = video_path(ctx.run_id, "video_silent.mp4")
    ok = _batch_concat_chunks(chunk_paths, silent_path, ctx.run_id)
    if not ok or not silent_path.exists():
        log.error("Chunk concat failed — aborting.")
        return ctx
    log.info(f"Silent video: {silent_path.stat().st_size // (1024*1024)}MB")
    _cleanup_files(chunk_paths)

    # Phase 4: SRT (AssemblyAI-synced or approximated)
    srt_path = _generate_srt_file(ctx.script_blueprint or {}, ctx.run_id)
    if srt_path:
        log.info(f"SRT file: {srt_path.name} ({'AssemblyAI-synced' if _has_word_timestamps(ctx.run_id) else 'approximated'})")

    drawtext_chain = _build_drawtext_chain(ctx.script_blueprint or {}, ctx.scene_assets)
    final_path = video_path(ctx.run_id, "long_video.mp4")

    ok = _apply_audio_and_text(
        silent_path, ctx.narration_audio_path,
        drawtext_chain, srt_path, final_path, ctx.run_id,
    )

    if ok and final_path.exists() and final_path.stat().st_size > 100_000:
        ctx.long_video_path = str(final_path)
        log.info(f"Long video: {final_path.name} ({final_path.stat().st_size // (1024*1024)}MB)")
        silent_path.unlink(missing_ok=True)
    else:
        log.warning("Final pass failed — keeping silent video as fallback.")
        ctx.long_video_path = str(silent_path)

    ctx.mark_stage("video_renderer")
    return ctx


# ─────────────────────────────────────────────
# SRT GENERATION (Phase B: AssemblyAI-first)
# ─────────────────────────────────────────────

def _has_word_timestamps(run_id: str) -> bool:
    return audio_path(run_id, "word_timestamps.json").exists()


def _generate_srt_file(blueprint: dict, run_id: str) -> Optional[Path]:
    """
    Priority 1: AssemblyAI word timestamps (exact millisecond sync).
    Priority 2: Blueprint part timing approximation.
    """
    # ── Priority 1: AssemblyAI ────────────────────────────────────
    ts_path = audio_path(run_id, "word_timestamps.json")
    if ts_path.exists():
        try:
            from engines.assemblyai_sync import build_srt_from_word_timestamps
            import json as _j
            word_ts = _j.loads(ts_path.read_text(encoding="utf-8"))
            if word_ts:
                srt_content = build_srt_from_word_timestamps(word_ts, chunk_size=7)
                if srt_content.strip():
                    srt_path = video_path(run_id, "subtitles.srt")
                    srt_path.parent.mkdir(parents=True, exist_ok=True)
                    srt_path.write_text(srt_content, encoding="utf-8")
                    log.debug(f"SRT from AssemblyAI: {srt_content.count(chr(10)//2)} entries")
                    return srt_path
        except Exception as exc:
            log.debug(f"AssemblyAI SRT build failed ({exc}) — falling back to approximation.")

    # ── Priority 2: Approximated from blueprint timing ────────────
    return _generate_srt_approximated(blueprint, run_id)


def _generate_srt_approximated(blueprint: dict, run_id: str) -> Optional[Path]:
    """Approximated SRT from blueprint part narration + timing estimates."""
    parts = blueprint.get("parts", [])
    if not parts:
        return None

    srt_path = video_path(run_id, "subtitles.srt")
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[str] = []
    idx = 1

    for part in parts:
        narration    = (part.get("narration") or "").strip()
        start_sec    = float(part.get("start_time_sec", 0.0))
        duration_sec = float(part.get("duration_sec", 30.0))
        if not narration or duration_sec < 1.5:
            continue
        words   = narration.split()
        n_words = len(words)
        if n_words == 0:
            continue
        rate     = n_words / duration_sec
        chunk_sz = 7
        chunks   = [words[i:i + chunk_sz] for i in range(0, n_words, chunk_sz)]
        t = start_sec
        for chunk in chunks:
            text      = " ".join(chunk)
            chunk_dur = max(1.8, min(len(chunk) / max(rate, 0.5), 5.0))
            entries.append(
                f"{idx}\n"
                f"{_sec_to_srt(t)} --> {_sec_to_srt(t + chunk_dur)}\n"
                f"{text}"
            )
            idx += 1
            t   += chunk_dur

    if not entries:
        return None
    srt_path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return srt_path


def _sec_to_srt(sec: float) -> str:
    sec = max(0.0, sec)
    h   = int(sec // 3600)
    m   = int((sec % 3600) // 60)
    s   = int(sec % 60)
    ms  = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─────────────────────────────────────────────
# CHUNK RENDERING (Phase B: handles video clips)
# ─────────────────────────────────────────────

def _render_all_chunks(scene_assets: list[dict], run_id: str) -> list[Path]:
    chunks: list[Path] = []
    total = len(scene_assets)
    for i, scene in enumerate(scene_assets):
        chunk_out = video_path(run_id, f"chunk_{i:04d}.mp4")
        ok = _render_single_chunk(scene, chunk_out)
        if ok:
            chunks.append(chunk_out)
        else:
            log.warning(f"Chunk {i:04d} ({scene.get('part_id','?')}) failed — black placeholder.")
            _render_black_placeholder(chunk_out, scene.get("duration_sec", 3.5))
            if chunk_out.exists():
                chunks.append(chunk_out)
        if (i + 1) % 10 == 0:
            log.info(f"  Progress: {i+1}/{total} chunks")
    return chunks


def _render_single_chunk(scene: dict, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path   = scene.get("asset_path", "")
    asset_type   = scene.get("asset_type", "stock_photo")
    duration_sec = float(scene.get("duration_sec", 3.5))
    duration_sec = max(1.5, min(duration_sec, 8.0))

    if not asset_path or not Path(asset_path).exists():
        log.warning(f"Scene asset missing: {asset_path}")
        return False

    # ── Phase B: T2V video clip ───────────────────────────────────
    if asset_type == "video_clip" or str(asset_path).lower().endswith(".mp4"):
        return _render_video_clip_chunk(asset_path, duration_sec, out_path)

    # ── Static image (original path) ─────────────────────────────
    card_types = {
        AssetCategory.EVIDENCE_CARD.value,
        AssetCategory.LOCATION_DATE_CARD.value,
        "shock_overlay", "cctv_frame", "cctv_style",
        AssetCategory.CCTV_STYLE.value,
    }
    motion_type = "static" if asset_type in card_types else scene.get("motion_type", "slow_zoom_in")
    vf = _build_motion_filter(motion_type, duration_sec)

    cmd = [
        "ffmpeg", "-y", "-loop", "1",
        "-t", str(round(duration_sec, 3)),
        "-i", asset_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
        "-r", str(VIDEO_FPS),
        "-t", str(round(duration_sec, 3)),
        "-threads", str(FFMPEG_THREADS),
        "-an", str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, f"chunk {out_path.stem}", _FFMPEG_TIMEOUT)
    if not ok:
        log.warning(f"Image chunk failed ({out_path.stem}): {err[-120:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 5000


def _render_video_clip_chunk(
    clip_path:    str,
    duration_sec: float,
    out_path:     Path,
) -> bool:
    """
    Renders a T2V-generated video clip as a scene chunk.
    Uses -stream_loop -1 to loop if clip < duration_sec.
    Applies scale+pad to ensure exact VIDEO_WIDTH×VIDEO_HEIGHT output.
    """
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",          # loop the clip if shorter than duration
        "-i", str(clip_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
        "-r", str(VIDEO_FPS),
        "-t", str(round(duration_sec, 3)),
        "-threads", str(FFMPEG_THREADS),
        "-an",
        str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, f"clip_chunk {out_path.stem}", _FFMPEG_TIMEOUT)
    if not ok:
        log.warning(f"Video clip chunk failed ({out_path.stem}): {err[-120:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 5000


def _render_black_placeholder(out_path: Path, duration_sec: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}",
        "-t", str(max(1.5, round(duration_sec, 2))),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-an", str(out_path),
    ]
    _run_ffmpeg(cmd, "black_placeholder", 30)


# ─────────────────────────────────────────────
# BATCH CONCAT
# ─────────────────────────────────────────────

def _batch_concat_chunks(chunk_paths: list[Path], final_out: Path, run_id: str) -> bool:
    final_out.parent.mkdir(parents=True, exist_ok=True)
    if len(chunk_paths) <= _BATCH_SZ:
        return _concat_with_demuxer(chunk_paths, final_out, run_id, "concat_all")
    batches     = [chunk_paths[i:i + _BATCH_SZ] for i in range(0, len(chunk_paths), _BATCH_SZ)]
    batch_files: list[Path] = []
    for b_idx, batch in enumerate(batches):
        bout = video_path(run_id, f"batch_{b_idx:03d}.mp4")
        ok   = _concat_with_demuxer(batch, bout, run_id, f"batch_{b_idx}")
        if ok and bout.exists():
            batch_files.append(bout)
    if not batch_files:
        return False
    ok = _concat_with_demuxer(batch_files, final_out, run_id, "final_concat")
    _cleanup_files(batch_files)
    return ok


def _concat_with_demuxer(
    input_paths: list[Path], out_path: Path, run_id: str, label: str
) -> bool:
    list_path = video_path(run_id, f"concat_{label}.txt")
    list_path.parent.mkdir(parents=True, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        for p in input_paths:
            if p.exists():
                f.write(f"file '{str(p.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)]
    ok, err = _run_ffmpeg(cmd, f"concat_{label}", 300)
    list_path.unlink(missing_ok=True)
    if not ok:
        log.warning(f"Concat {label} failed: {err[-150:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 10_000


# ─────────────────────────────────────────────
# TWO-PASS AUDIO + TEXT
# ─────────────────────────────────────────────

def _apply_audio_and_text(
    video_path_in:  Path,
    audio_path_in:  Optional[str],
    drawtext_chain: str,
    srt_path:       Optional[Path],
    out_path:       Path,
    run_id:         str = "",
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = bool(audio_path_in and Path(audio_path_in).exists())
    has_text  = bool(drawtext_chain or (srt_path and srt_path.exists()))

    audio_temp = (video_path(run_id, "_pass_audio_temp.mp4") if run_id
                  else out_path.parent / f"_audio_temp_{out_path.stem}.mp4")

    if has_audio:
        ok_a   = _pass_audio_overlay(video_path_in, audio_path_in, audio_temp)
        source = audio_temp if ok_a else video_path_in
        if not ok_a:
            log.warning("Audio overlay failed — continuing without audio.")
    else:
        source = video_path_in

    if has_text:
        ok_b = _pass_text_and_subtitles(source, drawtext_chain, srt_path, out_path)
        if not ok_b and srt_path:
            log.warning("Full text pass failed — retrying subtitles only.")
            ok_b = _pass_text_and_subtitles(source, "", srt_path, out_path)
        if not ok_b and drawtext_chain:
            log.warning("Subtitles pass failed — retrying drawtext only.")
            ok_b = _pass_text_and_subtitles(source, drawtext_chain, None, out_path)
        if not ok_b:
            log.warning("Drawtext pass failed — retrying without fontfile.")
            chain_nf = re.sub(r":fontfile=[^:,\[\]]+", "", drawtext_chain)
            chain_nf = re.sub(r"fontfile=[^:,\[\]]+:", "", chain_nf)
            ok_b = _pass_text_and_subtitles(source, chain_nf, None, out_path)
        if not ok_b:
            log.error("All text/subtitle passes failed — audio-only fallback.")
            if has_audio and source != video_path_in and source.exists():
                shutil.copy2(str(source), str(out_path))
                source.unlink(missing_ok=True)
                return True
            return False
        if has_audio and source != video_path_in and Path(source).exists():
            Path(source).unlink(missing_ok=True)
        return True
    else:
        if has_audio and source != video_path_in and Path(source).exists():
            Path(source).rename(out_path)
        else:
            shutil.copy2(str(video_path_in), str(out_path))
        return True


def _pass_audio_overlay(video_in: Path, audio_in: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_in), "-i", str(audio_in),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-ar", str(AUDIO_SAMPLE_RATE), "-shortest", str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, "audio_overlay_pass", 300)
    if not ok:
        log.warning(f"Audio overlay error: {err[-150:]}")
    return ok and out_path.exists() and out_path.stat().st_size > 10_000


def _pass_text_and_subtitles(
    video_in: Path, drawtext_chain: str, srt_path: Optional[Path], out_path: Path,
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    filters: list[str] = []
    if drawtext_chain:
        filters.append(drawtext_chain)
    if srt_path and srt_path.exists():
        srt_str = str(srt_path).replace("\\", "\\\\").replace(":", "\\:")
        filters.append(f"subtitles='{srt_str}':force_style='{_SUBTITLE_STYLE}'")
    if not filters:
        shutil.copy2(str(video_in), str(out_path))
        return True
    vf  = ",".join(filters)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_in), "-vf", vf,
        "-c:v", "libx264", "-preset", FFMPEG_PRESET, "-crf", str(FFMPEG_CRF),
        "-c:a", "copy", "-threads", str(FFMPEG_THREADS), str(out_path),
    ]
    ok, err = _run_ffmpeg(cmd, "text_subtitle_pass", _FINAL_TIMEOUT)
    if not ok:
        log.warning(f"Text/subtitle pass error: {err[-300:]}")
        out_path.unlink(missing_ok=True)
    return ok and out_path.exists() and out_path.stat().st_size > 100_000


# ─────────────────────────────────────────────
# MOTION FILTER BUILDER
# ─────────────────────────────────────────────

def _build_motion_filter(motion_type: str, duration_sec: float) -> str:
    bs  = _BS
    d   = max(int(duration_sec * VIDEO_FPS), VIDEO_FPS)
    zi  = round(0.24 / max(d, 1), 7)
    dur = round(duration_sec, 3)
    sw, sh = _SRC_W, _SRC_H
    cx = (sw - VIDEO_WIDTH)  // 2
    cy = (sh - VIDEO_HEIGHT) // 2
    px = int((sw - VIDEO_WIDTH)  * 0.85)
    py = int((sh - VIDEO_HEIGHT) * 0.85)
    filters = {
        "slow_zoom_in":  (f"scale={sw}:{sh}:flags=lanczos,zoompan=z=min(zoom+{zi}{bs},1.25):x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:d={d}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},format=yuv420p"),
        "slow_zoom_out": (f"scale={sw}:{sh}:flags=lanczos,zoompan=z=if(lte(zoom{bs},1.0001){bs},1.25{bs},max(1.0001{bs},zoom-{zi})):x=(iw-ow/zoom)/2:y=(ih-oh/zoom)/2:d={d}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},format=yuv420p"),
        "pan_right":     (f"scale={sw}:{sh},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:x=min({px}{bs},{px}*t/{dur}):y={cy},format=yuv420p"),
        "pan_left":      (f"scale={sw}:{sh},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:x=max(0{bs},{px}*(1-t/{dur})):y={cy},format=yuv420p"),
        "drift_up":      (f"scale={sw}:{sh},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:x={cx}:y=max(0{bs},{py}*(1-t/{dur})),format=yuv420p"),
        "drift_down":    (f"scale={sw}:{sh},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:x={cx}:y=min({py}{bs},{py}*t/{dur}),format=yuv420p"),
        "shake":         (f"scale={sw}:{sh},crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:x={cx}+10*sin(t*8):y={cy}+6*cos(t*10),format=yuv420p"),
        "static":        (f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p"),
    }
    return filters.get(motion_type, filters["slow_zoom_in"])


# ─────────────────────────────────────────────
# DRAWTEXT CHAIN
# ─────────────────────────────────────────────

def _build_drawtext_chain(blueprint: dict, scene_assets: list[dict]) -> str:
    filters: list[str] = []
    bs       = _BS
    fp       = _find_font().replace(":", "\\:")
    font_opt = f"fontfile={fp}:"

    filters.append(
        f"drawtext=text='+18':{font_opt}"
        f"fontsize=52:fontcolor=white:x=28:y=22:"
        f"box=1:boxcolor=0x8B0000@0.95:boxborderw=16:"
        f"enable=between(t{bs},0{bs},8.0)"
    )
    story_label = blueprint.get("story_label", "")
    if story_label:
        safe_label = _escape_drawtext(story_label.upper()[:40])
        filters.append(
            f"drawtext=text='{safe_label}':{font_opt}"
            f"fontsize=64:fontcolor=white:x=(w-text_w)/2:y=h-160:"
            f"box=1:boxcolor=0x8B0000@0.88:

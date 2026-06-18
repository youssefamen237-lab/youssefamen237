"""
engines/video_assembler.py

Assembles the final MP4 from pre-fetched media items, TTS audio,
optional background music, and subtitle file.

Pipeline
────────
  1. Probe audio duration via ffprobe
  2. Distribute that duration across N segments (alignment-aware when available)
  3. Pre-process every media item (scale+crop+trim/loop for video; Ken Burns for images)
  4. Concatenate with the concat demuxer
  5. Mix narration + optional music (music at 12 % volume)
  6. Burn subtitles and encode the final deliverable
  7. Clean up all temp files
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import structlog

from engines.image_processor import get_image_processor

logger = structlog.get_logger(__name__)

_SUB_STYLE_SHORT = (
    "Fontname=Arial,FontSize=56,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BackColour=&H80000000,Outline=3,Shadow=1,"
    "Alignment=2,MarginV=50"
)
_SUB_STYLE_LONG = (
    "Fontname=Arial,FontSize=36,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BackColour=&H80000000,Outline=2,Shadow=1,"
    "Alignment=2,MarginV=30"
)
_MUSIC_VOLUME = 0.12


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MediaItem:
    """A single piece of media assigned to one script segment."""
    local_path:         str
    asset_type:         str            # "video" | "image"
    provider:           str
    width:              int
    height:             int
    segment_index:      int
    search_query:       str
    duration_seconds:   Optional[float] = None  # available for video clips only
    provider_source_id: Optional[str]   = None  # original ID from the provider API
    file_size_bytes:    Optional[int]   = None  # populated after download


@dataclass
class VideoAssemblyJob:
    queue_id:        str
    video_type:      str            # "short" | "long"
    audio_path:      str
    media_items:     List[Optional[MediaItem]]
    output_path:     str
    subtitle_path:   Optional[str]  = None
    music_path:      Optional[str]  = None
    alignment:       Optional[dict] = None
    script_segments: Optional[List[dict]] = field(default=None)


# ─────────────────────────────────────────────────────────────────────────────
# Assembler
# ─────────────────────────────────────────────────────────────────────────────

class VideoAssembler:

    def __init__(self) -> None:
        self._proc = get_image_processor()

    # ── Public ────────────────────────────────────────────────────────────────

    def assemble(self, job: VideoAssemblyJob) -> str:
        """Run the full assembly pipeline.  Returns job.output_path."""
        temp_dir = tempfile.mkdtemp(prefix=f"yta_asm_{job.queue_id[:12]}_")
        try:
            return self._run_pipeline(job, temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Pipeline stages ───────────────────────────────────────────────────────

    def _run_pipeline(self, job: VideoAssemblyJob, temp_dir: str) -> str:
        W, H = (1080, 1920) if job.video_type == "short" else (1920, 1080)
        sub_style = _SUB_STYLE_SHORT if job.video_type == "short" else _SUB_STYLE_LONG

        # Stage 1 – audio duration
        total_dur = self._probe_duration(job.audio_path)
        if total_dur <= 0:
            raise RuntimeError(f"Could not determine audio duration: {job.audio_path}")

        # Stage 2 – segment durations
        n = max(len(job.media_items), 1)
        seg_durs = self._calc_segment_durations(
            total_dur, n, job.alignment, job.script_segments
        )

        # Stage 3 – pre-process every media item
        processed: List[str] = []
        for i, item in enumerate(job.media_items):
            dur = seg_durs[i] if i < len(seg_durs) else (total_dur / n)
            out = os.path.join(temp_dir, f"seg_{i:04d}.mp4")
            processed.append(
                self._prepare_segment(item, dur, out, W, H)
            )

        # Stage 4 – concatenate
        concat_path = os.path.join(temp_dir, "concat.mp4")
        self._concat_clips(processed, concat_path)

        # Stage 5 – final encode
        Path(job.output_path).parent.mkdir(parents=True, exist_ok=True)
        self._final_encode(
            video_path=concat_path,
            audio_path=job.audio_path,
            music_path=job.music_path,
            subtitle_path=job.subtitle_path,
            sub_style=sub_style,
            output_path=job.output_path,
            total_dur=total_dur,
        )

        size = os.path.getsize(job.output_path)
        logger.info(
            "video_assembled",
            queue_id=job.queue_id[:8],
            video_type=job.video_type,
            segments=n,
            duration=round(total_dur, 2),
            size_mb=round(size / 1_048_576, 1),
        )
        return job.output_path

    # ── Segment preparation ───────────────────────────────────────────────────

    def _prepare_segment(
        self,
        item: Optional[MediaItem],
        duration: float,
        output_path: str,
        width: int,
        height: int,
    ) -> str:
        if item is None:
            return self._proc.generate_black_clip(duration, output_path, width, height)
        if item.asset_type == "image":
            return self._proc.image_to_video_clip(
                item.local_path, duration, output_path, width, height
            )
        # video
        return self._proc.preprocess_video_clip(
            item.local_path, duration, output_path, width, height
        )

    # ── Concat ────────────────────────────────────────────────────────────────

    @staticmethod
    def _concat_clips(clip_paths: List[str], output_path: str) -> None:
        list_file = output_path + ".txt"
        with open(list_file, "w") as fh:
            for p in clip_paths:
                fh.write(f"file '{p}'\n")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]
        _ffmpeg(cmd, "concat_clips")
        os.unlink(list_file)

    # ── Final encode ──────────────────────────────────────────────────────────

    @staticmethod
    def _final_encode(
        video_path: str,
        audio_path: str,
        music_path: Optional[str],
        subtitle_path: Optional[str],
        sub_style: str,
        output_path: str,
        total_dur: float,
    ) -> None:
        cmd = ["ffmpeg", "-y"]
        inputs = [video_path, audio_path]
        has_music = bool(music_path and os.path.exists(music_path))

        cmd += ["-i", video_path, "-i", audio_path]
        if has_music:
            cmd += ["-i", music_path]

        # Audio filter
        if has_music:
            audio_filter = (
                f"[2:a]volume={_MUSIC_VOLUME},"
                f"atrim=duration={total_dur},"
                f"asetpts=PTS-STARTPTS[bg];"
                f"[1:a][bg]amix=inputs=2:duration=first[outa]"
            )
            cmd += ["-filter_complex", audio_filter]
            audio_map = "[outa]"
        else:
            audio_map = "1:a"

        # Video filter (subtitles)
        has_subs = bool(subtitle_path and os.path.exists(subtitle_path))
        if has_subs:
            # Escape path for FFmpeg filter
            esc_path = subtitle_path.replace("\\", "/").replace(":", "\\:")
            vf = f"subtitles={esc_path}:force_style='{sub_style}'"
            cmd += ["-vf", vf]

        cmd += ["-map", "0:v"]
        cmd += ["-map", audio_map]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", "30", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ]
        _ffmpeg(cmd, "final_encode")

    # ── Segment durations ─────────────────────────────────────────────────────

    def _calc_segment_durations(
        self,
        total_dur: float,
        n: int,
        alignment: Optional[dict],
        script_segments: Optional[List[dict]],
    ) -> List[float]:
        """
        Try alignment-based per-sentence timing first.
        Falls back to even distribution if alignment is absent or incomplete.
        """
        if alignment and script_segments:
            result = self._alignment_based_durations(
                alignment, script_segments, total_dur
            )
            if result and len(result) == n:
                return result
        # Even distribution
        base = total_dur / n
        return [base] * n

    @staticmethod
    def _alignment_based_durations(
        alignment: dict,
        segments: List[dict],
        total_dur: float,
    ) -> Optional[List[float]]:
        chars  = alignment.get("characters", [])
        starts = alignment.get("start_times", [])
        ends   = alignment.get("end_times",   [])
        if not chars or len(chars) != len(starts):
            return None

        full_text = "".join(chars)
        durations: List[float] = []
        pos = 0

        for seg in segments:
            sentence: str = seg.get("sentence", "").strip()
            if not sentence:
                durations.append(total_dur / max(len(segments), 1))
                continue
            idx = full_text.find(sentence, pos)
            if idx == -1:
                return None   # can't locate sentence → fall back
            end_idx = min(idx + len(sentence) - 1, len(ends) - 1)
            start_t = float(starts[idx])
            end_t   = float(ends[end_idx])
            durations.append(max(0.5, end_t - start_t))
            pos = idx + len(sentence)

        return durations if len(durations) == len(segments) else None

    # ── Probe ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _probe_duration(path: str) -> float:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            data = json.loads(r.stdout)
            return float(data["format"].get("duration", 0) or 0)
        except Exception:
            return 0.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ffmpeg(cmd: List[str], context: str, timeout: int = 300) -> None:
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"FFmpeg {context} failed (rc={result.returncode}): {stderr}")


# ── Singleton ──────────────────────────────────────────────────────────────────

_asm_instance: Optional[VideoAssembler] = None

def get_assembler() -> VideoAssembler:
    global _asm_instance
    if _asm_instance is None:
        _asm_instance = VideoAssembler()
    return _asm_instance

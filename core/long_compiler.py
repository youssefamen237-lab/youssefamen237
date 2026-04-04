"""
core/long_compiler.py
=====================
Stitches the last N rendered Shorts into a single long-form compilation
video for the weekly upload.

Source priority
---------------
1. SQLite DB  — fetches video rows with status='rendered' or 'uploaded',
               ordered by created_at DESC, up to COMPILATION_MAX_CLIPS.
2. Filesystem — if DB returns < MIN_CLIPS rows, scans OUTPUT_SHORTS_DIR
               for .mp4 files as a fallback (handles cold-start scenarios).

Humanization
------------
- Transition: random 0.3–0.8 s black fade between clips.
- Clip order: newest-first (most relevant content leads).
- Output filename: timestamped so no two compilations collide.

Output
------
A single .mp4 in OUTPUT_COMPILATIONS written at 1080×1920, 30fps,
H.264/AAC, web-optimised.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    VideoFileClip,
    concatenate_videoclips,
)

from config.settings import (
    COMPILATION_MAX_CLIPS,
    OUTPUT_COMPILATIONS,
    OUTPUT_SHORTS_DIR,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from database.db import Database
from utils.logger import get_logger
from utils.retry import retry_render

logger = get_logger(__name__)

_W: int = VIDEO_WIDTH
_H: int = VIDEO_HEIGHT

# Minimum clips needed to produce a compilation
MIN_CLIPS: int = 3

# Black fade transition duration range (seconds)
_FADE_MIN: float = 0.3
_FADE_MAX: float = 0.8

# Title card duration at the start of the compilation (seconds)
_TITLE_CARD_DURATION: float = 2.0


@dataclass
class CompilationResult:
    """
    Output of one completed compilation render.

    Attributes
    ----------
    video_path    : Absolute path to the rendered .mp4.
    duration_secs : Total compilation duration.
    clip_count    : Number of Short clips stitched together.
    """
    video_path:    Path
    duration_secs: float
    clip_count:    int


class LongCompiler:
    """
    Assembles a weekly compilation from rendered Short .mp4 files.

    Parameters
    ----------
    db          : Shared Database instance.
    output_dir  : Destination for compilation .mp4 files.
    shorts_dir  : Source directory for Short .mp4 files (filesystem fallback).
    max_clips   : Maximum number of Shorts to include.
    """

    def __init__(
        self,
        db:          Optional[Database] = None,
        output_dir:  Path = OUTPUT_COMPILATIONS,
        shorts_dir:  Path = OUTPUT_SHORTS_DIR,
        max_clips:   int  = COMPILATION_MAX_CLIPS,
    ) -> None:
        self._db         = db or Database()
        self._output_dir = Path(output_dir)
        self._shorts_dir = Path(shorts_dir)
        self._max_clips  = max_clips

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._db.init()

    # ── Public ─────────────────────────────────────────────────────────────

    @retry_render
    def compile(
        self,
        week_label:  Optional[str] = None,
        max_clips:   Optional[int] = None,
    ) -> CompilationResult:
        """
        Render a compilation from the most recent available Shorts.

        Parameters
        ----------
        week_label : Optional label for the output filename
                     (e.g. '2024-W42'). Auto-generated if None.
        max_clips  : Override the instance-level max_clips for this run.

        Returns
        -------
        CompilationResult with path and metadata.

        Raises
        ------
        RuntimeError : Fewer than MIN_CLIPS usable clips were found.
        """
        limit     = max_clips or self._max_clips
        label     = week_label or _iso_week_label()
        clip_paths = self._resolve_clip_paths(limit)

        if len(clip_paths) < MIN_CLIPS:
            raise RuntimeError(
                f"Compilation aborted: only {len(clip_paths)} clip(s) found "
                f"(minimum {MIN_CLIPS} required). "
                f"Run the daily Short pipeline first."
            )

        logger.info(
            "Compiling %d clips — label=%s", len(clip_paths), label
        )

        clips = self._load_and_standardise(clip_paths)
        final = self._concatenate_with_fades(clips)

        out_path = self._output_dir / f"compilation_{label}_{_uid()}.mp4"

        final.write_videofile(
            str(out_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            ffmpeg_params=[
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
            ],
            logger=None,
            verbose=False,
        )

        duration = final.duration
        final.close()
        for c in clips:
            c.close()

        logger.info(
            "Compilation rendered: %s  duration=%.1fs  clips=%d",
            out_path.name, duration, len(clip_paths),
        )

        return CompilationResult(
            video_path=out_path,
            duration_secs=duration,
            clip_count=len(clip_paths),
        )

    # ── Clip resolution ─────────────────────────────────────────────────────

    def _resolve_clip_paths(self, limit: int) -> list[Path]:
        """
        Build the ordered list of Short .mp4 paths to stitch.

        Strategy:
        1. Query DB for videos with type='short', status IN ('rendered','uploaded'),
           ordered newest-first.
        2. If DB yields fewer than MIN_CLIPS, supplement from filesystem.
        3. Verify each path exists and is a valid file before including it.
        """
        paths: list[Path] = []

        # ── DB source ──────────────────────────────────────────────────────
        try:
            rows = self._db_get_shorts(limit)
            for row in rows:
                p = Path(row["file_path"])
                if p.exists() and p.stat().st_size > 1000:
                    paths.append(p)
        except Exception as exc:
            logger.warning("DB short fetch failed (%s) — using filesystem only.", exc)

        # ── Filesystem fallback ────────────────────────────────────────────
        if len(paths) < MIN_CLIPS:
            logger.info(
                "DB returned %d paths — supplementing from filesystem.", len(paths)
            )
            fs_paths = self._filesystem_shorts(limit)
            existing_set = set(paths)
            for p in fs_paths:
                if p not in existing_set:
                    paths.append(p)
                    existing_set.add(p)

        # Deduplicate while preserving order, then cap
        seen: set[Path] = set()
        unique: list[Path] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                unique.append(p)

        result = unique[:limit]
        logger.info("Clip paths resolved: %d/%d", len(result), limit)
        return result

    def _db_get_shorts(self, limit: int) -> list[dict]:
        """Fetch short video rows from DB newest-first."""
        with self._db._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos "
                "WHERE video_type='short' AND status IN ('rendered','uploaded') "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _filesystem_shorts(self, limit: int) -> list[Path]:
        """Scan OUTPUT_SHORTS_DIR for .mp4 files, newest-first."""
        if not self._shorts_dir.exists():
            return []
        mp4s = sorted(
            self._shorts_dir.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return mp4s[:limit]

    # ── Clip loading & standardisation ─────────────────────────────────────

    def _load_and_standardise(self, paths: list[Path]) -> list[VideoFileClip]:
        """
        Load each .mp4, resize/crop to 1080×1920, drop audio track for now
        (audio is kept per-clip during concatenation).

        Returns a list of MoviePy VideoFileClips ready for concatenation.
        """
        clips: list[VideoFileClip] = []
        for p in paths:
            try:
                clip = VideoFileClip(str(p))

                # Crop / resize to portrait if needed
                clip = _fit_to_portrait(clip)

                clips.append(clip)
                logger.debug("Loaded clip: %s (%.1fs)", p.name, clip.duration)
            except Exception as exc:
                logger.warning("Skipping clip %s — load error: %s", p.name, exc)

        return clips

    # ── Concatenation with fades ────────────────────────────────────────────

    def _concatenate_with_fades(
        self, clips: list[VideoFileClip]
    ) -> CompositeVideoClip:
        """
        Concatenate clips with a random-duration black fade transition
        between each pair.

        Each clip gets:
        - fadeout at end:  random.uniform(FADE_MIN, FADE_MAX) seconds.
        - fadein at start: same value.

        Returns a single concatenated VideoClip.
        """
        if len(clips) == 1:
            return clips[0]

        processed: list[VideoFileClip] = []

        for i, clip in enumerate(clips):
            fade = random.uniform(_FADE_MIN, _FADE_MAX)
            c = clip.fadein(fade).fadeout(fade)
            processed.append(c)

        final = concatenate_videoclips(processed, method="compose")
        return final


# ── Utilities ────────────────────────────────────────────────────────────────

def _fit_to_portrait(clip: VideoFileClip) -> VideoFileClip:
    """Crop and resize a clip to exactly 1080×1920 (9:16 portrait)."""
    target_ratio = _W / _H
    actual_ratio = clip.w / clip.h

    if actual_ratio > target_ratio:
        new_w = int(clip.h * target_ratio)
        x1 = (clip.w - new_w) // 2
        clip = clip.crop(x1=x1, width=new_w)
    else:
        new_h = int(clip.w / target_ratio)
        y1 = (clip.h - new_h) // 2
        clip = clip.crop(y1=y1, height=new_h)

    return clip.resize((_W, _H))


def _iso_week_label() -> str:
    """Return the current ISO year-week string, e.g. '2024-W42'."""
    now = datetime.now(timezone.utc)
    return f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"


def _uid() -> str:
    """Short 8-char UUID fragment for unique filenames."""
    return str(uuid.uuid4())[:8]

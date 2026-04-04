"""
core/video_editor.py
====================
Composites background footage, TTS audio, and caption overlays into
a finished YouTube Short using MoviePy.

Anti-bot humanization
---------------------
- Duration    : audio_duration + random.uniform(0.5, 1.8) seconds.
- Zoom effect : 60% probability slow zoom-IN, 40% slow zoom-OUT.
- Zoom factor : random.uniform(1.04, 1.12) — never the same value.
- Caption fade: 0.08–0.18s random fade-in per beat.

Three-frame structure
---------------------
  [hook segment] + [body segment] + [cta segment]

Each segment uses the same background clip (looped/trimmed to fit)
with the corresponding caption overlay composited on top.
"""

import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image

from config.settings import (
    CTA_TEXT,
    FRAME_CTA_DURATION,
    FRAME_HOOK_DURATION,
    OUTPUT_SHORTS_DIR,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from core.captions import CaptionEngine, CaptionFrame
from core.tts import TTSResult
from core.visuals import ClipResult
from utils.logger import get_logger
from utils.retry import retry_render

logger = get_logger(__name__)

_W: int = VIDEO_WIDTH
_H: int = VIDEO_HEIGHT

# Random padding added to audio duration to produce total video duration
_PADDING_MIN: float = 0.5
_PADDING_MAX: float = 1.8

# Zoom factor range (applied over the full clip duration)
_ZOOM_MIN: float = 1.04
_ZOOM_MAX: float = 1.12

# Probability of zoom-IN (vs zoom-OUT)
_ZOOM_IN_PROBABILITY: float = 0.60

# Caption fade-in duration range (seconds)
_FADE_MIN: float = 0.08
_FADE_MAX: float = 0.18


@dataclass
class EditResult:
    """
    Output of one completed video edit.

    Attributes
    ----------
    video_path     : Absolute path to the rendered .mp4 file.
    duration_secs  : Actual video duration in seconds.
    zoom_direction : 'in' | 'out' — which effect was applied.
    zoom_factor    : The exact zoom magnitude used.
    """
    video_path:    Path
    duration_secs: float
    zoom_direction: str
    zoom_factor:   float


# ══════════════════════════════════════════════════════════════════════════
# ZOOM EFFECT
# ══════════════════════════════════════════════════════════════════════════

def _make_zoom_frame(
    base_frame: np.ndarray,
    t: float,
    total_duration: float,
    zoom_factor: float,
    zoom_in: bool,
) -> np.ndarray:
    """
    Applies a slow zoom-in or zoom-out Ken Burns effect to a single frame.

    Parameters
    ----------
    base_frame     : HxWx3 uint8 numpy array (the background frame).
    t              : Current time position in the clip (seconds).
    total_duration : Full clip duration (seconds).
    zoom_factor    : Max zoom magnitude (e.g. 1.08 = 8% scale increase).
    zoom_in        : True = start wide, end tight; False = start tight, end wide.

    Returns
    -------
    HxWx3 uint8 numpy array — cropped/scaled to original dimensions.
    """
    progress = t / max(total_duration, 0.001)   # 0.0 → 1.0

    if zoom_in:
        scale = 1.0 + (zoom_factor - 1.0) * progress
    else:
        scale = zoom_factor - (zoom_factor - 1.0) * progress

    h, w = base_frame.shape[:2]
    new_h = int(h * scale)
    new_w = int(w * scale)

    # Resize using PIL for quality (Lanczos)
    pil_img = Image.fromarray(base_frame)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)

    # Centre-crop back to original dimensions
    top  = (new_h - h) // 2
    left = (new_w - w) // 2
    cropped = np.array(pil_img)[top:top + h, left:left + w]

    return cropped


# ══════════════════════════════════════════════════════════════════════════
# BACKGROUND PREPARATION
# ══════════════════════════════════════════════════════════════════════════

def _prepare_background(
    clip_path: Path,
    target_duration: float,
    zoom_factor: float,
    zoom_in: bool,
) -> CompositeVideoClip:
    """
    Load the stock clip, crop to 9:16, loop to target_duration,
    and apply the Ken Burns zoom effect.

    Returns a MoviePy VideoClip ready for compositing.
    """
    raw = VideoFileClip(str(clip_path))

    # ── Crop to 9:16 (portrait) ──────────────────────────────────────────
    raw_ratio = raw.w / raw.h
    target_ratio = _W / _H

    if raw_ratio > target_ratio:
        # Clip is wider than 9:16 — crop sides
        new_w = int(raw.h * target_ratio)
        x1 = (raw.w - new_w) // 2
        cropped = raw.crop(x1=x1, width=new_w)
    else:
        # Clip is taller than 9:16 — crop top/bottom
        new_h = int(raw.w / target_ratio)
        y1 = (raw.h - new_h) // 2
        cropped = raw.crop(y1=y1, height=new_h)

    # ── Resize to exact output dimensions ────────────────────────────────
    resized = cropped.resize((_W, _H))

    # ── Loop to fill target_duration ─────────────────────────────────────
    if resized.duration < target_duration:
        loops = int(np.ceil(target_duration / resized.duration))
        from moviepy.editor import concatenate_videoclips as _concat
        resized = _concat([resized] * loops)

    trimmed = resized.subclip(0, target_duration)

    # ── Apply zoom effect frame-by-frame ─────────────────────────────────
    def apply_zoom(get_frame, t):
        frame = get_frame(t)
        return _make_zoom_frame(frame, t, target_duration, zoom_factor, zoom_in)

    zoomed = trimmed.fl(apply_zoom, apply_to=["mask"])
    zoomed = zoomed.without_audio()

    return zoomed


# ══════════════════════════════════════════════════════════════════════════
# CAPTION OVERLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _pil_to_moviepy(
    caption_frame: CaptionFrame,
    start: float,
    fade_duration: float,
) -> ImageClip:
    """
    Convert a CaptionFrame (PIL RGBA image) into a MoviePy ImageClip
    positioned at `start` seconds with a short fade-in.
    """
    rgba_array = np.array(caption_frame.image)

    clip = (
        ImageClip(rgba_array, ismask=False)
        .set_start(start)
        .set_duration(caption_frame.duration)
        .fadein(fade_duration)
    )
    return clip


def _build_caption_clips(
    hook_frame:   CaptionFrame,
    body_frames:  list[CaptionFrame],
    cta_frame:    CaptionFrame,
    hook_duration: float,
    body_duration: float,
) -> list[ImageClip]:
    """
    Convert all CaptionFrame objects to timed MoviePy ImageClips.
    Returns the list sorted by start time.
    """
    fade = random.uniform(_FADE_MIN, _FADE_MAX)
    clips: list[ImageClip] = []

    # Hook — starts at t=0
    clips.append(_pil_to_moviepy(hook_frame, start=0.0, fade_duration=fade))

    # Body beats — follow immediately after hook
    body_start = hook_duration
    for bf in body_frames:
        clips.append(_pil_to_moviepy(bf, start=body_start, fade_duration=fade))
        body_start += bf.duration

    # CTA — starts after body
    cta_start = hook_duration + body_duration
    clips.append(_pil_to_moviepy(cta_frame, start=cta_start, fade_duration=fade))

    return clips


# ══════════════════════════════════════════════════════════════════════════
# VIDEO EDITOR — public interface
# ══════════════════════════════════════════════════════════════════════════

class VideoEditor:
    """
    Assembles a finished YouTube Short from pre-generated components.

    Parameters
    ----------
    output_dir : Directory for rendered .mp4 files.  Created if missing.
    """

    def __init__(self, output_dir: Path = OUTPUT_SHORTS_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._caption_engine = CaptionEngine()

    # ── Public ─────────────────────────────────────────────────────────────

    @retry_render
    def render(
        self,
        script_id:   str,
        hook_text:   str,
        body_text:   str,
        tts_result:  TTSResult,
        clip_result: ClipResult,
    ) -> EditResult:
        """
        Render one Short and write it to disk.

        Duration model (anti-bot humanization)
        ---------------------------------------
        total_video_duration = tts_result.duration_secs
                               + random.uniform(0.5, 1.8)

        The hook segment duration = tts_result.hook_end_secs (exact audio timing).
        The body segment duration = total_video_duration
                                    - hook_duration
                                    - FRAME_CTA_DURATION.

        Zoom model
        ----------
        zoom_direction : 'in' with 60% probability, 'out' with 40%.
        zoom_factor    : random.uniform(1.04, 1.12).

        Parameters
        ----------
        script_id   : UUID for output filename correlation.
        hook_text   : Frame 1 text.
        body_text   : Frame 2 text.
        tts_result  : TTSResult from core/tts.py.
        clip_result : ClipResult from core/visuals.py.

        Returns
        -------
        EditResult with the path and metadata of the rendered file.
        """
        uid = script_id or str(uuid.uuid4())

        # ── Randomised parameters (anti-bot humanization) ─────────────────
        padding        = random.uniform(_PADDING_MIN, _PADDING_MAX)
        total_duration = tts_result.duration_secs + padding
        zoom_factor    = random.uniform(_ZOOM_MIN, _ZOOM_MAX)
        zoom_in        = random.random() < _ZOOM_IN_PROBABILITY
        zoom_dir       = "in" if zoom_in else "out"

        hook_duration  = tts_result.hook_end_secs
        cta_duration   = FRAME_CTA_DURATION
        body_duration  = max(
            0.5,
            total_duration - hook_duration - cta_duration,
        )

        logger.info(
            "Rendering Short: id=%s total=%.2fs zoom=%s@%.3f",
            uid, total_duration, zoom_dir, zoom_factor,
        )

        # ── Caption overlays ──────────────────────────────────────────────
        hook_caption  = self._caption_engine.render_hook(hook_text, hook_duration)
        body_captions = self._caption_engine.render_body(body_text, body_duration)
        cta_caption   = self._caption_engine.render_cta(CTA_TEXT, cta_duration)

        caption_clips = _build_caption_clips(
            hook_frame=hook_caption,
            body_frames=body_captions,
            cta_frame=cta_caption,
            hook_duration=hook_duration,
            body_duration=body_duration,
        )

        # ── Background footage ────────────────────────────────────────────
        background = _prepare_background(
            clip_path=clip_result.local_path,
            target_duration=total_duration,
            zoom_factor=zoom_factor,
            zoom_in=zoom_in,
        )

        # ── Composite video ───────────────────────────────────────────────
        composite = CompositeVideoClip(
            [background] + caption_clips,
            size=(_W, _H),
        ).set_duration(total_duration)

        # ── Attach TTS audio ──────────────────────────────────────────────
        audio = AudioFileClip(str(tts_result.audio_path))
        # Pad audio with silence if video is longer (the random padding gap)
        if audio.duration < total_duration:
            from moviepy.audio.AudioClip import AudioClip as _AC
            silence = _AC(lambda t: 0, duration=total_duration - audio.duration)
            from moviepy.editor import concatenate_audioclips
            audio = concatenate_audioclips([audio, silence])

        final = composite.set_audio(audio.set_duration(total_duration))

        # ── Write output ──────────────────────────────────────────────────
        out_path = self._output_dir / f"{uid}.mp4"
        final.write_videofile(
            str(out_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",           # balance speed vs file size
            ffmpeg_params=[
                "-crf", "23",        # quality: 18=lossless, 28=low; 23=good balance
                "-pix_fmt", "yuv420p",  # max compatibility (required for YouTube)
                "-movflags", "+faststart",  # web-optimised — metadata at front
            ],
            logger=None,             # suppress MoviePy's own progress bar in CI
            verbose=False,
        )

        # Close clips to release file handles
        final.close()
        background.close()
        audio.close()

        logger.info(
            "Short rendered: %s (%.2fs, zoom-%s @ %.3f)",
            out_path.name, total_duration, zoom_dir, zoom_factor,
        )

        return EditResult(
            video_path=out_path,
            duration_secs=total_duration,
            zoom_direction=zoom_dir,
            zoom_factor=zoom_factor,
        )

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..generators.types import QuizItem
from ..utils.text import ffmpeg_escape_text, clamp_text
from ..utils.ffmpeg import run as ffmpeg_run, which as which_bin
from .graphics import generate_spot_difference_pair
from .background_prep import prepare_blurred_background

log = logging.getLogger("short_maker")


def _find_font() -> str:
    env_path = os.getenv("FONT_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise RuntimeError("No font file found. Set FONT_PATH env var.")


def _build_text_blocks(item: QuizItem) -> Tuple[str, Optional[str]]:
    q = item.question.strip()
    if item.template == "mcq_3" and item.options:
        opts = item.options[:3]
        # A/B/C
        lines = [q, "", f"A) {opts[0]}", f"B) {opts[1]}", f"C) {opts[2]}"]
        return "\n".join(lines), None
    if item.template == "true_false":
        return q + "\n\nTrue ✅ or False ❌", None
    if item.template == "which_one" and item.options:
        a, b = item.options[:2]
        return q + f"\n\nA) {a}\nB) {b}", None
    return q, None


def render_short(
    cfg: Dict[str, Any],
    *,
    item: QuizItem,
    voice_audio: str | Path,
    background_image: str | Path,
    music_audio: Optional[str | Path],
    out_path: str | Path,
    work_dir: str | Path,
) -> Path:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    w = int(cfg["content"]["short"]["width"])
    h = int(cfg["content"]["short"]["height"])
    fps = int(cfg["content"]["short"]["fps"])
    timer_s = float(cfg["content"]["short"]["timer_seconds"])
    answer_s = float(cfg["content"]["short"]["answer_seconds"])
    total_s = timer_s + answer_s

    blur_sigma = float(cfg["content"]["short"]["blur_sigma"])
    # Pre-blur the background once (static image), much faster than per-frame blur.
    prepared_bg = work_dir / "bg_prepared.jpg"
    prepare_blurred_background(background_image, out_path=prepared_bg, width=w, height=h, blur_sigma=blur_sigma)
    background_image = prepared_bg
    safe_margin = int(cfg["content"]["short"]["safe_margin_px"])

    voice_vol = float(cfg["content"]["short"]["voice_volume"])
    music_vol = float(cfg["content"]["short"]["music_volume"])

    font = _find_font()

    q_text, _ = _build_text_blocks(item)
    q_text = clamp_text(q_text, 220)
    a_text = clamp_text(item.answer.strip(), int(cfg["content"]["short"]["max_answer_chars"]))

    q_esc = ffmpeg_escape_text(q_text)
    a_esc = ffmpeg_escape_text(a_text)

    ffmpeg = which_bin("ffmpeg")

    inputs = []
    inputs.extend(["-loop", "1", "-t", f"{total_s:.2f}", "-i", str(background_image)])
    inputs.extend(["-i", str(voice_audio)])
    has_music = music_audio is not None and str(music_audio)
    if has_music:
        inputs.extend(["-stream_loop", "-1", "-i", str(music_audio)])

    # Spot difference overlays
    spot_left = None
    spot_right = None
    if item.template == "spot_difference":
        diff_code = (item.extra or {}).get("diff_code", "DOT")
        spot_left, spot_right = generate_spot_difference_pair(work_dir, str(diff_code))
        inputs.extend(["-i", str(spot_left), "-i", str(spot_right)])

    # Video filters
    # Background: scale/crop + blur
    vf_parts = []
    vf_parts.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[bg];")

    # Optional: overlay spot images
    if item.template == "spot_difference" and spot_left and spot_right:
        panel_w = int(w * 0.42)
        panel_h = int(panel_w)  # square
        gap = int(w * 0.03)
        x_left = int((w - (panel_w * 2 + gap)) / 2)
        y_panels = int(h * 0.33)
        x_right = x_left + panel_w + gap

        vf_parts.append(f"[3:v]scale={panel_w}:{panel_h}[pl];")
        vf_parts.append(f"[4:v]scale={panel_w}:{panel_h}[pr];")
        vf_parts.append(f"[bg][pl]overlay={x_left}:{y_panels}:format=auto[tmp1];")
        vf_parts.append(f"[tmp1][pr]overlay={x_right}:{y_panels}:format=auto[base];")
    else:
        vf_parts.append("[bg]copy[base];")

    # Draw boxes for readability
    box_h = int(h * 0.44)
    box_y = int(h * 0.18)
    vf_parts.append(f"[base]drawbox=x={safe_margin}:y={box_y}:w={w-2*safe_margin}:h={box_h}:color=black@0.35:t=fill[boxed];")

    # Question text
    q_fontsize = int(h * 0.055)
    q_y = box_y + int(box_h * 0.18)
    vf_parts.append(
        "[boxed]"
        f"drawtext=fontfile='{font}':text='{q_esc}':x=(w-text_w)/2:y={q_y}:"
        f"fontsize={q_fontsize}:fontcolor=white:borderw=3:bordercolor=black:line_spacing=10:"
        f"enable='lt(t,{timer_s:.2f})'[qtxt];"
    )

    # Countdown timer number (bottom)
    timer_fontsize = int(h * 0.08)
    timer_y = int(h * 0.78)
    vf_parts.append(
        "[qtxt]"
        f"drawtext=fontfile='{font}':text='%{{eif\\:ceil({timer_s:.2f}-t)\\:d}}':x=(w-text_w)/2:y={timer_y}:"
        f"fontsize={timer_fontsize}:fontcolor=white:borderw=4:bordercolor=black:"
        f"enable='lt(t,{timer_s:.2f})'[timed];"
    )

    # Answer text (no voice)
    a_fontsize = int(h * 0.09)
    a_y = int(h * 0.43)
    vf_parts.append(
        "[timed]"
        f"drawtext=fontfile='{font}':text='{a_esc}':x=(w-text_w)/2:y={a_y}:"
        f"fontsize={a_fontsize}:fontcolor=white:borderw=4:bordercolor=black:"
        f"enable='gte(t,{timer_s:.2f})'[vout]"
    )

    vf = "".join(vf_parts)

    # Audio filters
    # Voice: trim to timer_s and set volume
    # Music (optional): trim to timer_s, volume, then mix.
    # Then concat with silence for answer_s.
    if has_music:
        # Inputs: 1=a_voice, 2=a_music
        af = (
            f"[1:a]atrim=0:{timer_s:.2f},asetpts=N/SR/TB,volume={voice_vol:.3f}[va];"
            f"[2:a]atrim=0:{timer_s:.2f},asetpts=N/SR/TB,volume={music_vol:.3f}[ma];"
            f"[va][ma]amix=inputs=2:duration=first:dropout_transition=0[mix];"
            f"anullsrc=r=44100:cl=stereo,atrim=0:{answer_s:.2f}[sil];"
            f"[mix][sil]concat=n=2:v=0:a=1[aout]"
        )
    else:
        af = (
            f"[1:a]atrim=0:{timer_s:.2f},asetpts=N/SR/TB,volume={voice_vol:.3f}[mix];"
            f"anullsrc=r=44100:cl=stereo,atrim=0:{answer_s:.2f}[sil];"
            f"[mix][sil]concat=n=2:v=0:a=1[aout]"
        )

    cmd = [
        ffmpeg,
        "-y",
        *inputs,
        "-filter_complex",
        vf + ";" + af,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        str(out),
    ]
    ffmpeg_run(cmd)
    return out

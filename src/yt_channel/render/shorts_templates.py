from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ..utils.text import ffmpeg_escape_text, wrap_text
from .ffmpeg import run_ffmpeg


@dataclass(frozen=True)
class BrandKit:
    font_regular: Path
    font_bold: Path
    color_text: str = "white"
    color_accent: str = "#FFD54A"
    color_secondary: str = "#4FC3F7"
    box_color: str = "black@0.55"


def _scale_crop_expr(out_w: int, out_h: int) -> str:
    # Scale to cover then crop center
    return (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h}"
    )


def _base_video_filter(bg_label: str, *, out_w: int, out_h: int, blur: bool, fade_in: float) -> str:
    blur_filter = ",gblur=sigma=20" if blur else ""
    fade = f",fade=t=in:st=0:d={fade_in}" if fade_in > 0 else ""
    return f"[{bg_label}]" + _scale_crop_expr(out_w, out_h) + ",format=rgba" + blur_filter + fade + "[base]"


def _draw_box(*, x: int, y: int, w: int, h: int, color: str) -> str:
    return f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill"


def _drawtext(
    *,
    text: str,
    fontfile: Path,
    fontsize: int,
    fontcolor: str,
    x: str,
    y: str,
    enable: Optional[str] = None,
    borderw: int = 0,
    bordercolor: str = "black",
    line_spacing: int = 8,
) -> str:
    t = ffmpeg_escape_text(text)
    base = (
        "drawtext="
        f"fontfile='{fontfile.as_posix()}':"
        f"text='{t}':"
        f"fontsize={fontsize}:"
        f"fontcolor={fontcolor}:"
        f"x={x}:y={y}:"
        f"line_spacing={line_spacing}:"
        f"borderw={borderw}:bordercolor={bordercolor}:"
        "alpha=1"
    )
    if enable:
        base += f":enable='{enable}'"
    return base


def render_short(
    *,
    out_path: Path,
    bg_image: Path,
    question_text: str,
    answer_text: str,
    choices: Optional[List[str]],
    template_id: str,
    tts_audio: Path,
    tts_duration: float,
    music_audio: Optional[Path],
    music_volume_db: float,
    countdown_seconds: int,
    answer_seconds: float,
    fps: int,
    resolution: Tuple[int, int],
    brand: BrandKit,
    with_music: bool,
) -> None:
    out_w, out_h = resolution
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_dur = float(tts_duration) + float(countdown_seconds) + float(answer_seconds)
    total_dur = max(total_dur, 6.0)
    t_q_end = float(tts_duration)
    t_count_start = t_q_end
    t_answer_start = t_q_end + float(countdown_seconds)
    t_end = total_dur

    # Wrap text for readability
    q_wrapped = wrap_text(question_text, 28)
    a_wrapped = wrap_text(answer_text, 26)
    choices_wrapped = [wrap_text(c, 26) for c in (choices or [])]

    # Layout constants (safe area)
    box_margin_x = 70
    box_margin_top = 260
    box_margin_bottom = 320
    box_x = box_margin_x
    box_y = box_margin_top
    box_w = out_w - 2 * box_margin_x
    box_h = out_h - box_margin_top - box_margin_bottom

    # Dynamic y positions
    q_y = int(out_h * 0.30)
    opt_y = int(out_h * 0.50)
    timer_y = int(out_h * 0.66)
    ans_y = int(out_h * 0.76)

    fade_in = 0.25

    # Video filters
    filters: List[str] = []

    if template_id == "zoom_reveal":
        # Crossfade from heavy blur to light blur over first 1.6s
        filters.append(f"[0:v]{_scale_crop_expr(out_w, out_h)},format=rgba,split=2[bg1][bg2]")
        filters.append("[bg1]gblur=sigma=28[blurred]")
        filters.append("[bg2]gblur=sigma=10[light]")
        filters.append(
            f"[blurred][light]xfade=transition=fade:duration=1.6:offset=0,fade=t=in:st=0:d={fade_in}[base]"
        )
    else:
        filters.append(_base_video_filter("0:v", out_w=out_w, out_h=out_h, blur=True, fade_in=fade_in))

    # Box behind text
    filters.append(f"[base]{_draw_box(x=box_x, y=box_y, w=box_w, h=box_h, color=brand.box_color)}[boxed]")

    # Question text
    filters.append(
        f"[boxed]{_drawtext(text=q_wrapped, fontfile=brand.font_bold, fontsize=64, fontcolor=brand.color_text, x='(w-text_w)/2', y=str(q_y), borderw=2, bordercolor='black@0.35')}[q]"
    )

    v_label = "q"

    # Template-specific overlays
    if template_id == "mcq" and choices_wrapped:
        opt_text = "\\n".join(choices_wrapped[:3])
        filters.append(
            f"[{v_label}]{_drawtext(text=opt_text, fontfile=brand.font_regular, fontsize=54, fontcolor=brand.color_secondary, x='(w-text_w)/2', y=str(opt_y), borderw=2, bordercolor='black@0.35', line_spacing=12)}[v1]"
        )
        v_label = "v1"

    if template_id == "true_false":
        prompt = "TRUE or FALSE?"
        filters.append(
            f"[{v_label}]{_drawtext(text=prompt, fontfile=brand.font_regular, fontsize=60, fontcolor=brand.color_secondary, x='(w-text_w)/2', y=str(opt_y), borderw=2, bordercolor='black@0.35')}[v1]"
        )
        v_label = "v1"

    # Countdown numbers (3..1)
    for i in range(countdown_seconds, 0, -1):
        start = t_count_start + (countdown_seconds - i)
        end = start + 1.0
        enable = f"between(t,{start:.3f},{min(end, t_answer_start):.3f})"
        filters.append(
            f"[{v_label}]{_drawtext(text=str(i), fontfile=brand.font_bold, fontsize=200, fontcolor=brand.color_accent, x='(w-text_w)/2', y=str(timer_y), enable=enable, borderw=3, bordercolor='black@0.4', line_spacing=0)}[c{i}]"
        )
        v_label = f"c{i}"

    # Answer
    enable_answer = f"between(t,{t_answer_start:.3f},{min(t_answer_start + answer_seconds, t_end):.3f})"
    filters.append(
        f"[{v_label}]{_drawtext(text=a_wrapped, fontfile=brand.font_bold, fontsize=72, fontcolor=brand.color_accent, x='(w-text_w)/2', y=str(ans_y), enable=enable_answer, borderw=2, bordercolor='black@0.35')}[vout]"
    )

    vf = ";".join(filters)

    # Audio filter
    # Pad voice to full duration
    audio_filters: List[str] = []
    audio_filters.append(f"[1:a]apad=pad_dur={total_dur:.3f},atrim=0:{total_dur:.3f}[voice]")

    use_music = bool(with_music and music_audio)
    if use_music:
        music_vol = math.pow(10.0, music_volume_db / 20.0)
        audio_filters.append(f"[2:a]volume={music_vol:.6f},atrim=0:{total_dur:.3f}[music]")
        # Duck music using voice
        audio_filters.append(
            "[music][voice]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=200[ducked]"
        )
        audio_filters.append("[ducked][voice]amix=inputs=2:duration=first:dropout_transition=0[aout]")
    else:
        audio_filters.append("[voice]anull[aout]")

    af = ";".join(audio_filters)

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(bg_image),
        "-i",
        str(tts_audio),
    ]

    if use_music:
        # Loop music to cover full duration
        cmd += ["-stream_loop", "-1", "-i", str(music_audio)]

    cmd += [
        "-t",
        f"{total_dur:.3f}",
        "-filter_complex",
        vf + ";" + af,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]

    run_ffmpeg(cmd, timeout=900)

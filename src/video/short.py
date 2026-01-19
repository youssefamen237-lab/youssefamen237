from __future__ import annotations

from pathlib import Path

from ..utils.ffmpeg import run_ffmpeg
from ..utils.text import wrap_for_display


def _write_textfile(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _pad_audio(in_wav: Path, out_wav: Path, *, duration_s: int) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(in_wav),
            "-af",
            f"apad=pad_dur={duration_s},atrim=0:{duration_s}",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(out_wav),
        ]
    )


def render_short(
    *,
    bg_path: Path,
    question: str,
    answer: str,
    tts_wav: Path,
    out_mp4: Path,
    font_bold_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    countdown_s: int = 10,
    answer_s: int = 2,
) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    total_s = int(countdown_s + answer_s)

    q_wrapped = wrap_for_display(question, max_chars=26, max_lines=4)
    a_wrapped = wrap_for_display(answer, max_chars=22, max_lines=2)

    q_txt = out_mp4.with_suffix(".question.txt")
    a_txt = out_mp4.with_suffix(".answer.txt")
    _write_textfile(q_txt, q_wrapped)
    _write_textfile(a_txt, a_wrapped)

    padded_wav = out_mp4.with_suffix(".padded.wav")
    _pad_audio(tts_wav, padded_wav, duration_s=total_s)

    bar_w = int(width * 0.78)
    bar_h = 26
    bar_y = height - 220

    q_fontsize = int(height * 0.058)
    a_fontsize = int(height * 0.085)
    timer_fontsize = int(height * 0.075)

    panel_w = int(width * 0.90)
    panel_h = int(height * 0.36)
    panel_x = f"(w-{panel_w})/2"
    panel_y = f"(h-{panel_h})/2-120"

    answer_panel_w = int(width * 0.84)
    answer_panel_h = int(height * 0.22)
    answer_panel_x = f"(w-{answer_panel_w})/2"
    answer_panel_y = f"(h-{answer_panel_h})/2-40"

    bg_zoom = 1.32
    bg_blur = 30
    bg_brightness = -0.12

    base_bg = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"scale=iw*{bg_zoom}:ih*{bg_zoom},"
        f"crop={width}:{height},"
        f"gblur=sigma={bg_blur},"
        f"eq=brightness={bg_brightness}"
    )

    vf = (
        f"{base_bg},"
        f"drawbox=x={panel_x}:y={panel_y}:w={panel_w}:h={panel_h}:color=black@0.28:t=fill:enable='between(t\\,0\\,{countdown_s})',"
        f"drawbox=x={answer_panel_x}:y={answer_panel_y}:w={answer_panel_w}:h={answer_panel_h}:color=black@0.30:t=fill:enable='between(t\\,{countdown_s}\\,{total_s})',"
        f"drawbox=x=(w-{bar_w})/2:y={bar_y}:w={bar_w}:h={bar_h}:color=white@0.22:t=fill,"
        f"drawbox=x=(w-{bar_w})/2:y={bar_y}:w='{bar_w}*(1-min(t\\,{countdown_s})/{countdown_s})':h={bar_h}:color=white@0.88:t=fill:enable='lt(t\\,{countdown_s})',"
        f"drawtext=fontfile='{font_bold_path}':textfile='{q_txt}':reload=1:fontsize={q_fontsize}:fontcolor=white:shadowcolor=black:shadowx=4:shadowy=4:x=(w-text_w)/2:y=(h-text_h)/2-120:line_spacing=10:enable='between(t\\,0\\,{countdown_s})',"
        f"drawtext=fontfile='{font_bold_path}':text='%{{eif\\:trunc({countdown_s}-t)\\:d}}':fontsize={timer_fontsize}:fontcolor=white:shadowcolor=black:shadowx=4:shadowy=4:x=(w-text_w)/2:y=h-340:enable='between(t\\,0\\,{countdown_s})',"
        f"drawtext=fontfile='{font_bold_path}':textfile='{a_txt}':reload=1:fontsize={a_fontsize}:fontcolor=white:shadowcolor=black:shadowx=4:shadowy=4:x=(w-text_w)/2:y=(h-text_h)/2-60:line_spacing=10:enable='between(t\\,{countdown_s}\\,{total_s})'"
    )

    run_ffmpeg(
        [
            "-loop",
            "1",
            "-i",
            str(bg_path),
            "-i",
            str(padded_wav),
            "-t",
            str(total_s),
            "-r",
            str(fps),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    )

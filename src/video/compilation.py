from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..utils.ffmpeg import FFmpegError, run_ffmpeg
from ..utils.text import wrap_for_display


def _write_textfile(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _render_static_segment(
    *,
    bg_path: Path,
    out_mp4: Path,
    text: str,
    font_bold_path: str,
    width: int,
    height: int,
    fps: int,
    duration_s: int,
    fontsize: int,
) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    txt = out_mp4.with_suffix(".txt")
    _write_textfile(txt, wrap_for_display(text, max_chars=18, max_lines=3))

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

    panel_w = int(width * 0.90)
    panel_h = int(height * 0.30)

    vf = (
        f"{base_bg},"
        f"drawbox=x=(w-{panel_w})/2:y=(h-{panel_h})/2:w={panel_w}:h={panel_h}:color=black@0.28:t=fill,"
        f"drawtext=fontfile='{font_bold_path}':textfile='{txt}':reload=1:fontsize={fontsize}:fontcolor=white:"
        f"shadowcolor=black:shadowx=4:shadowy=4:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=10"
    )

    run_ffmpeg(
        [
            "-loop",
            "1",
            "-i",
            str(bg_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration_s),
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


def render_compilation(
    *,
    short_paths: Sequence[Path],
    bg_path: Path,
    out_mp4: Path,
    font_bold_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    intro = out_mp4.with_name(out_mp4.stem + ".intro.mp4")
    outro = out_mp4.with_name(out_mp4.stem + ".outro.mp4")
    trans = out_mp4.with_name(out_mp4.stem + ".transition.mp4")

    _render_static_segment(
        bg_path=bg_path,
        out_mp4=intro,
        text="Daily Trivia Compilation\n4 Quick Questions",
        font_bold_path=font_bold_path,
        width=width,
        height=height,
        fps=fps,
        duration_s=5,
        fontsize=int(height * 0.07),
    )

    _render_static_segment(
        bg_path=bg_path,
        out_mp4=trans,
        text="Next Question",
        font_bold_path=font_bold_path,
        width=width,
        height=height,
        fps=fps,
        duration_s=2,
        fontsize=int(height * 0.07),
    )

    _render_static_segment(
        bg_path=bg_path,
        out_mp4=outro,
        text="How many did you get?\nComment your score!",
        font_bold_path=font_bold_path,
        width=width,
        height=height,
        fps=fps,
        duration_s=5,
        fontsize=int(height * 0.065),
    )

    concat_list = out_mp4.with_suffix(".concat.txt")
    lines = [f"file '{intro.as_posix()}'\n"]
    for i, sp in enumerate(short_paths):
        lines.append(f"file '{sp.as_posix()}'\n")
        if i != len(short_paths) - 1:
            lines.append(f"file '{trans.as_posix()}'\n")
    lines.append(f"file '{outro.as_posix()}'\n")
    concat_list.write_text("".join(lines), encoding="utf-8")

    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(out_mp4)])
        return
    except FFmpegError:
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
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

\
from __future__ import annotations

import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from autoyt.pipeline.content.question_bank import QuestionItem
from autoyt.pipeline.media.backgrounds import BackgroundAsset, pick_background
from autoyt.pipeline.media.music import MusicAsset
from autoyt.pipeline.media.tts import synthesize_tts
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.text import ffmpeg_escape, wrap_text

log = get_logger("autoyt.render_long")


@dataclass
class LongRenderResult:
    video_path: Path
    duration_s: float
    segments: List[Path]


def _run(cmd: list[str]) -> None:
    log.debug("Running: " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _render_segment(
    item: QuestionItem,
    voice_audio: Path,
    voice_duration_s: float,
    bg_path: Path,
    out_path: Path,
    cfg_long: Dict[str, Any],
    rng: random.Random,
) -> float:
    W = int(cfg_long["width"])
    H = int(cfg_long["height"])
    fps = int(cfg_long.get("fps", 30))
    timer_s = int(cfg_long.get("timer_seconds", 5))
    answer_s = float(cfg_long.get("answer_seconds", 2.5))
    font_main = str(cfg_long.get("font_main"))
    font_secondary = str(cfg_long.get("font_secondary"))

    # font sizes for 1920x1080
    fs_q = 66
    fs_a = 78
    fs_timer = 110
    fs_footer = 40

    t_voice_end = float(max(0.1, voice_duration_s))
    t_timer_start = t_voice_end
    t_timer_end = t_timer_start + timer_s
    t_answer_end = t_timer_end + answer_s
    total = t_answer_end

    q_text = item.question_text.strip()
    if item.options and item.template_id in {"mc_capital", "which_continent"}:
        labels = ["A", "B", "C", "D"]
        opts = []
        for i, opt in enumerate(item.options):
            lab = labels[i] if i < len(labels) else str(i + 1)
            opts.append(f"{lab}) {opt}")
        q_text = q_text + "\n\n" + "\n".join(opts)

    q_text = wrap_text(q_text, max_chars=40)
    a_text = wrap_text(item.answer_text.strip(), max_chars=32)

    draw = []
    draw.append(f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.22:t=fill")
    # Question
    draw.append(
        "drawtext="
        f"fontfile='{font_main}':"
        f"text='{ffmpeg_escape(q_text)}':"
        f"fontsize={fs_q}:"
        "fontcolor=white:"
        "borderw=4:bordercolor=black@0.65:"
        f"x=(w-text_w)/2:"
        f"y=h*0.14:"
        f"line_spacing=10:"
        f"enable='between(t,0,{t_timer_end})'"
    )

    # Timer
    for i in range(timer_s):
        val = timer_s - i
        start = t_timer_start + i
        end = min(t_timer_end, start + 1.0)
        draw.append(
            "drawtext="
            f"fontfile='{font_main}':"
            f"text='{val}':"
            f"fontsize={fs_timer}:"
            "fontcolor=white:"
            "borderw=6:bordercolor=black@0.7:"
            f"x=(w-text_w)/2:"
            f"y=h*0.68:"
            f"enable='between(t,{start},{end})'"
        )

    # Answer
    draw.append(
        "drawtext="
        f"fontfile='{font_main}':"
        f"text='{ffmpeg_escape(a_text)}':"
        f"fontsize={fs_a}:"
        "fontcolor=white:"
        "borderw=5:bordercolor=black@0.75:"
        f"x=(w-text_w)/2:"
        f"y=(h-text_h)/2:"
        f"line_spacing=10:"
        f"enable='between(t,{t_timer_end},{t_answer_end})'"
    )

    # Footer
    footer = rng.choice(["Comment your score!", "Subscribe for daily quizzes.", "How many can you get right?"])
    draw.append(
        "drawtext="
        f"fontfile='{font_secondary}':"
        f"text='{ffmpeg_escape(footer)}':"
        f"fontsize={fs_footer}:"
        "fontcolor=white@0.9:"
        "borderw=3:bordercolor=black@0.6:"
        f"x=(w-text_w)/2:"
        f"y=h*0.92:"
        f"enable='between(t,0,{total})'"
    )

    video_filter = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=cover,"
        f"crop={W}:{H},boxblur=18:1,format=yuv420p,"
        + ",".join(draw)
        + "[v]"
    )
    audio_filter = "[1:a]volume=1.0[a]"
    filter_complex = video_filter + ";" + audio_filter

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(bg_path), "-i", str(voice_audio)]
    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{total:.3f}",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out_path),
    ]
    _run(cmd)
    return total


def render_long_video(
    repo_root: Path,
    questions: List[QuestionItem],
    voice_profile: Dict[str, Any],
    out_path: Path,
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
    rng: random.Random,
) -> LongRenderResult:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cache_tts = repo_root / ".cache" / "tts"
    seg_dir = out_path.parent / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    cfg_long = cfg_base["rendering"]["long"]

    segments: List[Path] = []
    total = 0.0

    for idx, item in enumerate(questions):
        # Background per segment
        bg = pick_background(
            repo_root=repo_root,
            topic=item.topic,
            cfg_state=cfg_state,
            width=int(cfg_long["width"]),
            height=int(cfg_long["height"]),
            rng=rng,
        )

        voice_path = seg_dir / f"tts_{idx:03d}.mp3"
        voice_text = item.question_text.replace("\n", " ")
        dur = synthesize_tts(voice_text, voice_profile, voice_path, cache_dir=cache_tts)

        seg_path = seg_dir / f"seg_{idx:03d}.mp4"
        seg_dur = _render_segment(
            item=item,
            voice_audio=voice_path,
            voice_duration_s=dur,
            bg_path=bg.path,
            out_path=seg_path,
            cfg_long=cfg_long,
            rng=rng,
        )
        segments.append(seg_path)
        total += seg_dur

    # Concat
    concat_list = seg_dir / "concat.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"file '{s.as_posix()}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    _run(cmd)

    return LongRenderResult(video_path=out_path, duration_s=total, segments=segments)

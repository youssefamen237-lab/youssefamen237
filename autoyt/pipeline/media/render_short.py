\
from __future__ import annotations

import math
import os
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from autoyt.pipeline.content.question_bank import QuestionItem
from autoyt.pipeline.media.backgrounds import BackgroundAsset
from autoyt.pipeline.media.music import MusicAsset
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.text import ffmpeg_escape, wrap_text

log = get_logger("autoyt.render_short")


@dataclass
class RenderResult:
    video_path: Path
    duration_s: float
    used_music: bool
    background_id: str
    music_id: Optional[str]


def _run(cmd: list[str]) -> None:
    log.debug("Running ffmpeg: " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _build_question_text(item: QuestionItem) -> str:
    txt = item.question_text.strip()
    if item.options and item.template_id in {"mc_capital", "which_continent"}:
        # add A/B/C options in text block
        labels = ["A", "B", "C", "D"]
        opts = []
        for i, opt in enumerate(item.options):
            lab = labels[i] if i < len(labels) else str(i + 1)
            opts.append(f"{lab}) {opt}")
        txt = txt + "\n\n" + "\n".join(opts)
    return txt


def render_short(
    item: QuestionItem,
    voice_audio: Path,
    voice_duration_s: float,
    bg: BackgroundAsset,
    music: Optional[MusicAsset],
    out_path: Path,
    cfg_base: Dict[str, Any],
    rng: random.Random,
) -> RenderResult:
    ensure = out_path.parent
    ensure.mkdir(parents=True, exist_ok=True)

    r_cfg = cfg_base["rendering"]["shorts"]
    W = int(r_cfg["width"])
    H = int(r_cfg["height"])
    fps = int(r_cfg.get("fps", 30))
    timer_s = int(r_cfg.get("timer_seconds", 3))
    ans_min = float(r_cfg.get("answer_seconds_min", 1.0))
    ans_max = float(r_cfg.get("answer_seconds_max", 1.8))
    font_main = str(r_cfg.get("font_main"))
    font_secondary = str(r_cfg.get("font_secondary"))

    # Font sizes tuned for 1080x1920
    fs_q = 68
    fs_a = 96
    fs_timer = 120
    fs_cta = 44

    if item.template_id == "match_prediction":
        # Two-stage: prediction + end "VS" screen
        seg1 = max(6.0, voice_duration_s + 0.2)
        seg2 = 3.2
        total = seg1 + seg2
        q_text = wrap_text(_build_question_text(item), max_chars=30)
        # Build end screen text from meta if present
        home = (item.meta or {}).get("home") or ""
        away = (item.meta or {}).get("away") or ""
        md = (item.meta or {}).get("match_date") or ""
        vs_text = f"{home}\nVS\n{away}\n{md}".strip()
        vs_text = wrap_text(vs_text, max_chars=22)

        draw = []
        # background dark overlay
        draw.append(f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.28:t=fill")
        # prediction text
        draw.append(
            "drawtext="
            f"fontfile='{font_main}':"
            f"text='{ffmpeg_escape(q_text)}':"
            f"fontsize={fs_q}:"
            "fontcolor=white:"
            "borderw=4:bordercolor=black@0.65:"
            f"x=(w-text_w)/2:"
            f"y=h*0.22:"
            f"line_spacing=10:"
            f"enable='between(t,0,{seg1})'"
        )
        # end screen
        draw.append(
            "drawtext="
            f"fontfile='{font_main}':"
            f"text='{ffmpeg_escape(vs_text)}':"
            f"fontsize={fs_a}:"
            "fontcolor=white:"
            "borderw=4:bordercolor=black@0.7:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)/2:"
            f"line_spacing=12:"
            f"enable='between(t,{seg1},{total})'"
        )

        video_filter = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=cover,"
            f"crop={W}:{H},boxblur=20:1,format=yuv420p,"
            + ",".join(draw)
            + "[v]"
        )
        # audio
        filter_parts = [video_filter]
        if music:
            audio_filter = (
                f"[1:a]volume=1.0[a_voice];"
                f"[2:a]volume=0.12,afade=t=in:st=0:d=0.4,afade=t=out:st={max(0.0,total-0.4)}:d=0.4[a_music];"
                f"[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2[a]"
            )
        else:
            audio_filter = "[1:a]volume=1.0[a]"
        filter_parts.append(audio_filter)
        filter_complex = ";".join(filter_parts)

        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(bg.path), "-i", str(voice_audio)]
        if music:
            cmd += ["-stream_loop", "-1", "-i", str(music.path)]
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
        return RenderResult(
            video_path=out_path,
            duration_s=total,
            used_music=bool(music),
            background_id=bg.asset_id,
            music_id=music.asset_id if music else None,
        )

    # Q/A short
    answer_s = float(rng.uniform(ans_min, ans_max))
    t_voice_end = float(max(0.1, voice_duration_s))
    t_timer_start = t_voice_end
    t_timer_end = t_timer_start + timer_s
    t_answer_end = t_timer_end + answer_s
    total = t_answer_end

    q_text = wrap_text(_build_question_text(item), max_chars=30)
    a_text = wrap_text(item.answer_text.strip(), max_chars=22)

    # CTA: keep small, rotate outside of render if needed
    # We'll pull CTA from the question text itself only for match/discussion;
    # for normal Q/A, add a simple CTA line at bottom.
    cta = rng.choice(cfg_base["cta"]["shorts"])
    if item.template_id == "would_you_rather":
        cta = rng.choice(cfg_base["cta"]["discussion"])

    draw = []
    draw.append(f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.25:t=fill")

    # Question
    draw.append(
        "drawtext="
        f"fontfile='{font_main}':"
        f"text='{ffmpeg_escape(q_text)}':"
        f"fontsize={fs_q}:"
        "fontcolor=white:"
        "borderw=4:bordercolor=black@0.65:"
        f"x=(w-text_w)/2:"
        f"y=h*0.18:"
        f"line_spacing=12:"
        f"enable='between(t,0,{t_timer_end})'"
    )

    # CTA bottom
    draw.append(
        "drawtext="
        f"fontfile='{font_secondary}':"
        f"text='{ffmpeg_escape(cta)}':"
        f"fontsize={fs_cta}:"
        "fontcolor=white@0.95:"
        "borderw=3:bordercolor=black@0.6:"
        f"x=(w-text_w)/2:"
        f"y=h*0.86:"
        f"enable='between(t,{max(0.0, t_timer_start-0.3)},{t_timer_end})'"
    )

    # Timer digits (3..1)
    # If timer_s != 3, we still show countdown from timer_s to 1
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
            f"y=h*0.70:"
            f"enable='between(t,{start},{end})'"
        )

    # Answer reveal (no voice)
    draw.append(
        "drawtext="
        f"fontfile='{font_main}':"
        f"text='{ffmpeg_escape(a_text)}':"
        f"fontsize={fs_a}:"
        "fontcolor=white:"
        "borderw=5:bordercolor=black@0.75:"
        f"x=(w-text_w)/2:"
        f"y=(h-text_h)/2:"
        f"line_spacing=12:"
        f"enable='between(t,{t_timer_end},{t_answer_end})'"
    )

    video_filter = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=cover,"
        f"crop={W}:{H},boxblur=20:1,format=yuv420p,"
        + ",".join(draw)
        + "[v]"
    )
    filter_parts = [video_filter]
    if music:
        audio_filter = (
            f"[1:a]volume=1.0[a_voice];"
            f"[2:a]volume=0.12,afade=t=in:st=0:d=0.4,afade=t=out:st={max(0.0,total-0.4)}:d=0.4[a_music];"
            f"[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2[a]"
        )
    else:
        audio_filter = "[1:a]volume=1.0[a]"
    filter_parts.append(audio_filter)
    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(bg.path), "-i", str(voice_audio)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music.path)]
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

    return RenderResult(
        video_path=out_path,
        duration_s=total,
        used_music=bool(music),
        background_id=bg.asset_id,
        music_id=music.asset_id if music else None,
    )

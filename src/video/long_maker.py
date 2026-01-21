from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..generators.types import QuizItem
from ..utils.ffmpeg import run as ffmpeg_run, which as which_bin
from ..utils.text import ffmpeg_escape_text, clamp_text
from .short_maker import _find_font  # reuse font finder
from .background_prep import prepare_blurred_background

log = logging.getLogger("long_maker")


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def render_long(
    cfg: Dict[str, Any],
    *,
    items: List[QuizItem],
    voice_audios: List[Path],
    background_images: List[Path],
    music_audio: Optional[Path],
    out_path: str | Path,
    work_dir: str | Path,
) -> Path:
    if len(items) != len(voice_audios) or len(items) != len(background_images):
        raise ValueError("items, voice_audios, background_images length mismatch")

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    w = int(cfg["content"]["long"]["width"])
    h = int(cfg["content"]["long"]["height"])
    fps = int(cfg["content"]["long"]["fps"])

    q_s = float(cfg["content"]["long"]["question_seconds"])
    a_s = float(cfg["content"]["long"]["answer_seconds"])
    seg_s = q_s + a_s

    blur_sigma = float(cfg["content"]["long"]["blur_sigma"])
    safe_margin = int(cfg["content"]["long"]["safe_margin_px"])
    voice_vol = float(cfg["content"]["long"]["voice_volume"])
    music_vol = float(cfg["content"]["long"]["music_volume"])

    font = _find_font()
    ffmpeg = which_bin("ffmpeg")

    seg_paths: List[Path] = []

    for idx, (item, voice_audio, bg) in enumerate(zip(items, voice_audios, background_images), start=1):
        bg_prepared = work_dir / f"bg_{idx:03d}.jpg"
        prepare_blurred_background(bg, out_path=bg_prepared, width=w, height=h, blur_sigma=blur_sigma)

        seg = work_dir / f"seg_{idx:03d}.mp4"
        q_text = clamp_text(item.question.strip(), 120)
        a_text = clamp_text(item.answer.strip(), 60)
        q_esc = ffmpeg_escape_text(q_text)
        a_esc = ffmpeg_escape_text(a_text)

        vf = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[bg];"
            f"[bg]drawbox=x={safe_margin}:y={int(h*0.20)}:w={w-2*safe_margin}:h={int(h*0.52)}:color=black@0.30:t=fill[boxed];"
            f"[boxed]drawtext=fontfile='{font}':text='{q_esc}':x=(w-text_w)/2:y={int(h*0.30)}:"
            f"fontsize={int(h*0.06)}:fontcolor=white:borderw=3:bordercolor=black:line_spacing=10:"
            f"enable='lt(t,{q_s:.2f})'[qtxt];"
            f"[qtxt]drawtext=fontfile='{font}':text='{a_esc}':x=(w-text_w)/2:y={int(h*0.46)}:"
            f"fontsize={int(h*0.075)}:fontcolor=white:borderw=4:bordercolor=black:"
            f"enable='gte(t,{q_s:.2f})'[vout]"
        )

        af = (
            f"[1:a]atrim=0:{q_s:.2f},asetpts=N/SR/TB,volume={voice_vol:.3f}[va];"
            f"anullsrc=r=44100:cl=stereo,atrim=0:{a_s:.2f}[sil];"
            f"[va][sil]concat=n=2:v=0:a=1[aout]"
        )

        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{seg_s:.2f}",
            "-i",
            str(bg_prepared),
            "-i",
            str(voice_audio),
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
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(seg),
        ]
        ffmpeg_run(cmd)
        seg_paths.append(seg)

    # Concat segments (re-encode for stability)
    list_file = work_dir / f"concat_{_now_ts()}_{random.randint(1000,9999)}.txt"
    list_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in seg_paths]) + "\n", encoding="utf-8")

    concat_path = work_dir / f"concat_voice_{_now_ts()}_{random.randint(1000,9999)}.mp4"
    cmd_concat = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        str(concat_path),
    ]
    ffmpeg_run(cmd_concat)

    if music_audio and Path(music_audio).exists():
        final_cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(concat_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_audio),
            "-filter_complex",
            f"[1:a]volume={music_vol:.3f}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(out),
        ]
        ffmpeg_run(final_cmd)
    else:
        out.write_bytes(concat_path.read_bytes())

    return out

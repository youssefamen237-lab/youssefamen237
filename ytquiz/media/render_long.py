from __future__ import annotations

import math
import random
from pathlib import Path

from ytquiz.config import Config
from ytquiz.log import Log
from ytquiz.media.overlays import OverlayPaths, make_long_overlays
from ytquiz.media.render_short import render_short
from ytquiz.media.tts import synthesize_voice
from ytquiz.utils import ensure_dir, run_cmd


def render_long_episode(
    *,
    cfg: Config,
    bg_image: Path,
    questions: list[dict],
    voice_gender: str,
    music_mode: str,
    music_path: Path | None,
    out_mp4: Path,
    rng: random.Random,
    log: Log,
) -> float:
    ensure_dir(out_mp4.parent)
    seg_dir = out_mp4.parent / "segments"
    ensure_dir(seg_dir)

    seg_files: list[Path] = []
    total_dur = 0.0

    qtotal = len(questions)
    for i, q in enumerate(questions, start=1):
        qtext = str(q["question_text"])
        atext = str(q["answer_text"])
        countdown = int(q.get("countdown_seconds") or 10)
        countdown = max(8, min(14, countdown + 3))

        voice_text = qtext
        voice_wav = seg_dir / f"v_{i:03d}.wav"
        synthesize_voice(cfg=cfg, voice_gender=voice_gender, text=voice_text, out_wav=voice_wav, rng=rng, log=log)

        overlays = make_long_overlays(
            out_dir=seg_dir,
            font_file=cfg.overlay_font_file,
            question=qtext,
            answer=atext,
            options=q.get("options"),
            correct_index=q.get("correct_option_index"),
            template_id=1 if q.get("options") is None else 2,
            rng=rng,
            hint_text=q.get("hint_text"),
            qnum=i,
            qtotal=qtotal,
        )

        seg_mp4 = seg_dir / f"seg_{i:03d}.mp4"
        seg_len = _render_long_segment(
            cfg=cfg,
            bg_image=bg_image,
            overlays=overlays,
            voice_wav=voice_wav,
            countdown_seconds=countdown,
            out_mp4=seg_mp4,
            log=log,
        )
        seg_files.append(seg_mp4)
        total_dur += seg_len

    concat_list = seg_dir / "concat.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for p in seg_files:
            f.write(f"file '{p.as_posix()}'\n")

    base_concat = out_mp4.parent / "long_base.mp4"
    run_cmd(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(base_concat)],
        timeout=1800,
        retries=1,
        retry_sleep=2.0,
    )

    if music_mode == "on" and music_path is not None:
        final = out_mp4
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(base_concat),
                "-stream_loop",
                "-1",
                "-i",
                str(music_path),
                "-filter_complex",
                "[1:a]volume=-30dB[m];[m][0:a]sidechaincompress=threshold=0.06:ratio=10:attack=25:release=200[md];[0:a][md]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(final),
            ],
            timeout=1800,
            retries=1,
            retry_sleep=2.0,
        )
    else:
        base_concat.replace(out_mp4)

    try:
        base_concat.unlink(missing_ok=True)
    except Exception:
        pass

    return float(total_dur)


def _render_long_segment(
    *,
    cfg: Config,
    bg_image: Path,
    overlays: OverlayPaths,
    voice_wav: Path,
    countdown_seconds: int,
    out_mp4: Path,
    log: Log,
) -> float:
    original_size = cfg.video_size
    cfg2 = cfg.with_overrides(video_size=(1920, 1080))
    return render_short(
        cfg=cfg2,
        bg_image=bg_image,
        overlays=overlays,
        voice_wav=voice_wav,
        music_path=None,
        countdown_seconds=countdown_seconds,
        out_mp4=out_mp4,
        log=log,
    )

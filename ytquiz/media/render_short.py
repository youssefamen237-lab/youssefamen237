from __future__ import annotations

from pathlib import Path

from ytquiz.config import Config
from ytquiz.log import Log
from ytquiz.media.overlays import OverlayPaths
from ytquiz.utils import run_cmd


def render_short(
    *,
    cfg: Config,
    bg_image: Path,
    overlays: OverlayPaths,
    voice_wav: Path,
    music_path: Path | None,
    countdown_seconds: int,
    out_mp4: Path,
    log: Log,
) -> float:
    answer_seconds = float(cfg.answer_reveal_seconds)
    total = float(countdown_seconds) + answer_seconds
    total = max(total, 6.0)

    vw, vh = cfg.video_size
    font = str(cfg.ffmpeg_font_file)

    timer_fontsize = int(max(56, min(vw, vh) * 0.12))
    timer_y = 0.82 if vh >= vw else 0.78

    timer_expr = f"%{{eif\\:max(0\\,ceil({countdown_seconds}-t))\\:d}}"
    draw_timer = (
        "drawtext="
        f"fontfile={font}:"
        f"text='{timer_expr}':"
        "x=(w-text_w)/2:"
        f"y=h*{timer_y}:"
        f"fontsize={timer_fontsize}:"
        "fontcolor=white:borderw=6:bordercolor=black:"
        f"enable='between(t,0,{countdown_seconds})'"
    )

    inputs: list[str] = []
    inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(bg_image)]
    inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(overlays.question_png)]

    input_idx = 2
    hint_enabled = overlays.hint_png is not None
    if hint_enabled:
        inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(overlays.hint_png)]
        input_idx += 1

    inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(overlays.answer_png)]
    answer_in = input_idx
    voice_in = input_idx + 1

    inputs += ["-i", str(voice_wav)]

    music_in = None
    if music_path is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        music_in = voice_in + 1

    v_parts: list[str] = []
    v_parts.append(f"[0:v]scale={vw}:{vh},setsar=1,boxblur=20:1,format=rgba[bg]")
    v_parts.append(f"[bg][1:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{countdown_seconds})'[v1]")
    v_parts.append(f"[v1]{draw_timer}[v2]")

    v_cur = "v2"

    if hint_enabled:
        hint_in = 2
        hint_start = max(1.0, float(countdown_seconds) * 0.45)
        hint_end = float(countdown_seconds)
        v_parts.append(f"[{v_cur}][{hint_in}:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,{hint_start:.3f},{hint_end:.3f})'[v3]")
        v_cur = "v3"

    v_parts.append(
        f"[{v_cur}][{answer_in}:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,{countdown_seconds},{total})'[vout]"
    )

    a_parts: list[str] = []
    a_parts.append(f"[{voice_in}:a]aresample=44100,volume=1.1[voice]")
    if music_in is None:
        a_parts.append("[voice]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[aout]")
    else:
        a_parts.append(f"[{music_in}:a]aresample=44100,volume=-30dB[music]")
        a_parts.append("[music][voice]sidechaincompress=threshold=0.06:ratio=10:attack=25:release=200[ducked]")
        a_parts.append("[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0[aout]")

    filter_complex = ";".join(v_parts + a_parts)

    cmd = ["ffmpeg", "-y"]
    cmd += inputs
    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-t",
        f"{total:.3f}",
        "-r",
        str(cfg.fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(cfg.crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out_mp4),
    ]

    run_cmd(cmd, timeout=900, retries=1, retry_sleep=2.0)
    return float(total)

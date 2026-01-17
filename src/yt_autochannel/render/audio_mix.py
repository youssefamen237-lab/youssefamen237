from __future__ import annotations

from pathlib import Path

from ..utils.subprocesses import run_cmd


def mix_voice_and_music(
    voice_path: Path,
    music_path: Path,
    out_path: Path,
    total_duration_s: float,
    music_target_db: float,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = max(0.1, float(total_duration_s))

    # volume in dB; ffmpeg volume filter accepts "XdB".
    mvol = f"{music_target_db}dB"

    # Input 0: voice. Input 1: music (looped).
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(voice_path),
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-filter_complex",
        (
            f"[0:a]apad,atrim=0:{total},asetpts=N/SR/TB[voice];"
            f"[1:a]atrim=0:{total},volume={mvol},asetpts=N/SR/TB[music];"
            f"[music][voice]sidechaincompress=threshold=0.03:ratio=10:attack=10:release=250[duck];"
            f"[duck][voice]amix=inputs=2:duration=first:dropout_transition=0[outa]"
        ),
        "-map",
        "[outa]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]
    run_cmd(cmd, timeout=180, check=True)

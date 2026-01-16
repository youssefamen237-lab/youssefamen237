from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from ytquiz.config import Config
from ytquiz.log import Log
from ytquiz.utils import ensure_dir, run_cmd


def ensure_piper_voice(voice_name: str, data_dir: Path, log: Log) -> Path:
    ensure_dir(data_dir)
    model_path = data_dir / f"{voice_name}.onnx"
    cfg_path = data_dir / f"{voice_name}.onnx.json"
    if model_path.exists() and cfg_path.exists():
        return model_path

    log.info(f"Downloading Piper voice: {voice_name}")
    run_cmd(
        [sys.executable, "-m", "piper.download_voices", "--data-dir", str(data_dir), voice_name],
        timeout=600,
        retries=1,
        retry_sleep=2.0,
    )
    if not model_path.exists():
        candidates = list(data_dir.rglob("*.onnx"))
        for c in candidates:
            if c.name.startswith(voice_name) and c.suffix == ".onnx":
                model_path = c
                break
    return model_path


def synthesize_voice(*, cfg: Config, voice_gender: str, text: str, out_wav: Path, rng: random.Random, log: Log) -> None:
    ensure_dir(out_wav.parent)
    voice_name = cfg.piper_voice_female if voice_gender == "female" else cfg.piper_voice_male
    model_path = ensure_piper_voice(voice_name, cfg.piper_data_dir, log)

    tmp = out_wav.with_suffix(".tmp.wav")

    try:
        _run_piper(text=text, model_path=model_path, data_dir=cfg.piper_data_dir, out_wav=tmp, log=log)
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(tmp),
                "-ar",
                "44100",
                "-ac",
                "1",
                "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5",
                str(out_wav),
            ],
            timeout=120,
            retries=1,
            retry_sleep=1.0,
        )
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return
    except Exception as e:
        log.warn(f"Piper TTS failed ({voice_name}): {e}")

    if _run_espeak(text=text, out_wav=out_wav, log=log):
        return

    raise RuntimeError("All TTS methods failed")


def _run_piper(*, text: str, model_path: Path, data_dir: Path, out_wav: Path, log: Log) -> None:
    cmd = [
        sys.executable,
        "-m",
        "piper",
        "--data-dir",
        str(data_dir),
        "-m",
        str(model_path),
        "-f",
        str(out_wav),
        "--",
        text,
    ]
    run_cmd(cmd, timeout=180, retries=0, retry_sleep=1.0)


def _run_espeak(*, text: str, out_wav: Path, log: Log) -> bool:
    try:
        cmd = ["espeak", "-v", "en-us", "-s", "155", "-w", str(out_wav), text]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True, timeout=60)
        return True
    except Exception:
        return False

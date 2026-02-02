from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import TTSEngine, TTSError, TTSResult


class Festival(TTSEngine):
    name = "festival"

    def available(self) -> bool:
        return shutil.which("text2wave") is not None

    def synthesize(self, text: str, out_wav: Path) -> TTSResult:
        exe = shutil.which("text2wave")
        if not exe:
            raise TTSError("text2wave not found")
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
            txt_path = f.name
        cmd = [exe, txt_path, "-o", str(out_wav)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not out_wav.exists():
            raise TTSError(f"festival text2wave failed: {(p.stderr or p.stdout).strip()}")
        return TTSResult(wav_path=out_wav, engine=self.name)

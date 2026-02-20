import subprocess
from pathlib import Path

from core.config import CONFIG


class VideoEngine:
    def _run(self, cmd: list[str]) -> None:
        subprocess.run(cmd, check=True)

    def build_short(self, background: Path, question: str, cta: str, answer: str, question_audio: Path, cta_audio: Path) -> Path:
        out = CONFIG.output_dir / "short.mp4"
        text = f"{question}\\n\\n{cta}"
        answer_text = f"Answer: {answer}"
        self._run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(background),
                "-i",
                str(question_audio),
                "-i",
                str(cta_audio),
                "-filter_complex",
                (
                    "[1:a][2:a]concat=n=2:v=0:a=1[aud];"
                    f"[0:v]drawtext=text='{text}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=15:box=1:boxcolor=black@0.45:boxborderw=20,"
                    "drawtext=text='5...4...3...2...1':enable='between(t,2,7)':fontcolor=yellow:fontsize=70:x=(w-text_w)/2:y=h*0.78,"
                    f"drawtext=text='{answer_text}':enable='between(t,7,8.2)':fontcolor=lime:fontsize=64:x=(w-text_w)/2:y=h*0.65[v]"
                ),
                "-map",
                "[v]",
                "-map",
                "[aud]",
                "-t",
                "8.2",
                "-r",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ]
        )
        return out

    def build_long(self, background: Path, slides_file: Path, narration: Path) -> Path:
        out = CONFIG.output_dir / "long.mp4"
        self._run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(background),
                "-i",
                str(narration),
                "-vf",
                f"drawtext=textfile='{slides_file}':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:boxborderw=18",
                "-shortest",
                "-r",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ]
        )
        return out

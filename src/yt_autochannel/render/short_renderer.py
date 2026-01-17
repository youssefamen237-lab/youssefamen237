from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..providers.tts_chain import TTSChain
from ..utils.media_utils import get_audio_duration_s
from ..utils.subprocesses import run_cmd
from ..utils.text_utils import sanitize_text, wrap_lines
from .audio_mix import mix_voice_and_music


@dataclass
class ShortRenderSpec:
    template_id: str
    question: str
    answer: str
    choices: Optional[List[str]]
    correct_index: Optional[int]
    countdown_seconds: int
    answer_seconds: float
    bg_path: Path
    font_path: str
    fps: int
    resolution: str  # e.g. "1080x1920"
    brand_primary: str
    brand_secondary: str
    brand_accent: str
    music_enabled: bool
    music_path: Optional[Path]
    music_target_db: float
    tts_chain: TTSChain
    tts_voice: str
    output_path: Path


def _ff_escape_text(s: str) -> str:
    """Escape text for ffmpeg drawtext (passed as an argument, not through a shell)."""
    s = sanitize_text(s)
    s = s.replace('\\', r'\\\\')
    s = s.replace(':', r'\\:')
    s = s.replace("'", r"\\'")
    s = s.replace('\n', r'\\n')
    return s


def _tts_text(spec: ShortRenderSpec) -> str:
    q = sanitize_text(spec.question)
    if spec.choices:
        opts = [sanitize_text(x) for x in spec.choices]
        letters = ['A', 'B', 'C', 'D']
        parts = [q]
        for i, opt in enumerate(opts[:3]):
            parts.append(f"{letters[i]}. {opt}")
        return ' '.join(parts)
    return q


def render_short(spec: ShortRenderSpec) -> None:
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='yt_short_') as td:
        td_path = Path(td)
        voice_audio = td_path / 'voice.mp3'

        tts_text = _tts_text(spec)
        spec.tts_chain.synthesize(tts_text, voice=spec.tts_voice, out_path=voice_audio)
        voice_dur = max(0.05, float(get_audio_duration_s(voice_audio)))

        total_dur = float(voice_dur) + float(spec.countdown_seconds) + float(spec.answer_seconds)

        final_audio = voice_audio
        if spec.music_enabled and spec.music_path and spec.music_path.exists():
            mixed = td_path / 'mix.mp3'
            mix_voice_and_music(
                voice_path=voice_audio,
                music_path=spec.music_path,
                out_path=mixed,
                music_target_db=spec.music_target_db,
            )
            final_audio = mixed

        # Layout params
        w, h = spec.resolution.split('x')
        w = int(w)
        h = int(h)

        box_w = int(w * 0.90)
        box_h = int(h * 0.55)
        box_x = int((w - box_w) / 2)
        box_y = int(h * 0.18)

        q_text = wrap_lines(spec.question, width=32)
        a_text = wrap_lines(spec.answer, width=32)

        if spec.template_id == 'multiple_choice' and spec.choices:
            letters = ['A', 'B', 'C', 'D']
            opts = [sanitize_text(x) for x in spec.choices][:3]
            opt_lines = [f"{letters[i]}) {opts[i]}" for i in range(len(opts))]
            q_text = wrap_lines(spec.question, width=32) + "\n\n" + "\n".join(opt_lines)
            if spec.correct_index is not None and 0 <= int(spec.correct_index) < len(opts):
                a_text = f"Answer: {letters[int(spec.correct_index)]}) {opts[int(spec.correct_index)]}"

        q_text_esc = _ff_escape_text(q_text)
        a_text_esc = _ff_escape_text(a_text)

        # Times
        q_end = voice_dur + float(spec.countdown_seconds)
        a_start = voice_dur + float(spec.countdown_seconds)
        a_end = a_start + float(spec.answer_seconds)

        # Background: always blurred; zoom_reveal cross-fades blur->sharp near answer.
        base = f"scale={w}:{h}:force_original_aspect_ratio=cover,crop={w}:{h},format=rgba,setsar=1"
        blur = "boxblur=12:1"

        filters = []
        filters.append(base)

        if spec.template_id == 'zoom_reveal':
            # Use xfade between blurred and sharp starting 1s before answer.
            offset = max(0.0, a_start - 1.0)
            filters = [
                f"[0:v]{base},split=2[base1][base2]",
                f"[base1]{blur}[b]",
                f"[b][base2]xfade=transition=fade:duration=1:offset={offset}[bg]",
            ]
            bg_label = "[bg]"
            filter_prefix = ";".join(filters)
            # Start composing from [bg]
            chain = bg_label
        else:
            filter_prefix = f"{base},{blur}"
            chain = "[v]"

        # Text overlay and box
        fontsize_q = int(h * 0.055)
        fontsize_a = int(h * 0.060)
        fontsize_cd = int(h * 0.100)

        draw = []
        draw.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.55:t=fill"
        )
        # Question
        draw.append(
            "drawtext="
            f"fontfile={spec.font_path}:"
            f"text='{q_text_esc}':"
            f"fontsize={fontsize_q}:"
            f"fontcolor={spec.brand_primary}:"
            f"x=(w-text_w)/2:"
            f"y={box_y + int(box_h*0.12)}:"
            f"line_spacing=10:"
            f"enable='lt(t,{q_end})'"
        )
        # Countdown numbers (3..1) after voice ends
        for i in range(spec.countdown_seconds):
            num = spec.countdown_seconds - i
            st = voice_dur + float(i)
            en = st + 1.0
            draw.append(
                "drawtext="
                f"fontfile={spec.font_path}:"
                f"text='{num}':"
                f"fontsize={fontsize_cd}:"
                f"fontcolor={spec.brand_accent}:"
                f"x=(w-text_w)/2:"
                f"y={box_y + int(box_h*0.72)}:"
                f"enable='between(t,{st},{en})'"
            )
        # Answer
        draw.append(
            "drawtext="
            f"fontfile={spec.font_path}:"
            f"text='{a_text_esc}':"
            f"fontsize={fontsize_a}:"
            f"fontcolor={spec.brand_secondary}:"
            f"x=(w-text_w)/2:"
            f"y={box_y + int(box_h*0.40)}:"
            f"line_spacing=10:"
            f"enable='between(t,{a_start},{a_end})'"
        )

        draw_chain = ",".join(draw)

        # Fade in/out
        fade_d = 0.20
        fade_out_st = max(0.0, total_dur - fade_d)
        fade_chain = f"fade=t=in:st=0:d={fade_d},fade=t=out:st={fade_out_st}:d={fade_d}"

        if spec.template_id == 'zoom_reveal':
            # Full filter_complex with labels
            fc = f"{filter_prefix};{chain}{draw_chain},{fade_chain}[vout]"
            vf_args = ["-filter_complex", fc, "-map", "[vout]", "-map", "1:a"]
        else:
            vf = f"{filter_prefix},{draw_chain},{fade_chain}"
            vf_args = ["-vf", vf]

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-t",
            f"{total_dur}",
            "-i",
            str(spec.bg_path),
            "-i",
            str(final_audio),
        ]
        cmd.extend(vf_args)
        cmd.extend([
            "-r",
            str(spec.fps),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(spec.output_path),
        ])

        run_cmd(cmd, timeout=300, check=True)

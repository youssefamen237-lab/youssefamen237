from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..providers.tts_chain import TTSChain
from ..utils.media_utils import get_audio_duration_s
from ..utils.subprocesses import run_cmd
from ..utils.text_utils import sanitize_text, wrap_lines
from .audio_mix import mix_voice_and_music


@dataclass
class LongEpisodeSpec:
    title: str
    qas: List[Any]  # list of dicts with keys like q/a/topic
    bg_path: Path
    font_path: str
    fps: int
    resolution: str  # e.g. "1920x1080"
    brand_primary: str
    brand_secondary: str
    brand_accent: str
    music_enabled: bool
    music_path: Optional[Path]
    music_target_db: float
    tts_chain: TTSChain
    tts_voice: str
    output_path: Path
    countdown_seconds: int = 3
    answer_seconds: float = 1.0
    intro_seconds: float = 5.0
    recap_seconds: float = 60.0
    outro_seconds: float = 5.0


def _ff_escape_text(s: str) -> str:
    s = sanitize_text(s)
    s = s.replace('\\', r'\\\\')
    s = s.replace(':', r'\\:')
    s = s.replace("'", r"\\'")
    s = s.replace('\n', r'\\n')
    return s


def _qa_fields(item: Any) -> Dict[str, str]:
    if isinstance(item, dict):
        q = item.get('q') or item.get('question') or ''
        a = item.get('a') or item.get('answer') or ''
        t = item.get('topic') or ''
        return {'q': sanitize_text(str(q)), 'a': sanitize_text(str(a)), 'topic': sanitize_text(str(t))}
    return {'q': sanitize_text(str(item)), 'a': '', 'topic': ''}


def _music_for_duration(music_path: Path, duration_s: float, out_path: Path, target_db: float) -> None:
    # Use -stream_loop to loop music, trim to duration, and set volume.
    # Convert dBFS-ish target into linear gain relative to music as provided.
    # We keep it conservative (ducking is handled elsewhere when voice exists).
    vol = 0.06 if target_db <= -28 else 0.08
    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1',
        '-i', str(music_path),
        '-t', f'{duration_s}',
        '-filter:a', f'volume={vol}',
        '-c:a', 'aac',
        '-b:a', '128k',
        str(out_path),
    ]
    run_cmd(cmd, timeout=120, check=True)


def _render_segment(
    bg_path: Path,
    audio_path: Path,
    out_path: Path,
    resolution: str,
    fps: int,
    font_path: str,
    primary: str,
    secondary: str,
    accent: str,
    question: str,
    answer: str,
    voice_dur: float,
    countdown_seconds: int,
    answer_seconds: float,
    idx: Optional[int] = None,
    total: Optional[int] = None,
    title_bar: bool = True,
) -> None:
    w_s, h_s = resolution.split('x')
    w = int(w_s)
    h = int(h_s)

    total_dur = float(voice_dur) + float(countdown_seconds) + float(answer_seconds)
    q_end = voice_dur + float(countdown_seconds)
    a_start = voice_dur + float(countdown_seconds)
    a_end = a_start + float(answer_seconds)

    # Layout: center box
    box_w = int(w * 0.86)
    box_h = int(h * 0.56)
    box_x = int((w - box_w) / 2)
    box_y = int(h * 0.18)

    q_text = wrap_lines(question, width=44)
    a_text = wrap_lines(answer, width=44)

    q_esc = _ff_escape_text(q_text)
    a_esc = _ff_escape_text(a_text)

    fontsize_q = int(h * 0.055)
    fontsize_a = int(h * 0.060)
    fontsize_cd = int(h * 0.095)
    fontsize_bar = int(h * 0.040)

    base = f"scale={w}:{h}:force_original_aspect_ratio=cover,crop={w}:{h},format=rgba,setsar=1,boxblur=10:1"

    draw = []
    draw.append(f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.55:t=fill")

    if title_bar and idx is not None and total is not None and total > 0:
        bar = f"Question {idx}/{total}"
        draw.append(
            "drawtext="
            f"fontfile={font_path}:"
            f"text='{_ff_escape_text(bar)}':"
            f"fontsize={fontsize_bar}:"
            f"fontcolor={accent}:"
            f"x={int(w*0.05)}:"
            f"y={int(h*0.06)}"
        )

    # Question
    draw.append(
        "drawtext="
        f"fontfile={font_path}:"
        f"text='{q_esc}':"
        f"fontsize={fontsize_q}:"
        f"fontcolor={primary}:"
        f"x=(w-text_w)/2:"
        f"y={box_y + int(box_h*0.14)}:"
        f"line_spacing=10:"
        f"enable='lt(t,{q_end})'"
    )

    # Countdown
    for i in range(int(countdown_seconds)):
        num = int(countdown_seconds) - i
        st = voice_dur + float(i)
        en = st + 1.0
        draw.append(
            "drawtext="
            f"fontfile={font_path}:"
            f"text='{num}':"
            f"fontsize={fontsize_cd}:"
            f"fontcolor={accent}:"
            f"x=(w-text_w)/2:"
            f"y={box_y + int(box_h*0.72)}:"
            f"enable='between(t,{st},{en})'"
        )

    # Answer
    draw.append(
        "drawtext="
        f"fontfile={font_path}:"
        f"text='{a_esc}':"
        f"fontsize={fontsize_a}:"
        f"fontcolor={secondary}:"
        f"x=(w-text_w)/2:"
        f"y={box_y + int(box_h*0.42)}:"
        f"line_spacing=10:"
        f"enable='between(t,{a_start},{a_end})'"
    )

    fade_d = 0.25
    fade_out_st = max(0.0, total_dur - fade_d)
    vf = f"{base},{','.join(draw)},fade=t=in:st=0:d={fade_d},fade=t=out:st={fade_out_st}:d={fade_d}"

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1',
        '-t', f'{total_dur}',
        '-i', str(bg_path),
        '-i', str(audio_path),
        '-vf', vf,
        '-r', str(fps),
        '-shortest',
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '160k',
        str(out_path),
    ]
    run_cmd(cmd, timeout=400, check=True)


def _concat_mp4(parts: List[Path], out_path: Path) -> None:
    # Use concat demuxer (safe if codecs match)
    list_file = out_path.parent / (out_path.stem + '_concat.txt')
    lines = [f"file '{p.as_posix()}'" for p in parts]
    list_file.write_text("\n".join(lines), encoding='utf-8')
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', str(list_file),
        '-c', 'copy',
        str(out_path),
    ]
    run_cmd(cmd, timeout=600, check=True)


def render_long_episode(spec: LongEpisodeSpec) -> None:
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='yt_long_') as td:
        td_path = Path(td)

        # Normalize QA list
        qas = [_qa_fields(it) for it in (spec.qas or [])]
        qas = [q for q in qas if q['q'] and q['a']]
        if not qas:
            qas = [{'q': 'What is 5 + 6?', 'a': '11', 'topic': 'Math'}]

        parts: List[Path] = []

        # Intro (no voice)
        intro_audio = td_path / 'intro_audio.m4a'
        if spec.music_enabled and spec.music_path and spec.music_path.exists():
            _music_for_duration(spec.music_path, float(spec.intro_seconds), intro_audio, spec.music_target_db)
        else:
            # silent
            cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo', '-t', f'{spec.intro_seconds}', '-c:a', 'aac', str(intro_audio)]
            run_cmd(cmd, timeout=60, check=True)

        intro_q = sanitize_text(spec.title)
        intro_a = 'Get ready! Answer before the timer ends.'
        intro_part = td_path / 'intro.mp4'
        _render_segment(
            bg_path=spec.bg_path,
            audio_path=intro_audio,
            out_path=intro_part,
            resolution=spec.resolution,
            fps=spec.fps,
            font_path=spec.font_path,
            primary=spec.brand_primary,
            secondary=spec.brand_secondary,
            accent=spec.brand_accent,
            question=intro_q,
            answer=intro_a,
            voice_dur=max(0.05, float(spec.intro_seconds) - float(spec.countdown_seconds) - float(spec.answer_seconds)),
            countdown_seconds=int(spec.countdown_seconds),
            answer_seconds=float(spec.answer_seconds),
            idx=None,
            total=None,
            title_bar=False,
        )
        parts.append(intro_part)

        # Question segments
        total_q = len(qas)
        for i, qa in enumerate(qas, start=1):
            voice_audio = td_path / f'v_{i:03d}.mp3'
            spec.tts_chain.synthesize(qa['q'], voice=spec.tts_voice, out_path=voice_audio)
            voice_dur = max(0.05, float(get_audio_duration_s(voice_audio)))

            seg_audio = voice_audio
            if spec.music_enabled and spec.music_path and spec.music_path.exists():
                mixed = td_path / f'mix_{i:03d}.mp3'
                mix_voice_and_music(voice_path=voice_audio, music_path=spec.music_path, out_path=mixed, music_target_db=spec.music_target_db)
                seg_audio = mixed

            seg_out = td_path / f'q_{i:03d}.mp4'
            _render_segment(
                bg_path=spec.bg_path,
                audio_path=seg_audio,
                out_path=seg_out,
                resolution=spec.resolution,
                fps=spec.fps,
                font_path=spec.font_path,
                primary=spec.brand_primary,
                secondary=spec.brand_secondary,
                accent=spec.brand_accent,
                question=qa['q'],
                answer=qa['a'],
                voice_dur=voice_dur,
                countdown_seconds=int(spec.countdown_seconds),
                answer_seconds=float(spec.answer_seconds),
                idx=i,
                total=total_q,
                title_bar=True,
            )
            parts.append(seg_out)

        # Recap segment (no voice)
        recap_audio = td_path / 'recap_audio.m4a'
        if spec.music_enabled and spec.music_path and spec.music_path.exists():
            _music_for_duration(spec.music_path, float(spec.recap_seconds), recap_audio, spec.music_target_db)
        else:
            cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo', '-t', f'{spec.recap_seconds}', '-c:a', 'aac', str(recap_audio)]
            run_cmd(cmd, timeout=60, check=True)

        # Build a recap text block
        recap_lines = ['Recap']
        max_lines = 22
        for i, qa in enumerate(qas[:max_lines], start=1):
            recap_lines.append(f"{i}. {qa['a']}")
        recap_q = "\n".join(recap_lines)
        recap_a = 'Thanks for playing. Subscribe for more.'
        recap_part = td_path / 'recap.mp4'
        _render_segment(
            bg_path=spec.bg_path,
            audio_path=recap_audio,
            out_path=recap_part,
            resolution=spec.resolution,
            fps=spec.fps,
            font_path=spec.font_path,
            primary=spec.brand_primary,
            secondary=spec.brand_secondary,
            accent=spec.brand_accent,
            question=recap_q,
            answer=recap_a,
            voice_dur=max(0.05, float(spec.recap_seconds) - float(spec.countdown_seconds) - float(spec.answer_seconds)),
            countdown_seconds=int(spec.countdown_seconds),
            answer_seconds=float(spec.answer_seconds),
            idx=None,
            total=None,
            title_bar=False,
        )
        parts.append(recap_part)


        # Outro segment
        outro_audio = td_path / 'outro_audio.m4a'
        if spec.music_enabled and spec.music_path and spec.music_path.exists():
            _music_for_duration(spec.music_path, float(spec.outro_seconds), outro_audio, spec.music_target_db)
        else:
            cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', f'{spec.outro_seconds}', '-c:a', 'aac', str(outro_audio)]
            run_cmd(cmd, timeout=60, check=True)

        outro_part = td_path / 'outro.mp4'
        outro_q = 'Subscribe for more trivia.'
        outro_a = 'See you next time.'
        _render_segment(
            bg_path=spec.bg_path,
            audio_path=outro_audio,
            out_path=outro_part,
            resolution=spec.resolution,
            fps=spec.fps,
            font_path=spec.font_path,
            primary=spec.brand_primary,
            secondary=spec.brand_secondary,
            accent=spec.brand_accent,
            question=outro_q,
            answer=outro_a,
            voice_dur=max(0.05, float(spec.outro_seconds) - float(spec.countdown_seconds) - float(spec.answer_seconds)),
            countdown_seconds=int(spec.countdown_seconds),
            answer_seconds=float(spec.answer_seconds),
            idx=None,
            total=None,
            title_bar=False,
        )
        parts.append(outro_part)

        _concat_mp4(parts, spec.output_path)

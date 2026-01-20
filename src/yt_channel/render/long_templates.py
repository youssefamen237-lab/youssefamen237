from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from ..providers.manager import ProviderManager
from ..question_bank.generators import QuestionItem
from ..render.ffmpeg import ffprobe_duration, run_ffmpeg
from ..utils.text import ffmpeg_escape_text, wrap_text
from .shorts_templates import BrandKit


def _scale_crop_expr(w: int, h: int) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2,"
        "setsar=1"
    )


def _audio_mix_filter(*, total: float, voice: bool, music_volume_db: float) -> str:
    if voice:
        voice_chain = f"[1:a]apad=pad_dur={total},atrim=0:{total}[voice]"
        music_chain = f"[2:a]volume={music_volume_db}dB[music]"
        duck = "[music][voice]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=200[mduck]"
        mix = f"[mduck][voice]amix=inputs=2:duration=first:dropout_transition=0,atrim=0:{total}[aout]"
        return ";".join([voice_chain, music_chain, duck, mix])

    # music only
    music_chain = f"[1:a]volume={music_volume_db}dB,atrim=0:{total}[aout]"
    return music_chain


def _render_segment(
    *,
    out_path: Path,
    bg_image: Path,
    duration: float,
    vf: str,
    af: str,
    voice_path: Optional[Path],
    music_path: Optional[Path],
    fps: int,
    resolution: Tuple[int, int],
) -> None:
    w, h = resolution
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration}",
        "-i",
        str(bg_image),
    ]

    if voice_path:
        cmd += ["-i", str(voice_path)]
        if music_path:
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    else:
        if music_path:
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]

    cmd += [
        "-filter_complex",
        f"{vf};{af}",
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-r",
        str(fps),
        "-s",
        f"{w}x{h}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(out_path),
    ]

    run_ffmpeg(cmd)


def _question_vf(
    *,
    question_no: int,
    total_questions: int,
    question_text: str,
    answer_text: str,
    tts_duration: float,
    countdown_seconds: int,
    answer_seconds: float,
    brand: BrandKit,
    resolution: Tuple[int, int],
) -> tuple[str, float]:
    w, h = resolution

    q_end = float(tts_duration)
    c_start = q_end
    c_end = q_end + float(countdown_seconds)
    a_start = c_end
    a_end = a_start + float(answer_seconds)
    total = a_end

    q_wrapped = wrap_text(question_text, max_chars=max(34, int(w * 0.045)))
    a_wrapped = wrap_text(answer_text, max_chars=max(30, int(w * 0.045)))

    scoreboard = ffmpeg_escape_text(f"Question {question_no}/{total_questions}")
    q_esc = ffmpeg_escape_text(q_wrapped)
    a_esc = ffmpeg_escape_text(a_wrapped)

    box_x = int(w * 0.10)
    box_w = int(w * 0.80)
    box_y = int(h * 0.22)
    box_h = int(h * 0.56)

    q_y = int(h * 0.32)
    timer_y = int(h * 0.55)
    a_y = int(h * 0.66)

    fs_score = max(28, int(h * 0.045))
    fs_q = max(44, int(h * 0.070))
    fs_timer = max(90, int(h * 0.140))
    fs_a = max(48, int(h * 0.075))

    filters: List[str] = []
    filters.append(f"[0:v]{_scale_crop_expr(w,h)},format=rgba,gblur=sigma=22,fade=t=in:st=0:d=0.35[base]")
    cur = "[base]"

    filters.append(
        f"{cur}drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.58:t=fill[bx]"
    )
    cur = "[bx]"

    filters.append(
        f"{cur}drawtext=fontfile='{brand.font_bold}':text='{scoreboard}':fontcolor={brand.color_accent}:fontsize={fs_score}:x=(w-text_w)/2:y={int(h*0.08)}:shadowcolor=black@0.45:shadowx=2:shadowy=2[s0]"
    )
    cur = "[s0]"

    filters.append(
        f"{cur}drawtext=fontfile='{brand.font_bold}':text='{q_esc}':fontcolor={brand.color_text}:fontsize={fs_q}:x=(w-text_w)/2:y={q_y}:line_spacing=8:shadowcolor=black@0.6:shadowx=3:shadowy=3[q1]"
    )
    cur = "[q1]"

    for i, n in enumerate(range(countdown_seconds, 0, -1)):
        st = c_start + i
        en = min(c_end, st + 1.0)
        filters.append(
            f"{cur}drawtext=fontfile='{brand.font_bold}':text='{n}':fontcolor={brand.color_accent}:fontsize={fs_timer}:x=(w-text_w)/2:y={timer_y}:enable='between(t,{st},{en})':shadowcolor=black@0.55:shadowx=3:shadowy=3[qc{i}]"
        )
        cur = f"[qc{i}]"

    filters.append(
        f"{cur}drawtext=fontfile='{brand.font_bold}':text='Answer: {a_esc}':fontcolor={brand.color_accent}:fontsize={fs_a}:x=(w-text_w)/2:y={a_y}:enable='between(t,{a_start},{a_end})':shadowcolor=black@0.55:shadowx=2:shadowy=2[vout]"
    )

    return ";".join(filters), total


def _title_vf(*, title: str, subtitle: str, brand: BrandKit, resolution: Tuple[int, int]) -> str:
    w, h = resolution
    title_w = wrap_text(title, max_chars=28)
    sub_w = wrap_text(subtitle, max_chars=34)
    t_esc = ffmpeg_escape_text(title_w)
    s_esc = ffmpeg_escape_text(sub_w)

    box_x = int(w * 0.10)
    box_w = int(w * 0.80)
    box_y = int(h * 0.25)
    box_h = int(h * 0.50)

    fs_t = max(64, int(h * 0.12))
    fs_s = max(36, int(h * 0.06))

    vf = (
        f"[0:v]{_scale_crop_expr(w,h)},format=rgba,gblur=sigma=22,fade=t=in:st=0:d=0.5[base]"
        f";[base]drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.62:t=fill[b]"
        f";[b]drawtext=fontfile='{brand.font_bold}':text='{t_esc}':fontcolor={brand.color_text}:fontsize={fs_t}:x=(w-text_w)/2:y={int(h*0.36)}:line_spacing=8:shadowcolor=black@0.6:shadowx=3:shadowy=3[t]"
        f";[t]drawtext=fontfile='{brand.font_regular}':text='{s_esc}':fontcolor={brand.color_accent}:fontsize={fs_s}:x=(w-text_w)/2:y={int(h*0.62)}:shadowcolor=black@0.5:shadowx=2:shadowy=2[vout]"
    )
    return vf


def _section_vf(*, text: str, brand: BrandKit, resolution: Tuple[int, int]) -> str:
    w, h = resolution
    t = ffmpeg_escape_text(wrap_text(text, max_chars=30))
    box_x = int(w * 0.12)
    box_w = int(w * 0.76)
    box_y = int(h * 0.34)
    box_h = int(h * 0.32)
    fs = max(56, int(h * 0.10))
    vf = (
        f"[0:v]{_scale_crop_expr(w,h)},format=rgba,gblur=sigma=22,fade=t=in:st=0:d=0.35[base]"
        f";[base]drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.6:t=fill[b]"
        f";[b]drawtext=fontfile='{brand.font_bold}':text='{t}':fontcolor={brand.color_accent}:fontsize={fs}:x=(w-text_w)/2:y=(h-text_h)/2:shadowcolor=black@0.6:shadowx=3:shadowy=3[vout]"
    )
    return vf


def _recap_vf(*, answers: List[str], brand: BrandKit, resolution: Tuple[int, int]) -> str:
    w, h = resolution
    half = (len(answers) + 1) // 2
    left = answers[:half]
    right = answers[half:]

    left_text = "\n".join(left)
    right_text = "\n".join(right)

    l_esc = ffmpeg_escape_text(left_text)
    r_esc = ffmpeg_escape_text(right_text)

    header = ffmpeg_escape_text("Answer Recap")

    box_x = int(w * 0.06)
    box_w = int(w * 0.88)
    box_y = int(h * 0.10)
    box_h = int(h * 0.80)

    fs_h = max(52, int(h * 0.09))
    fs = max(28, int(h * 0.045))

    x_left = int(w * 0.12)
    x_right = int(w * 0.55)
    y_list = int(h * 0.22)

    vf = (
        f"[0:v]{_scale_crop_expr(w,h)},format=rgba,gblur=sigma=22,fade=t=in:st=0:d=0.4[base]"
        f";[base]drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.62:t=fill[b]"
        f";[b]drawtext=fontfile='{brand.font_bold}':text='{header}':fontcolor={brand.color_accent}:fontsize={fs_h}:x=(w-text_w)/2:y={int(h*0.12)}:shadowcolor=black@0.6:shadowx=3:shadowy=3[h]"
        f";[h]drawtext=fontfile='{brand.font_regular}':text='{l_esc}':fontcolor={brand.color_text}:fontsize={fs}:x={x_left}:y={y_list}:line_spacing=6:shadowcolor=black@0.45:shadowx=2:shadowy=2[l]"
        f";[l]drawtext=fontfile='{brand.font_regular}':text='{r_esc}':fontcolor={brand.color_text}:fontsize={fs}:x={x_right}:y={y_list}:line_spacing=6:shadowcolor=black@0.45:shadowx=2:shadowy=2[vout]"
    )
    return vf


def render_long_episode(
    *,
    out_path: Path,
    bg_image: Path,
    questions: List[QuestionItem],
    providers: ProviderManager,
    voice_gender: str,
    countdown_seconds: int,
    answer_seconds: float,
    fps: int,
    resolution: Tuple[int, int],
    brand: BrandKit,
    music_enabled: bool,
    music_pick,
    music_volume_db: float,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = out_path.parent / f"tmp_{out_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    music_path: Optional[Path] = music_pick.path if (music_enabled and music_pick) else None

    segments: List[Path] = []

    # Intro
    intro_path = tmp_dir / "000_intro.mp4"
    vf_intro = _title_vf(title="Trivia Episode", subtitle="Play along & keep score!", brand=brand, resolution=resolution)
    af_intro = _audio_mix_filter(total=5.0, voice=False, music_volume_db=music_volume_db)
    _render_segment(
        out_path=intro_path,
        bg_image=bg_image,
        duration=5.0,
        vf=vf_intro,
        af=af_intro,
        voice_path=None,
        music_path=music_path,
        fps=fps,
        resolution=resolution,
    )
    segments.append(intro_path)

    total_q = len(questions)
    rounds = [
        ("Round 1: Capitals", 0, min(10, total_q)),
        ("Round 2: Flags", min(10, total_q), min(20, total_q)),
        ("Round 3: Mixed Trivia", min(20, total_q), min(30, total_q)),
        ("Final Round", min(30, total_q), total_q),
    ]

    seg_idx = 1
    for round_title, start, end in rounds:
        if start >= end:
            continue

        sec_path = tmp_dir / f"{seg_idx:03d}_section.mp4"
        vf_sec = _section_vf(text=round_title, brand=brand, resolution=resolution)
        af_sec = _audio_mix_filter(total=2.5, voice=False, music_volume_db=music_volume_db)
        _render_segment(
            out_path=sec_path,
            bg_image=bg_image,
            duration=2.5,
            vf=vf_sec,
            af=af_sec,
            voice_path=None,
            music_path=music_path,
            fps=fps,
            resolution=resolution,
        )
        segments.append(sec_path)
        seg_idx += 1

        for i in range(start, end):
            q = questions[i]
            tts_out = tmp_dir / f"tts_{i+1:03d}.mp3"
            tts_res = providers.tts_question(text=q.question_text, gender=voice_gender, out_path=tts_out)
            tts_dur = ffprobe_duration(tts_res.audio_path)

            vf_q, total_dur = _question_vf(
                question_no=i + 1,
                total_questions=total_q,
                question_text=q.question_text,
                answer_text=q.answer_text,
                tts_duration=tts_dur,
                countdown_seconds=countdown_seconds,
                answer_seconds=answer_seconds,
                brand=brand,
                resolution=resolution,
            )
            af_q = _audio_mix_filter(total=total_dur, voice=True, music_volume_db=music_volume_db)

            q_path = tmp_dir / f"{seg_idx:03d}_q.mp4"
            _render_segment(
                out_path=q_path,
                bg_image=bg_image,
                duration=total_dur,
                vf=vf_q,
                af=af_q,
                voice_path=tts_res.audio_path,
                music_path=music_path,
                fps=fps,
                resolution=resolution,
            )
            segments.append(q_path)
            seg_idx += 1

    # Recap (60s)
    recap_path = tmp_dir / f"{seg_idx:03d}_recap.mp4"
    answers = [f"Q{i+1}: {questions[i].answer_text}" for i in range(total_q)]
    vf_recap = _recap_vf(answers=answers, brand=brand, resolution=resolution)
    af_recap = _audio_mix_filter(total=60.0, voice=False, music_volume_db=music_volume_db)
    _render_segment(
        out_path=recap_path,
        bg_image=bg_image,
        duration=60.0,
        vf=vf_recap,
        af=af_recap,
        voice_path=None,
        music_path=music_path,
        fps=fps,
        resolution=resolution,
    )
    segments.append(recap_path)

    # Concat
    concat_txt = tmp_dir / "concat.txt"
    lines = []
    for p in segments:
        lines.append(f"file '{p.as_posix()}'\n")
    concat_txt.write_text("".join(lines), encoding="utf-8")

    cmd_copy = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_txt),
        "-c",
        "copy",
        str(out_path),
    ]
    try:
        run_ffmpeg(cmd_copy)
    except Exception:
        cmd_re = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(out_path),
        ]
        run_ffmpeg(cmd_re)

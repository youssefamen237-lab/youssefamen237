\
import logging
import math
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .assets import load_blurred_background, pick_random_music, repo_path
from .tts import synthesize
from .utils.ffmpeg_utils import ensure_ffmpeg, run_cmd

logger = logging.getLogger(__name__)


def _load_font(font_candidates: List[str], size: int) -> ImageFont.FreeTypeFont:
    for p in font_candidates:
        try:
            if p and os.path.exists(p):
                return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    for w in words:
        test = " ".join(cur + [w])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
                cur = [w]
            else:
                lines.append(w)
                cur = []
    if cur:
        lines.append(" ".join(cur))
    return lines


def _draw_card(
    base: Image.Image,
    text_lines: List[str],
    options_lines: List[str],
    timer_text: Optional[str],
    config: Dict[str, Any],
    diff_pair: Optional[Tuple[Image.Image, Image.Image]] = None,
) -> Image.Image:
    w, h = base.size
    render_cfg = config.get("render") or {}
    safe = int(render_cfg.get("safe_margin_px", 110))
    pad = int(render_cfg.get("card_padding_px", 60))
    radius = int(render_cfg.get("card_radius_px", 40))
    opacity = float(render_cfg.get("card_opacity", 0.75))

    font_path_candidates = list(render_cfg.get("font_path_candidates") or [])
    body_font_size = int(render_cfg.get("body_font_size", 64))
    answer_font_size = int(render_cfg.get("answer_font_size", 78))

    body_font = _load_font(font_path_candidates, body_font_size)
    opt_font = _load_font(font_path_candidates, int(body_font_size * 0.72))
    timer_font = _load_font(font_path_candidates, int(body_font_size * 0.9))

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    max_card_w = w - 2 * safe
    card_w = max_card_w
    card_x0 = safe
    card_x1 = safe + card_w

    y = safe
    content_top = y

    # reserve space for diff images if present
    diff_h = 0
    if diff_pair is not None:
        diff_h = int(min(640, (h - 2 * safe) * 0.35))
        content_top += diff_h + int(pad * 0.6)

    # compute text height
    draw_tmp = ImageDraw.Draw(Image.new("RGB", (w, h)))
    max_text_w = card_w - 2 * pad
    wrapped: List[str] = []
    for ln in text_lines:
        wrapped.extend(_wrap_text(draw_tmp, ln, body_font, max_text_w))
    opt_wrapped: List[str] = []
    for ln in options_lines:
        opt_wrapped.extend(_wrap_text(draw_tmp, ln, opt_font, max_text_w))

    line_h = int(body_font_size * 1.25)
    opt_line_h = int(opt_font.size * 1.35)
    text_block_h = len(wrapped) * line_h + (len(opt_wrapped) * opt_line_h if opt_wrapped else 0)

    timer_h = int(timer_font.size * 1.5) if timer_text else 0
    card_h = diff_h + int(pad * 2) + text_block_h + timer_h + int(pad * (0.8 if timer_text else 0.2))
    card_h = min(card_h, h - 2 * safe)
    card_y0 = (h - card_h) // 2
    card_y1 = card_y0 + card_h

    fill = (0, 0, 0, int(255 * opacity))
    od.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=radius, fill=fill)

    # paste diff images
    if diff_pair is not None:
        left_im, right_im = diff_pair
        inner_w = card_w - 2 * pad
        gap = int(pad * 0.5)
        img_w = (inner_w - gap) // 2
        img_h = diff_h
        left_im = left_im.resize((img_w, img_h), Image.Resampling.LANCZOS).convert("RGB")
        right_im = right_im.resize((img_w, img_h), Image.Resampling.LANCZOS).convert("RGB")
        x0 = card_x0 + pad
        y0 = card_y0 + pad
        overlay.paste(left_im, (x0, y0))
        overlay.paste(right_im, (x0 + img_w + gap, y0))

        # labels
        lbl_font = _load_font(font_path_candidates, int(opt_font.size * 1.05))
        od.text((x0 + 10, y0 + 10), "LEFT", font=lbl_font, fill=(255, 255, 255, 230))
        od.text((x0 + img_w + gap + 10, y0 + 10), "RIGHT", font=lbl_font, fill=(255, 255, 255, 230))

    # draw text
    dd = ImageDraw.Draw(overlay)
    tx = card_x0 + pad
    ty = card_y0 + pad + (diff_h + int(pad * 0.6) if diff_pair is not None else 0)

    for ln in wrapped:
        dd.text((tx, ty), ln, font=body_font, fill=(255, 255, 255, 240))
        ty += line_h

    if opt_wrapped:
        ty += int(opt_line_h * 0.4)
        for ln in opt_wrapped:
            dd.text((tx, ty), ln, font=opt_font, fill=(230, 230, 230, 235))
            ty += opt_line_h

    if timer_text:
        ty += int(timer_font.size * 0.35)
        tw = dd.textbbox((0, 0), timer_text, font=timer_font)[2]
        dd.text(((w - tw) // 2, card_y1 - pad - timer_font.size), timer_text, font=timer_font, fill=(255, 255, 255, 230))

    composed = base.convert("RGBA")
    composed = Image.alpha_composite(composed, overlay)
    return composed.convert("RGB")


def _make_diff_images(size: Tuple[int, int], different_side: str) -> Tuple[Image.Image, Image.Image]:
    w, h = size
    bg = (20, 20, 20)
    left = Image.new("RGB", (w, h), bg)
    right = Image.new("RGB", (w, h), bg)

    def draw_shapes(img: Image.Image, seed: int) -> None:
        rnd = random.Random(seed)
        d = ImageDraw.Draw(img)
        for _ in range(9):
            x0 = rnd.randint(10, w - 120)
            y0 = rnd.randint(10, h - 120)
            x1 = x0 + rnd.randint(40, 130)
            y1 = y0 + rnd.randint(40, 130)
            shape = rnd.choice(["rect", "ellipse"])
            col = (rnd.randint(60, 240), rnd.randint(60, 240), rnd.randint(60, 240))
            if shape == "rect":
                d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=col)
            else:
                d.ellipse([x0, y0, x1, y1], fill=col)

    base_seed = random.randint(0, 10_000_000)
    draw_shapes(left, base_seed)
    draw_shapes(right, base_seed)

    # introduce a small difference
    target = left if different_side.upper() == "LEFT" else right
    d = ImageDraw.Draw(target)
    x0 = random.randint(20, w - 180)
    y0 = random.randint(20, h - 180)
    x1 = x0 + random.randint(60, 170)
    y1 = y0 + random.randint(60, 170)
    col = (255, 255, 255)
    d.rectangle([x0, y0, x1, y1], outline=col, width=6)

    return left, right


@dataclass
class RenderResult:
    video_path: Path
    duration_seconds: float
    thumbnail_path: Optional[Path]


def render_short(
    *,
    config: Dict[str, Any],
    question: str,
    answer: str,
    options: Optional[List[str]],
    template_id: str,
    voice_profile: Dict[str, Any],
    cta_text: str,
    out_dir: Path,
) -> RenderResult:
    ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    render_cfg = config.get("render") or {}
    content_cfg = config.get("content") or {}
    assets_cfg = config.get("assets") or {}

    size = tuple((render_cfg.get("shorts_size") or [1080, 1920]))  # type: ignore
    fps = int(render_cfg.get("fps", 30))
    blur_radius = int(render_cfg.get("blur_radius", 18))

    images_dir = repo_path(str(assets_cfg.get("images_dir") or "assets/images"))
    music_dir = repo_path(str(assets_cfg.get("music_dir") or "assets/music"))

    countdown = int(content_cfg.get("short_countdown_seconds", 3))
    ans_min = float(content_cfg.get("short_answer_seconds_min", 1.0))
    ans_max = float(content_cfg.get("short_answer_seconds_max", 1.7))
    answer_seconds = random.uniform(ans_min, ans_max)

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        base_bg = load_blurred_background(images_dir, size=size, blur_radius=blur_radius)

        diff_pair = None
        text_lines: List[str] = []
        opt_lines: List[str] = []

        if template_id == "left_right_diff":
            diff_pair = _make_diff_images((640, 420), different_side=answer)
            text_lines = [question]
            opt_lines = ["A) LEFT   B) RIGHT"]
        elif options and template_id in {"mcq", "odd_one_out"}:
            text_lines = [question]
            labels = ["A", "B", "C", "D"]
            opt_lines = [f"{labels[i]}) {opt}" for i, opt in enumerate(options[:4])]
        elif options and template_id == "true_false":
            text_lines = [question]
            opt_lines = ["A) True", "B) False"]
        else:
            text_lines = [question]
            opt_lines = []

        # Voice
        voice_text = f"{question} {cta_text}"
        voice_mp3 = tdir / "voice.mp3"
        voice_dur = synthesize(voice_text, voice_profile, voice_mp3)

        # Make sure countdown is long enough for voice (avoid cutting audio)
        q_seconds = float(max(countdown, math.ceil(voice_dur)))
        q_seconds = float(min(q_seconds, countdown + 2))
        timer_secs = int(round(q_seconds))
        if timer_secs < 2:
            timer_secs = 2

        frames: List[Tuple[Path, float]] = []
        for t in range(timer_secs, 0, -1):
            timer_text = str(t)
            frame = _draw_card(
                base_bg,
                text_lines=text_lines,
                options_lines=opt_lines,
                timer_text=timer_text,
                config=config,
                diff_pair=diff_pair,
            )
            fp = tdir / f"q_{t}.png"
            frame.save(fp, format="PNG")
            frames.append((fp, 1.0))

        ans_frame = _draw_card(
            base_bg,
            text_lines=["Answer:", answer],
            options_lines=[],
            timer_text=None,
            config=config,
            diff_pair=None,
        )
        ans_png = tdir / "answer.png"
        ans_frame.save(ans_png, format="PNG")
        frames.append((ans_png, answer_seconds))

        # Thumbnail: use the first question frame
        thumb_path = out_dir / f"thumb_short_{random.randint(100000, 999999)}.png"
        try:
            Image.open(frames[0][0]).save(thumb_path)
        except Exception:
            thumb_path = None
        # concat list for images
        concat_txt = tdir / "images.txt"
        lines = []
        for fp, dur in frames:
            lines.append(f"file '{fp.as_posix()}'")
            lines.append(f"duration {dur:.3f}")
        # repeat last file without duration
        lines.append(f"file '{frames[-1][0].as_posix()}'")
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        video_noaudio = tdir / "video_noaudio.mp4"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-r",
                str(fps),
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                str(video_noaudio),
            ]
        )

        total_duration = float(timer_secs) + float(answer_seconds)

        # optional music for the question part only
        music_path = pick_random_music(music_dir)

        final_out = out_dir / f"short_{random.randint(100000, 999999)}.mp4"
        if music_path:
            filter_complex = (
                f"anullsrc=r=44100:cl=stereo,atrim=0:{total_duration:.3f}[sil];"
                f"[1:a]atrim=0:{q_seconds:.3f},asetpts=PTS-STARTPTS,volume=1.0[voice];"
                f"[2:a]atrim=0:{q_seconds:.3f},asetpts=PTS-STARTPTS,volume=0.08[mus];"
                f"[voice][mus]amix=inputs=2:duration=first:dropout_transition=2[mix];"
                f"[sil][mix]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_noaudio),
                    "-i",
                    str(voice_mp3),
                    "-i",
                    str(music_path),
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(final_out),
                ]
            )
        else:
            filter_complex = (
                f"anullsrc=r=44100:cl=stereo,atrim=0:{total_duration:.3f}[sil];"
                f"[1:a]atrim=0:{q_seconds:.3f},asetpts=PTS-STARTPTS,volume=1.0[voice];"
                f"[sil][voice]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_noaudio),
                    "-i",
                    str(voice_mp3),
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(final_out),
                ]
            )

        return RenderResult(video_path=final_out, duration_seconds=total_duration, thumbnail_path=thumb_path if thumb_path and Path(thumb_path).exists() else None)


def render_long_compilation(
    *,
    config: Dict[str, Any],
    items: List[Dict[str, Any]],
    voice_profile: Dict[str, Any],
    out_dir: Path,
    title_slide: Optional[str] = None,
) -> RenderResult:
    ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    render_cfg = config.get("render") or {}
    content_cfg = config.get("content") or {}
    assets_cfg = config.get("assets") or {}

    size = tuple((render_cfg.get("shorts_size") or [1080, 1920]))  # vertical compilation
    fps = int(render_cfg.get("fps", 30))
    blur_radius = int(render_cfg.get("blur_radius", 18))

    images_dir = repo_path(str(assets_cfg.get("images_dir") or "assets/images"))
    music_dir = repo_path(str(assets_cfg.get("music_dir") or "assets/music"))

    q_seconds = float(content_cfg.get("long_question_seconds", 9.0))
    countdown = int(content_cfg.get("long_countdown_seconds", 6))
    answer_seconds = float(content_cfg.get("long_answer_seconds", 2.0))

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        segment_paths: List[Path] = []

        base_bg = load_blurred_background(images_dir, size=size, blur_radius=blur_radius)

        # optional intro
        if title_slide:
            intro_img = _draw_card(base_bg, [title_slide], [], None, config=config)
            intro_png = tdir / "intro.png"
            intro_img.save(intro_png, format="PNG")

            intro_txt = tdir / "intro_images.txt"
            intro_txt.write_text(
                "\n".join([f"file '{intro_png.as_posix()}'", "duration 2.5", f"file '{intro_png.as_posix()}'"]),
                encoding="utf-8",
            )
            intro_mp4 = tdir / "intro.mp4"
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(intro_txt),
                    "-r",
                    str(fps),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    str(intro_mp4),
                ]
            )
            segment_paths.append(intro_mp4)

        # render each question as a short segment
        for idx, it in enumerate(items):
            question = str(it["question"])
            answer = str(it["answer"])
            template_id = str(it.get("template_id") or "mcq")
            options = it.get("options")

            with tempfile.TemporaryDirectory() as segtd:
                segdir = Path(segtd)

                diff_pair = None
                text_lines: List[str] = []
                opt_lines: List[str] = []

                if template_id == "left_right_diff":
                    diff_pair = _make_diff_images((640, 420), different_side=answer)
                    text_lines = [question]
                    opt_lines = ["LEFT or RIGHT?"]
                elif isinstance(options, list) and template_id in {"mcq", "odd_one_out"}:
                    text_lines = [question]
                    labels = ["A", "B", "C", "D"]
                    opt_lines = [f"{labels[i]}) {str(opt)}" for i, opt in enumerate(options[:4])]
                elif isinstance(options, list) and template_id == "true_false":
                    text_lines = [question]
                    opt_lines = ["True or False?"]
                else:
                    text_lines = [question]
                    opt_lines = []

                # voice
                voice_text = question
                voice_mp3 = segdir / "voice.mp3"
                voice_dur = synthesize(voice_text, voice_profile, voice_mp3)

                seg_timer = int(max(countdown, min(countdown + 3, math.ceil(voice_dur))))
                seg_q_seconds = float(max(q_seconds, seg_timer))

                frames: List[Tuple[Path, float]] = []
                for t in range(seg_timer, 0, -1):
                    frame = _draw_card(
                        base_bg,
                        text_lines=text_lines,
                        options_lines=opt_lines,
                        timer_text=str(t),
                        config=config,
                        diff_pair=diff_pair,
                    )
                    fp = segdir / f"q_{t}.png"
                    frame.save(fp, format="PNG")
                    frames.append((fp, 1.0))

                ans_frame = _draw_card(base_bg, ["Answer:", answer], [], None, config=config, diff_pair=None)
                ans_png = segdir / "answer.png"
                ans_frame.save(ans_png, format="PNG")
                frames.append((ans_png, answer_seconds))

                concat_txt = segdir / "images.txt"
                lines = []
                for fp, dur in frames:
                    lines.append(f"file '{fp.as_posix()}'")
                    lines.append(f"duration {dur:.3f}")
                lines.append(f"file '{frames[-1][0].as_posix()}'")
                concat_txt.write_text("\n".join(lines), encoding="utf-8")

                seg_noaudio = segdir / "seg_noaudio.mp4"
                run_cmd(
                    [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat_txt),
                        "-r",
                        str(fps),
                        "-pix_fmt",
                        "yuv420p",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        str(seg_noaudio),
                    ]
                )

                seg_total = float(seg_timer) + float(answer_seconds)

                music_path = pick_random_music(music_dir)

                seg_final = tdir / f"seg_{idx:03d}.mp4"
                if music_path:
                    filter_complex = (
                        f"anullsrc=r=44100:cl=stereo,atrim=0:{seg_total:.3f}[sil];"
                        f"[1:a]atrim=0:{float(seg_timer):.3f},asetpts=PTS-STARTPTS,volume=1.0[voice];"
                        f"[2:a]atrim=0:{float(seg_timer):.3f},asetpts=PTS-STARTPTS,volume=0.06[mus];"
                        f"[voice][mus]amix=inputs=2:duration=first:dropout_transition=2[mix];"
                        f"[sil][mix]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                    )
                    run_cmd(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(seg_noaudio),
                            "-i",
                            str(voice_mp3),
                            "-i",
                            str(music_path),
                            "-filter_complex",
                            filter_complex,
                            "-map",
                            "0:v:0",
                            "-map",
                            "[aout]",
                            "-c:v",
                            "copy",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                            "-shortest",
                            str(seg_final),
                        ]
                    )
                else:
                    filter_complex = (
                        f"anullsrc=r=44100:cl=stereo,atrim=0:{seg_total:.3f}[sil];"
                        f"[1:a]atrim=0:{float(seg_timer):.3f},asetpts=PTS-STARTPTS,volume=1.0[voice];"
                        f"[sil][voice]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                    )
                    run_cmd(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(seg_noaudio),
                            "-i",
                            str(voice_mp3),
                            "-filter_complex",
                            filter_complex,
                            "-map",
                            "0:v:0",
                            "-map",
                            "[aout]",
                            "-c:v",
                            "copy",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                            "-shortest",
                            str(seg_final),
                        ]
                    )

                segment_paths.append(seg_final)

        # concat segments
        concat_list = tdir / "segments.txt"
        concat_lines = [f"file '{p.as_posix()}'" for p in segment_paths]
        concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

        final_out = out_dir / f"long_{random.randint(100000, 999999)}.mp4"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(final_out),
            ]
        )

        # thumbnail: first segment mid-frame
        thumb_path = out_dir / f"thumb_long_{random.randint(100000, 999999)}.png"
        try:
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(final_out),
                    "-ss",
                    "00:00:01.000",
                    "-vframes",
                    "1",
                    str(thumb_path),
                ]
            )
        except Exception:
            thumb_path = None

        # compute duration via ffprobe (format)
        try:
            import json as _json
            import subprocess

            p = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(final_out)],
                capture_output=True,
                text=True,
                check=True,
            )
            dur = float((_json.loads(p.stdout).get("format") or {}).get("duration") or 0.0)
        except Exception:
            dur = 0.0

        return RenderResult(video_path=final_out, duration_seconds=dur, thumbnail_path=thumb_path if thumb_path and Path(thumb_path).exists() else None)

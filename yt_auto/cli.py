from __future__ import annotations

import argparse
import os
import random
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from yt_auto.config import load_config
from yt_auto.images import pick_background
from yt_auto.llm import QuizItem, generate_quiz_batch_long, generate_quiz_item
from yt_auto.long_humanize import build_long_meta, pick_theme, theme_by_key
from yt_auto.safety import validate_text_is_safe
from yt_auto.state import StateStore
from yt_auto.thumbnail import build_long_thumbnail
from yt_auto.tts import synthesize_tts
from yt_auto.utils import ensure_dir, normalize_text, sha256_hex
from yt_auto.video import build_long_compilation, build_short, ffprobe_duration_seconds
from yt_auto.youtube_uploader import YouTubeUploader


def _seed_for(slot: int, date_yyyymmdd: str) -> int:
    return abs(hash(f"{date_yyyymmdd}:{slot}")) % (10**9)


def _ffmpeg_silence_wav(out_wav: Path, seconds: float) -> None:
    """Create a silent wav file (used as a fallback when TTS isn't available)."""

    ensure_dir(out_wav.parent)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",
        f"{seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg_silence_failed: {p.stderr[:500]}")


def _compose_spoken_text(quiz_question: str, cta: str) -> str:
    q = quiz_question.strip()
    c = cta.strip()
    if not q.endswith("?"):
        q = q + "?"
    if c:
        return f"{q} {c}"
    return q


def _final_short_description(base: str, hashtags: list[str]) -> str:
    d = (base or "").strip()
    if "Quizzaro" not in d:
        d = (d + "\n\nSubscribe to Quizzaro for more quizzes!").strip()
    h = " ".join([x.strip() for x in hashtags if x.strip()])
    if h:
        d = (d + "\n\n" + h).strip()
    return d


def _ensure_unique_or_regen(state: StateStore, cfg, seed: int):
    for i in range(1, 9):
        item = generate_quiz_item(cfg, seed + i * 17)
        safe = validate_text_is_safe(item.question, item.answer)
        if not safe.ok:
            continue
        if state.is_duplicate_question(item.question, days_window=cfg.min_days_between_repeats):
            continue
        return item, (seed + i * 17)
    item = generate_quiz_item(cfg, seed + 9991)
    return item, (seed + 9991)


def _build_short_pipeline(cfg, state: StateStore, slot: int, date_yyyymmdd: str):
    ensure_dir(cfg.out_dir)

    if state.was_short_published(date_yyyymmdd, slot):
        return ("", "")

    uploader = YouTubeUploader(cfg.youtube_oauths)

    base_seed = _seed_for(slot, date_yyyymmdd)

    quiz = None
    used_seed = base_seed

    tts_wav = cfg.out_dir / f"tts_{date_yyyymmdd}_slot{slot}.wav"

    for attempt in range(1, 9):
        quiz, used_seed = _ensure_unique_or_regen(state, cfg, base_seed + attempt * 101)

        spoken = _compose_spoken_text(quiz.question, quiz.cta)
        _ = synthesize_tts(cfg, spoken, tts_wav)

        dur = ffprobe_duration_seconds(tts_wav)
        if dur <= float(cfg.countdown_seconds) - 0.15:
            break

        tts_wav.unlink(missing_ok=True)

    if quiz is None or not tts_wav.exists():
        raise RuntimeError("tts_generation_failed")

    fp = sha256_hex(normalize_text(quiz.question))
    bg = pick_background(cfg, used_seed)

    out_mp4 = cfg.out_dir / f"short-{date_yyyymmdd}-slot{slot}.mp4"
    _ = build_short(cfg, quiz, bg, tts_wav, out_mp4, used_seed)

    desc = _final_short_description(quiz.description, quiz.hashtags)

    res = uploader.upload_video(
        file_path=out_mp4,
        title=quiz.title,
        description=desc,
        tags=quiz.tags,
        category_id=cfg.category_id_short,
        privacy_status=cfg.privacy_short,
        made_for_kids=cfg.made_for_kids,
        default_language=cfg.language,
        default_audio_language=cfg.language,
    )

    date_iso = datetime.strptime(date_yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    state.add_used_question(quiz.question, quiz.answer, date_iso)
    state.prune_used(keep_days=90)

    artifact_name = f"short-{date_yyyymmdd}-slot{slot}"
    state.record_short(date_yyyymmdd, slot, res.video_id, artifact_name, fp)
    state.save()

    tts_wav.unlink(missing_ok=True)

    return (res.video_id, "tts")


def _build_long_pipeline(cfg, state: StateStore, date_yyyymmdd: str) -> str:
    ensure_dir(cfg.out_dir)

    if state.was_long_published(date_yyyymmdd):
        return ""

    # Long video is generated independently (no dependency on Shorts artifacts).
    base_seed = abs(hash(f"long:{date_yyyymmdd}")) % (10**9)
    r = random.Random(base_seed)

    theme = pick_theme(base_seed)

    # Randomize duration (minutes) in a way that doesn't always hit the extremes.
    lo = int(cfg.long_min_minutes)
    hi = int(cfg.long_max_minutes)
    if hi < lo:
        hi = lo
    # Triangular-ish: bias toward the middle
    target_minutes = int(round(r.triangular(lo, hi, (lo + hi) / 2)))
    target_minutes = max(lo, min(hi, target_minutes))

    # Randomize card durations a bit to avoid a fixed structure.
    intro_s = r.uniform(4.5, 6.5)
    outro_s = r.uniform(4.5, 6.5)
    gap_s = r.uniform(1.2, 2.2)

    countdown_choices = cfg.long_countdown_choices or [8, 9, 10, 11]
    avg_cd = sum(countdown_choices) / float(len(countdown_choices))
    avg_clip = avg_cd + float(cfg.answer_reveal_seconds)
    avg_with_gap = avg_clip + gap_s

    target_seconds = target_minutes * 60.0
    est_questions = int(round(max(1.0, (target_seconds - intro_s - outro_s + gap_s) / avg_with_gap)))
    n_questions = max(18, min(90, est_questions))

    meta = build_long_meta(theme, n_questions=n_questions, countdown_choices=countdown_choices, seed=base_seed + 7)

    # --- Generate questions (batch) ---
    qas = []
    seen_norm = set()
    batch_seed = base_seed + 1000
    max_batches = 10

    while len(qas) < n_questions and max_batches > 0:
        need = n_questions - len(qas)
        batch_n = min(16, max(8, need))
        batch = generate_quiz_batch_long(cfg, batch_seed, batch_n, theme.key)

        for qa in batch:
            if len(qas) >= n_questions:
                break
            norm_q = normalize_text(qa.question)
            if norm_q in seen_norm:
                continue
            if state.is_duplicate_question(qa.question, days_window=cfg.min_days_between_repeats):
                continue
            safe = validate_text_is_safe(qa.question, qa.answer)
            if not safe.ok:
                continue
            seen_norm.add(norm_q)
            qas.append(qa)

        batch_seed += 997
        max_batches -= 1

    if not qas:
        return ""

    # If we fell back to the built-in local pool (no LLM keys), keep metadata generic
    # to avoid mismatch (e.g., LOGOS title with non-logo questions).
    if all(getattr(x, "provider", "") == "fallback" for x in qas):
        theme = theme_by_key("GK")
        meta = build_long_meta(theme, n_questions=n_questions, countdown_choices=countdown_choices, seed=base_seed + 7)

        # If the fallback pool can't provide enough unique questions, allow repeats
        # (only in fallback mode) so the long video duration is still achieved.
        while len(qas) < n_questions:
            extra_seed = base_seed + 50000 + len(qas)
            extra = generate_quiz_batch_long(cfg, extra_seed, 1, theme.key)
            if not extra:
                break
            qa = extra[0]
            safe = validate_text_is_safe(qa.question, qa.answer)
            if not safe.ok:
                continue
            qas.append(qa)

    # --- Build quiz clips ---
    clips: list[Path] = []
    silent_wav = cfg.out_dir / f"silence_long_{date_yyyymmdd}.wav"
    if not silent_wav.exists():
        # long enough for the biggest countdown trim
        _ffmpeg_silence_wav(silent_wav, seconds=float(max(countdown_choices) + 2))

    use_tts = os.getenv("LONG_USE_TTS", "1").strip().lower() not in {"0", "false", "no"}

    for idx, qa in enumerate(qas, start=1):
        clip_seed = base_seed + idx * 31
        cd = r.choice(countdown_choices)

        # Use a per-clip countdown without affecting Shorts
        cfg_clip = replace(cfg, countdown_seconds=int(cd))

        bg = pick_background(cfg, clip_seed)
        out_clip = cfg.out_dir / f"longclip-{date_yyyymmdd}-{idx:03d}.mp4"

        # TTS (optional). If it fails or is too long, fall back to silence.
        wav_in = silent_wav
        tmp_wav = cfg.out_dir / f"tts_long_{date_yyyymmdd}_{idx:03d}.wav"
        if use_tts:
            try:
                _ = synthesize_tts(cfg, qa.question, tmp_wav)
                if tmp_wav.exists():
                    dur = ffprobe_duration_seconds(tmp_wav)
                    if dur <= float(cd) - 0.15:
                        wav_in = tmp_wav
                    else:
                        tmp_wav.unlink(missing_ok=True)
            except Exception:
                tmp_wav.unlink(missing_ok=True)

        quiz_item = QuizItem(
            category=qa.category,
            question=qa.question,
            answer=qa.answer,
            cta="",
            title="",
            description="",
            tags=[],
            hashtags=[],
            provider=qa.provider,
        )

        _ = build_short(cfg_clip, quiz_item, bg, wav_in, out_clip, clip_seed)
        clips.append(out_clip)

        if tmp_wav.exists():
            tmp_wav.unlink(missing_ok=True)

    # --- Compile to a 16:9 long video ---
    out_long = cfg.out_dir / f"long-{date_yyyymmdd}.mp4"

    intro_sub = f"{meta.keyword} QUIZ • {len(clips)} QUESTIONS"
    build_long_compilation(
        cfg,
        clips,
        out_long,
        date_yyyymmdd=date_yyyymmdd,
        intro_title="Quizzaro",
        intro_subtitle=intro_sub,
        gap_title="Next",
        gap_subtitle="Get Ready!",
        outro_title="Quizzaro",
        outro_subtitle="Comment your score + subscribe!",
        intro_s=float(intro_s),
        gap_s=float(gap_s),
        outro_s=float(outro_s),
    )

    # --- Thumbnail ---
    bg_thumb = pick_background(cfg, base_seed + 9999)
    thumb = cfg.out_dir / f"thumb-{date_yyyymmdd}.jpg"
    build_long_thumbnail(
        cfg,
        bg_thumb,
        thumb,
        keyword=meta.keyword,
        badge=meta.badge,
        subline=meta.subline,
        seed=base_seed + 123,
    )

    # --- Upload ---
    uploader = YouTubeUploader(cfg.youtube_oauths)
    res = uploader.upload_video(
        file_path=out_long,
        title=meta.title[:100],
        description=meta.description[:5000],
        tags=meta.tags,
        category_id=cfg.category_id_long,
        privacy_status=cfg.privacy_long,
        made_for_kids=cfg.made_for_kids,
        default_language=cfg.language,
        default_audio_language=cfg.language,
    )

    try:
        uploader.set_thumbnail(res.video_id, thumb)
    except Exception:
        pass

    # Record used questions (so Shorts/Long don't repeat)
    date_iso = datetime.strptime(date_yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    for qa in qas:
        state.add_used_question(qa.question, qa.answer, date_iso)
    state.prune_used(keep_days=120)

    state.record_long(date_yyyymmdd, res.video_id)
    state.save()

    return res.video_id


def main() -> int:
    parser = argparse.ArgumentParser(prog="yt_auto")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("bootstrap")
    p_boot.add_argument("--date", required=False, default="")

    p_short = sub.add_parser("short")
    p_short.add_argument("--slot", required=True, type=int, choices=[1, 2, 3, 4])
    p_short.add_argument("--date", required=False, default="")

    p_long = sub.add_parser("long")
    p_long.add_argument("--date", required=False, default="")

    p_all = sub.add_parser("run-all")
    p_all.add_argument("--date", required=False, default="")

    args = parser.parse_args()
    cfg = load_config()
    state = StateStore(cfg.state_path)

    if args.cmd == "bootstrap":
        date_yyyymmdd = (args.date or "").strip()
        if not date_yyyymmdd:
            date_yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
        _vid, _tts = _build_short_pipeline(cfg, state, slot=1, date_yyyymmdd=date_yyyymmdd)
        if not state.is_bootstrapped():
            state.set_bootstrapped(True)
            state.save()
        return 0

    if args.cmd == "short":
        date_yyyymmdd = (args.date or "").strip()
        if not date_yyyymmdd:
            date_yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
        _vid, _tts = _build_short_pipeline(cfg, state, slot=int(args.slot), date_yyyymmdd=date_yyyymmdd)
        if not state.is_bootstrapped():
            state.set_bootstrapped(True)
            state.save()
        return 0

    if args.cmd == "long":
        date_yyyymmdd = (args.date or "").strip()
        if not date_yyyymmdd:
            date_yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
        _ = _build_long_pipeline(cfg, state, date_yyyymmdd=date_yyyymmdd)
        return 0

    if args.cmd == "run-all":
        date_yyyymmdd = (args.date or "").strip()
        if not date_yyyymmdd:
            date_yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")

        # Shorts first (kept unchanged)
        for slot in [1, 2, 3, 4]:
            _build_short_pipeline(cfg, state, slot=slot, date_yyyymmdd=date_yyyymmdd)

        # Then the long video (humanized)
        _build_long_pipeline(cfg, state, date_yyyymmdd=date_yyyymmdd)

        if not state.is_bootstrapped():
            state.set_bootstrapped(True)
            state.save()
        return 0

    return 2

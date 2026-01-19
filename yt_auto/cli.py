from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from yt_auto.config import load_config
from yt_auto.github_artifacts import download_shorts_for_date
from yt_auto.images import pick_background
from yt_auto.llm import generate_quiz_item
from yt_auto.safety import validate_text_is_safe
from yt_auto.state import StateStore
from yt_auto.thumbnail import build_long_thumbnail
from yt_auto.tts import synthesize_tts
from yt_auto.utils import ensure_dir, normalize_text, sha256_hex
from yt_auto.video import build_long_compilation, build_short, ffprobe_duration_seconds
from yt_auto.youtube_uploader import YouTubeUploader


def _repo_full_name() -> str:
    v = os.getenv("GITHUB_REPOSITORY", "").strip()
    if v:
        return v
    raise RuntimeError("missing_GITHUB_REPOSITORY_env")


def _seed_for(slot: int, date_yyyymmdd: str) -> int:
    return abs(hash(f"{date_yyyymmdd}:{slot}")) % (10**9)


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

    token = cfg.github_token.strip()
    if not token:
        return ""

    owner_repo = _repo_full_name()

    clips = download_shorts_for_date(cfg.out_dir, date_yyyymmdd, token, owner_repo)
    if len(clips) < 4:
        return ""

    out_long = cfg.out_dir / f"long-{date_yyyymmdd}.mp4"
    build_long_compilation(cfg, clips, out_long, date_yyyymmdd)

    bg = pick_background(cfg, abs(hash(date_yyyymmdd)) % (10**9))
    thumb = cfg.out_dir / f"thumb-{date_yyyymmdd}.jpg"
    build_long_thumbnail(cfg, bg, thumb, date_yyyymmdd)

    uploader = YouTubeUploader(cfg.youtube_oauths)

    title = f"Quizzaro Daily Compilation ({date_yyyymmdd})"
    desc = "Today's 10-second quizzes in one compilation.\n\nSubscribe to Quizzaro for more!"
    tags = ["quiz", "trivia", "compilation", "daily quiz", "brain teaser", "knowledge", "quizzaro"]

    res = uploader.upload_video(
        file_path=out_long,
        title=title[:100],
        description=desc[:5000],
        tags=tags,
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

    return 2

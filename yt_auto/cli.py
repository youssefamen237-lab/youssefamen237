from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from yt_auto.config import load_config
from yt_auto.github_artifacts import download_shorts_for_date
from yt_auto.images import pick_background
from yt_auto.llm import generate_quiz_item
from yt_auto.manager import ContentAnalyzer, StrategyOptimizer, RiskManager
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

    # Require YouTube OAuth for actual uploads
    if not cfg.youtube_oauths:
        raise RuntimeError("YouTube OAuth credentials required. Set YT_CLIENT_ID_1, YT_CLIENT_SECRET_1, YT_REFRESH_TOKEN_1 environment variables.")
    
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

    # Upload video to YouTube
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
    video_id = res.video_id

    date_iso = datetime.strptime(date_yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")
    state.add_used_question(quiz.question, quiz.answer, date_iso)
    state.prune_used(keep_days=90)

    artifact_name = f"short-{date_yyyymmdd}-slot{slot}"
    state.record_short(date_yyyymmdd, slot, video_id, artifact_name, fp)
    state.save()

    tts_wav.unlink(missing_ok=True)

    return (video_id, "youtube")



def _build_long_pipeline(cfg, state: StateStore, date_yyyymmdd: str) -> str:
    ensure_dir(cfg.out_dir)

    if state.was_long_published(date_yyyymmdd):
        return ""

    token = cfg.github_token.strip()
    if not token:
        return ""

    # Require YouTube OAuth for uploads
    if not cfg.youtube_oauths:
        raise RuntimeError("YouTube OAuth credentials required. Set YT_CLIENT_ID_2, YT_CLIENT_SECRET_2, YT_REFRESH_TOKEN_2 environment variables.")

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

    # Generate dynamic titles for long compilations
    title_options = [
        f"🧠 Ultimate Quizzaro Daily Compilation - {date_yyyymmdd}",
        f"📚 Today's Brain Teasers | Quizzaro Quiz Marathon {date_yyyymmdd}",
        f"⚡ 10-Second Quiz Challenge Compilation - {date_yyyymmdd}",
        f"🎯 Quizzaro Daily Trivia Dump - Can You Score Perfect? {date_yyyymmdd}",
        f"🔥 Test Your Knowledge | Quizzaro Daily Shorts {date_yyyymmdd}",
    ]
    base_seed_long = abs(hash(date_yyyymmdd)) % (10**9)
    import random as _r
    title = _r.Random(base_seed_long).choice(title_options)
    
    desc = """🎯 Can you get them all right? Today's Quizzaro daily quiz compilation featuring 10-second brain teasers!

⭐ Challenge yourself and comment your scores below!
📺 Subscribe to Quizzaro for daily trivia, brain teasers, and quick knowledge challenges
🧠 Perfect for testing your knowledge and learning fun facts

#quizzaro #quiz #trivia #brainfteaser #shorts #daily #challenge #education"""
    
    tags = ["quiz", "trivia", "compilation", "daily quiz", "brain teaser", "knowledge", "quizzaro", "shorts", "challenge", "education", "learning", "viral", "educational content", "mind puzzle", "IQ test"]

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


def _analyze_and_optimize(cfg, state: StateStore) -> None:
    """Analyze video performance and optimize strategy."""
    analyzer = ContentAnalyzer(cfg)
    optimizer = StrategyOptimizer(cfg, analyzer)
    risk_manager = RiskManager(cfg)

    # Get recent published videos from state
    state_data = state.load_state()
    
    print("Analyzing recent performance...")
    shorts = state_data.get("shorts", {})
    for date_key, date_shorts in shorts.items():
        for slot_data in date_shorts.values():
            if isinstance(slot_data, dict) and "video_id" in slot_data:
                video_id = slot_data["video_id"]
                metadata = {
                    "template": "unknown",
                    "voice": "elevenlabs",
                    "posting_time": "auto",
                    "background_id": "random",
                    "cta_index": 0,
                    "title_pattern": "varied",
                }
                _ = analyzer.analyze_short_performance(video_id, metadata)

    # Get long videos
    longs = state_data.get("longs", {})
    for date_key, long_data in longs.items():
        if isinstance(long_data, dict) and "video_id" in long_data:
            video_id = long_data["video_id"]
            metadata = {"length_seconds": 300}
            _ = analyzer.analyze_long_performance(video_id, metadata)

    # Get recommendations
    recommendations = analyzer.get_recommendations()
    print("\nOptimization Recommendations:")
    print(f"Best templates: {recommendations['best_templates']}")
    print(f"Best voices: {recommendations['best_voices']}")
    print(f"Best posting times: {recommendations['best_posting_times']}")

    # Update strategy
    if optimizer.should_update_strategy():
        optimizer.update_strategy()
        print("\nStrategy updated based on analysis.")

    # Check risk level
    risk_level = risk_manager.get_risk_level()
    print(f"\nCurrent risk level: {risk_level}")
    if risk_level != "low":
        print("Risk mitigation recommendations:")
        for rec in risk_manager.get_recommendations():
            print(f"  - {rec}")

    print("\nAnalysis complete. Strategy optimized.")


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

    p_analyze = sub.add_parser("analyze")

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

    if args.cmd == "analyze":
        _analyze_and_optimize(cfg, state)
        return 0

    return 2

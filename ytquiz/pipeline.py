from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from ytquiz.config import Config
from ytquiz.dataset.countries import load_countries
from ytquiz.dataset.question_factory import QuizItem, generate_long_questions, generate_short_question
from ytquiz.log import Log
from ytquiz.media.backgrounds import pick_background
from ytquiz.media.music import pick_music_track
from ytquiz.media.overlays import make_short_overlays
from ytquiz.media.render_long import render_long_episode
from ytquiz.media.render_short import render_short
from ytquiz.media.thumbnail import make_long_thumbnail
from ytquiz.media.tts import synthesize_voice
from ytquiz.optimizer.planner import Planner
from ytquiz.optimizer.scoring import compute_score
from ytquiz.safety import sanitize_description, sanitize_tags, sanitize_title
from ytquiz.state import StateDB
from ytquiz.utils import ensure_dir, ffprobe_duration_seconds, now_utc, rfc3339, run_cmd
from ytquiz.youtube.analytics import fetch_video_metrics
from ytquiz.youtube.auth import build_youtube_services
from ytquiz.youtube.uploader import set_thumbnail, upload_video


_CTA_VARIANTS = [
    "Comment your answer!",
    "Drop your answer below!",
    "No Googling—comment fast!",
    "Type it in the comments!",
]

_HASHTAGS = ["#quiz", "#trivia", "#shorts", "#generalknowledge", "#challenge"]


def run_pipeline(cfg: Config) -> None:
    log = Log()

    if cfg.kill_switch:
        log.warn("KILL_SWITCH enabled. Exiting without action.")
        return

    ensure_dir(cfg.data_dir)
    ensure_dir(cfg.out_dir)
    ensure_dir(cfg.cache_dir)

    state = StateDB(cfg.data_dir / "state.sqlite3")

    services = build_youtube_services(cfg, log)
    youtube = services["youtube"]
    analytics = services["analytics"]

    countries = load_countries(cfg.datasets_dir, log)

    _update_metrics(cfg=cfg, state=state, youtube=youtube, analytics=analytics, log=log)

    planner = Planner(cfg=cfg, state=state, log=log)
    day = now_utc()
    plans = planner.plan_day(day)

    uploads_done = 0

    for plan in plans.shorts:
        if uploads_done >= cfg.daily_upload_cap:
            log.warn("Daily upload cap reached. Stopping.")
            break
        video_id = _produce_and_upload_short(cfg=cfg, state=state, youtube=youtube, plan=plan, countries=countries, log=log)
        if video_id:
            uploads_done += 1

    if plans.long is not None and uploads_done < cfg.daily_upload_cap:
        _produce_and_upload_long(cfg=cfg, state=state, youtube=youtube, plan=plans.long, countries=countries, log=log)


def _update_metrics(*, cfg: Config, state: StateDB, youtube, analytics, log: Log) -> None:
    rows = state.list_videos_needing_metrics(
        min_age_hours=24,
        max_days=45,
        update_every_hours=24,
        limit=60,
    )
    if not rows:
        log.info("No videos need analytics update.")
        return

    now = now_utc()

    for r in rows:
        video_id = str(r["video_id"])
        publish_s = str(r["published_at"])
        try:
            publish_dt = datetime.fromisoformat(publish_s)
        except Exception:
            publish_dt = now - timedelta(days=2)

        metrics = fetch_video_metrics(
            analytics=analytics,
            youtube=youtube,
            channel_id=cfg.channel_id,
            video_id=video_id,
            publish_dt=publish_dt,
            lookback_days=cfg.analytics_lookback_days,
            log=log,
        )
        if not metrics:
            continue

        try:
            age_hours = max(0.1, (now - publish_dt).total_seconds() / 3600.0)
        except Exception:
            age_hours = 24.0
        metrics["ageHours"] = float(age_hours)

        vlen = float(r["video_length_seconds"] or 0.0)
        score = compute_score(metrics, vlen)
        state.update_metrics(video_id=video_id, metrics=metrics, score=score)
        time.sleep(0.7)


def _produce_and_upload_short(*, cfg: Config, state: StateDB, youtube, plan, countries, log: Log) -> str | None:
    rng = random.Random()
    rng.seed(int(now_utc().timestamp()) ^ (hash(plan.topic_id) & 0xFFFFFFFF))

    item = generate_short_question(
        rng=rng,
        state=state,
        countries=countries,
        topic_id=plan.topic_id,
        template_id=plan.template_id,
        cd_bucket=plan.cd_bucket,
        similarity_window=cfg.similarity_window,
        answer_cooldown_days=cfg.answer_cooldown_days,
    )

    # voice reads the FULL question (and a very short CTA)
    cta = rng.choice(_CTA_VARIANTS)
    voice_text = f"{item.question_text} {cta}"

    day_slug = now_utc().strftime("%Y-%m-%d")
    out_dir = cfg.out_dir / day_slug / "shorts"
    ensure_dir(out_dir)

    voice_wav = out_dir / f"voice_{item.question_hash[:10]}.wav"
    synthesize_voice(cfg=cfg, voice_gender=plan.voice_gender, text=voice_text, out_wav=voice_wav, rng=rng, log=log)

    # SAFE trim: trims ONLY leading/trailing silence without cutting pauses inside speech
    trimmed_wav = out_dir / f"voice_{item.question_hash[:10]}_trim.wav"
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_wav),
            "-af",
            "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-45dB,"
            "areverse,"
            "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-45dB,"
            "areverse",
            str(trimmed_wav),
        ],
        timeout=180,
        retries=1,
        retry_sleep=1.0,
    )
    voice_wav = trimmed_wav

    voice_dur = ffprobe_duration_seconds(voice_wav)
    read_seconds = max(1.0, float(voice_dur))

    # NEW pacing:
    # After voice finishes, show a short timer (3–5s) then answer immediately
    base_cd = 3 + int(round(2.0 * float(item.difficulty)))
    jitter = rng.choice([-1, 0, 0, 0, 1])
    countdown = max(3, min(5, base_cd + jitter))

    bg_image, bg_source = pick_background(
        rng=rng,
        backgrounds_dir=cfg.backgrounds_dir,
        out_dir=out_dir,
        width=cfg.video_size[0],
        height=cfg.video_size[1],
    )

    music_enabled = plan.music_mode == "on"
    music_path = pick_music_track(rng, cfg.music_dir) if music_enabled else None

    overlays = make_short_overlays(
        out_dir=out_dir,
        font_file=cfg.overlay_font_file,
        question=item.question_text,
        answer=item.answer_text,
        options=item.options,
        correct_index=item.correct_option_index,
        template_id=plan.template_id,
        rng=rng,
        hint_text=item.hint_text,
    )

    out_mp4 = out_dir / f"short_{item.question_hash[:10]}.mp4"
    video_len = render_short(
        cfg=cfg,
        bg_image=bg_image,
        overlays=overlays,
        voice_wav=voice_wav,
        music_enabled=music_enabled,
        music_path=music_path,
        read_seconds=read_seconds,
        countdown_seconds=countdown,
        out_mp4=out_mp4,
        log=log,
    )

    meta = _short_metadata(item=item, countdown=countdown, rng=rng)
    title = sanitize_title(meta["title"])
    description = sanitize_description(meta["description"])
    tags = sanitize_tags(meta["tags"])

    if cfg.dry_run:
        fake_id = f"DRYRUN_{item.question_hash[:12]}"
        state.insert_video(
            video_id=fake_id,
            kind="short",
            title=title,
            description=description,
            scheduled_at=rfc3339(plan.scheduled_at),
            published_at=rfc3339(plan.scheduled_at),
            template_id=plan.template_id,
            topic_id=plan.topic_id,
            question_text=item.question_text,
            answer_text=item.answer_text,
            question_hash=item.question_hash,
            voice_gender=plan.voice_gender,
            countdown_seconds=countdown,
            video_length_seconds=video_len,
            music_mode=plan.music_mode,
            bg_source=bg_source,
            features={
                "slot_id": plan.slot_id,
                "cd_bucket": plan.cd_bucket,
                "publish_immediately": bool(plan.publish_immediately),
                "cta_variant": "cta_v1",
            },
        )
        log.info(f"DRY_RUN: would upload short: {title}")
        return fake_id

    privacy = "public" if plan.publish_immediately else "private"
    publish_at = None if plan.publish_immediately else plan.scheduled_at

    video_id = upload_video(
        youtube=youtube,
        file_path=str(out_mp4),
        title=title,
        description=description,
        tags=tags,
        category_id=cfg.category_id,
        privacy_status=privacy,
        publish_at=publish_at,
        made_for_kids=cfg.made_for_kids,
        log=log,
    )

    state.insert_video(
        video_id=video_id,
        kind="short",
        title=title,
        description=description,
        scheduled_at=rfc3339(plan.scheduled_at),
        published_at=rfc3339(plan.scheduled_at if not plan.publish_immediately else now_utc()),
        template_id=plan.template_id,
        topic_id=plan.topic_id,
        question_text=item.question_text,
        answer_text=item.answer_text,
        question_hash=item.question_hash,
        voice_gender=plan.voice_gender,
        countdown_seconds=countdown,
        video_length_seconds=video_len,
        music_mode=plan.music_mode,
        bg_source=bg_source,
        features={
            "slot_id": plan.slot_id,
            "cd_bucket": plan.cd_bucket,
            "publish_immediately": bool(plan.publish_immediately),
            "cta_variant": "cta_v1",
        },
    )

    time.sleep(rng.uniform(4.0, 12.0))
    return video_id


def _produce_and_upload_long(*, cfg: Config, state: StateDB, youtube, plan, countries, log: Log) -> str | None:
    rng = random.Random()
    rng.seed(int(now_utc().timestamp()) ^ 0xA5A5A5A5)

    long_topics = ["capitals", "continents", "elements", "science", "math"]
    compilation_rows = state.select_compilation_short_items(limit=cfg.long_questions, max_days=120)
    questions: list[QuizItem] = []
    for r in compilation_rows:
        try:
            cd = int(r["countdown_seconds"] or 4)
        except Exception:
            cd = 4
        questions.append(
            QuizItem(
                topic_id=str(r["topic_id"]),
                question_text=str(r["question_text"]),
                answer_text=str(r["answer_text"]),
                options=None,
                correct_option_index=None,
                hint_text=None,
                difficulty=0.6,
                countdown_seconds=max(3, min(6, cd)),
                question_hash=str(r["question_hash"] or ""),
            )
        )

    if len(questions) < cfg.long_questions:
        extra = generate_long_questions(rng=rng, state=state, countries=countries, topics=long_topics, count=cfg.long_questions - len(questions))
        questions.extend(extra)

    day_slug = now_utc().strftime("%Y-%m-%d")
    out_dir = cfg.out_dir / day_slug / "long"
    ensure_dir(out_dir)

    cfg_long = cfg.with_overrides(video_size=(1920, 1080))

    bg_image, bg_source = pick_background(
        rng=rng,
        backgrounds_dir=cfg.backgrounds_dir,
        out_dir=out_dir,
        width=cfg_long.video_size[0],
        height=cfg_long.video_size[1],
    )

    music_enabled = plan.music_mode == "on"
    music_path = pick_music_track(rng, cfg.music_dir) if music_enabled else None

    out_mp4 = out_dir / f"long_{day_slug}.mp4"
    video_len = render_long_episode(
        cfg=cfg_long,
        bg_image=bg_image,
        questions=[q.__dict__ for q in questions],
        voice_gender=plan.voice_gender,
        music_mode=plan.music_mode,
        music_path=music_path,
        out_mp4=out_mp4,
        rng=rng,
        log=log,
    )

    logo_path = (cfg.brand_dir / "logo.png") if (cfg.brand_dir / "logo.png").exists() else None
    thumb = out_dir / f"thumb_{day_slug}.jpg"

    thumb_headline = rng.choice(
        [
            f"{cfg.long_questions} QUESTION QUIZ",
            "CAN YOU BEAT THE TIMER?",
            "TRIVIA CHALLENGE",
            "QUICK QUIZ SHOWDOWN",
        ]
    )
    thumb_sub = rng.choice(
        [
            "GEOGRAPHY | SCIENCE | MORE",
            "COMMENT YOUR SCORE",
            "NO GOOGLING",
            "HOW MANY DID YOU GET?",
        ]
    )

    make_long_thumbnail(
        rng=rng,
        bg_image=bg_image,
        font_file=cfg.overlay_font_file,
        logo_path=logo_path,
        headline=thumb_headline,
        subline=thumb_sub,
        out_jpg=thumb,
    )

    meta = _long_metadata(day_slug=day_slug, rng=rng, questions_count=cfg.long_questions)
    title = sanitize_title(meta["title"])
    description = sanitize_description(meta["description"])
    tags = sanitize_tags(meta["tags"])

    if cfg.dry_run:
        fake_id = f"DRYRUN_LONG_{day_slug}"
        state.insert_video(
            video_id=fake_id,
            kind="long",
            title=title,
            description=description,
            scheduled_at=rfc3339(plan.scheduled_at),
            published_at=rfc3339(plan.scheduled_at),
            template_id=0,
            topic_id="long",
            question_text="",
            answer_text="",
            question_hash=f"long_{day_slug}",
            voice_gender=plan.voice_gender,
            countdown_seconds=0,
            video_length_seconds=video_len,
            music_mode=plan.music_mode,
            bg_source=bg_source,
            features={"slot_id": plan.slot_id},
        )
        log.info(f"DRY_RUN: would upload long: {title}")
        return fake_id

    privacy = "private"
    publish_at = plan.scheduled_at

    video_id = upload_video(
        youtube=youtube,
        file_path=str(out_mp4),
        title=title,
        description=description,
        tags=tags,
        category_id=cfg.category_id,
        privacy_status=privacy,
        publish_at=publish_at,
        made_for_kids=cfg.made_for_kids,
        log=log,
    )

    set_thumbnail(youtube=youtube, video_id=video_id, thumbnail_path=str(thumb), log=log)

    state.insert_video(
        video_id=video_id,
        kind="long",
        title=title,
        description=description,
        scheduled_at=rfc3339(plan.scheduled_at),
        published_at=rfc3339(plan.scheduled_at),
        template_id=0,
        topic_id="long",
        question_text="",
        answer_text="",
        question_hash=f"long_{day_slug}",
        voice_gender=plan.voice_gender,
        countdown_seconds=0,
        video_length_seconds=video_len,
        music_mode=plan.music_mode,
        bg_source=bg_source,
        features={"slot_id": plan.slot_id},
    )

    time.sleep(rng.uniform(6.0, 15.0))
    return video_id


def _short_metadata(*, item: QuizItem, countdown: int, rng: random.Random) -> dict[str, object]:
    emoji = rng.choice(["🔥", "🤯", "🌍", "🧠", "⚡", "🎯"])
    topic = item.topic_id

    title_templates = {
        "capitals": [
            "Can you guess it in {n}s? {e}",
            "Capital Quiz: {n}s only! {e}",
            "Guess it fast! {e}",
        ],
        "continents": [
            "Which continent is it? {n}s {e}",
            "Continent Quiz: {n}s only {e}",
        ],
        "currencies": [
            "Currency Quiz: {n}s only! {e}",
            "Guess the currency country! {e}",
        ],
        "elements": [
            "Science Quiz: {n}s only {e}",
            "Symbol Challenge: {n}s {e}",
        ],
        "science": [
            "Quick Science Question ({n}s) {e}",
            "Science Trivia Sprint {e}",
        ],
        "math": [
            "Mental Math ({n}s) {e}",
            "Fast Math Challenge {e}",
        ],
        "truefalse": [
            "True or False? {n}s only {e}",
            "Is this true? {n}s {e}",
        ],
    }

    templates = title_templates.get(topic, ["Quick Quiz ({n}s) {e}"])
    title = rng.choice(templates).format(n=countdown, e=emoji)

    base_desc = [
        "Answer before the timer ends and comment below.",
        "Try it without Googling. Comment your answer.",
        "How fast can you solve it? Drop your answer in the comments.",
        "Watch till the end for the answer (it flashes quickly).",
    ]
    desc = rng.choice(base_desc)
    hashtags = " ".join(_HASHTAGS)

    description = f"{desc}\n\n{hashtags}\n"
    tags = [
        "quiz",
        "trivia",
        "general knowledge",
        "shorts",
        "challenge",
        "guess",
        "brain teaser",
    ]
    if topic == "capitals":
        tags += ["geography", "capitals", "countries"]
    elif topic == "continents":
        tags += ["geography", "continents", "countries"]
    elif topic == "currencies":
        tags += ["currency", "geography", "countries"]
    elif topic == "elements":
        tags += ["science", "chemistry", "elements"]
    elif topic == "science":
        tags += ["science", "space", "facts"]
    elif topic == "math":
        tags += ["math", "mental math", "fast"]
    elif topic == "truefalse":
        tags += ["facts", "true or false", "trivia"]

    return {"title": title, "description": description, "tags": tags}


def _long_metadata(*, day_slug: str, rng: random.Random, questions_count: int) -> dict[str, object]:
    emoji = rng.choice(["🔥", "🧠", "🎯", "🌍", "⚡", "🤯"])
    qcount = int(questions_count)

    title_templates = [
        f"{qcount} Question Quiz — Can You Beat the Timer? {emoji}",
        f"Geography & Science Quiz ({qcount} Questions) {emoji}",
        f"Ultimate Trivia Challenge: {qcount} Questions {emoji}",
        f"Beat the Clock: {qcount} Quick Questions {emoji}",
        f"Try Not to Lose: {qcount}-Question Quiz {emoji}",
    ]
    title = rng.choice(title_templates)

    description = (
        "A fast-paced quiz episode.\n"
        "Try to answer before the timer ends.\n\n"
        + " ".join(_HASHTAGS[:4])
        + "\n"
    )
    tags = [
        "quiz",
        "trivia",
        "general knowledge",
        "geography",
        "science",
        "challenge",
        "questions",
    ]
    return {"title": title, "description": description, "tags": tags}

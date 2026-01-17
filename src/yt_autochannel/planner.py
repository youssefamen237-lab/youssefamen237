from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pytz

from .analytics.optimizer import Bandit
from .config import Settings
from .db.sqlite_db import DB, utc_now_iso
from .dedupe import check_duplicate
from .models import PlannedVideo
from .question_bank import QuestionBank, QA
from .render.backgrounds import ensure_backgrounds, pick_background
from .render.music import ensure_music, pick_music
from .safety import ContentSafety
from .seo import generate_seo
from .templates import SHORT_TEMPLATES
from .utils.text_utils import normalize_for_dupe, stable_hash
from .utils.time_utils import daily_time_slots_utc, now_utc


def _voice_gender_for_short(settings: Settings, db: DB) -> str:
    """AB test (first N days) then stick to winner (with small exploration)."""
    ab_start = db.get_state("ab_start_utc")
    now = now_utc()
    if ab_start is None:
        db.set_state("ab_start_utc", now.isoformat())
        ab_start_dt = now
    else:
        try:
            ab_start_dt = datetime.fromisoformat(ab_start)
            if ab_start_dt.tzinfo is None:
                ab_start_dt = ab_start_dt.replace(tzinfo=pytz.UTC)
        except Exception:
            ab_start_dt = now

    if (now - ab_start_dt) <= timedelta(days=settings.ab_test_days):
        # Count recent shorts by voice
        rows = db.list_recent_videos(days=settings.ab_test_days + 1)
        male = 0
        female = 0
        for r in rows:
            if r["kind"] != "short":
                continue
            vg = (r["voice_gender"] or "").lower()
            if vg == "male":
                male += 1
            elif vg == "female":
                female += 1
        if male > female:
            return "female"
        if female > male:
            return "male"
        return random.choice(["male", "female"])

    winner = db.get_state("voice_winner")
    if winner in {"male", "female"}:
        if random.random() < 0.10:
            return "female" if winner == "male" else "male"
        return winner

    return random.choice(["male", "female"])


def _reserve_duplicates(db: DB, qa: QA, title: str) -> None:
    qn = normalize_for_dupe(qa.question)
    an = normalize_for_dupe(qa.answer)
    tn = normalize_for_dupe(title)
    db.add_duplicate("question", qn, stable_hash(qn))
    db.add_duplicate("answer", an, stable_hash(an))
    db.add_duplicate("title", tn, stable_hash(tn))


def plan_today(settings: Settings, db: DB) -> List[PlannedVideo]:
    """Create plans and write them into SQLite (videos + duplicates)."""
    repo_root = Path(settings.repo_root)
    assets_dir = repo_root / settings.assets_dir
    data_dir = repo_root / settings.data_dir

    bg_dir = assets_dir / "backgrounds"
    music_dir = assets_dir / "music"
    ensure_backgrounds(bg_dir)
    ensure_music(music_dir)

    safety = ContentSafety.from_file(str(data_dir / settings.safety_blocklist_file))
    bank = QuestionBank(data_dir)

    tz = pytz.timezone(settings.timezone)
    local_now = datetime.now(tz=tz)

    # Publish times (UTC) for daily shorts
    slots_utc = daily_time_slots_utc(
        settings.timezone,
        local_now,
        settings.shorts_time_slots_local,
        settings.shorts_jitter_seconds,
    )

    # First run: publish first short ASAP
    if db.get_state("first_run_done") != "1":
        slots_utc = sorted(slots_utc)
        slots_utc[0] = now_utc() + timedelta(minutes=2)

    bandit = Bandit(db)

    planned: List[PlannedVideo] = []

    for i in range(settings.daily_shorts):
        publish_at = slots_utc[i % len(slots_utc)]

        template_id = bandit.choose("template", SHORT_TEMPLATES, epsilon=0.25)
        music_enabled = settings.music_enabled_default and (bandit.choose("music", ["on", "off"], epsilon=0.20) == "on")
        if template_id == "zoom_reveal":
            music_enabled = False

        voice_gender = _voice_gender_for_short(settings, db)

        bg = pick_background(bg_dir, db=db)
        music = pick_music(music_dir) if music_enabled else None

        qa: Optional[QA] = None
        seo_title = ""
        seo_desc = ""
        seo_tags: List[str] = []

        # Try multiple times to satisfy safety + anti-duplicate + cooldown
        for _ in range(80):
            candidate = bank.random_qa(template_id=template_id)
            if not safety.is_safe(candidate.question) or not safety.is_safe(candidate.answer):
                continue

            # Duplicates on question
            if check_duplicate(db, "question", candidate.question, settings.fuzzy_threshold).is_duplicate:
                continue

            # Answer cooldown + duplicates
            ans_dupe = check_duplicate(db, "answer", candidate.answer, settings.fuzzy_threshold)
            if ans_dupe.is_duplicate:
                recent_answers = db.recent_texts(kind="answer", days=settings.answer_cooldown_days)
                if normalize_for_dupe(candidate.answer) in recent_answers:
                    continue

            seo = generate_seo(candidate, template_id=template_id)
            if check_duplicate(db, "title", seo.title, settings.fuzzy_threshold).is_duplicate:
                continue

            qa = candidate
            seo_title = seo.title
            seo_desc = seo.description
            seo_tags = seo.tags
            break

        if qa is None:
            qa = bank.fallback_qa()
            seo = generate_seo(qa, template_id="classic_countdown")
            seo_title, seo_desc, seo_tags = seo.title, seo.description, seo.tags
            template_id = "classic_countdown"

        planned_video = PlannedVideo(
            kind="short",
            publish_at_utc=publish_at,
            template_id=template_id,
            topic=qa.topic,
            difficulty=qa.difficulty,
            countdown_seconds=settings.countdown_seconds,
            voice_gender=voice_gender,
            music_enabled=music_enabled,
            bg_image_path=bg,
            bg_image_id=bg.name,
            music_path=music,
            music_track_id=(music.name if music else ""),
            question=qa.question,
            answer=qa.answer,
            choices=qa.choices,
            correct_index=qa.correct_index,
            title=seo_title,
            description=seo_desc,
            tags=seo_tags,
        )
        planned.append(planned_video)

        # Reserve duplicates immediately (prevents duplicates within same run/day)
        _reserve_duplicates(db, qa, seo_title)

        extra = {}
        if qa.choices is not None:
            extra = {"choices": qa.choices, "correct_index": qa.correct_index}

        db.insert_video_plan(
            {
                "kind": "short",
                "publish_at_utc": publish_at.isoformat(),
                "template_id": template_id,
                "topic": qa.topic,
                "difficulty": qa.difficulty,
                "countdown_seconds": settings.countdown_seconds,
                "voice_gender": voice_gender,
                "music_track_id": (music.name if music else ""),
                "bg_image_id": bg.name,
                "title_style_id": bandit.choose("title_style", ["a", "b", "c"], epsilon=0.30),
                "title": seo_title,
                "description": seo_desc,
                "tags_csv": ",".join(seo_tags),
                "question": qa.question,
                "answer": qa.answer,
                "extra_json": (json.dumps(extra) if extra else ""),
                "created_at_utc": utc_now_iso(),
                "status": "planned",
                "error": "",
            }
        )

    # Optional long video planning
    if local_now.weekday() in settings.long_days_of_week and db.get_state("first_run_done") == "1":
        from .utils.time_utils import parse_hhmm

        h, m = parse_hhmm(settings.long_time_local)
        local_dt = tz.localize(datetime(local_now.year, local_now.month, local_now.day, h, m, 0))
        local_dt = local_dt + timedelta(seconds=random.randint(-settings.long_jitter_seconds, settings.long_jitter_seconds))
        publish_at = local_dt.astimezone(pytz.UTC)

        episode_qas = bank.random_episode_qas(count=80)
        title = bank.long_title_from_topics([q.topic for q in episode_qas])
        desc = bank.long_description(title)
        tags = bank.long_tags()

        bg = pick_background(bg_dir, db=db)
        music = pick_music(music_dir)

        planned.append(
            PlannedVideo(
                kind="long",
                publish_at_utc=publish_at,
                template_id="long_episode",
                topic="Mixed Trivia",
                difficulty="Mixed",
                countdown_seconds=settings.countdown_seconds,
                voice_gender=_voice_gender_for_short(settings, db),
                music_enabled=True,
                bg_image_path=bg,
                music_path=music,
                episode_qas=episode_qas,
                title=title,
                description=desc,
                tags=tags,
            )
        )

        payload = [{"q": q.question, "a": q.answer, "topic": q.topic} for q in episode_qas]
        db.insert_video_plan(
            {
                "kind": "long",
                "publish_at_utc": publish_at.isoformat(),
                "template_id": "long_episode",
                "topic": "Mixed Trivia",
                "difficulty": "Mixed",
                "countdown_seconds": settings.countdown_seconds,
                "voice_gender": _voice_gender_for_short(settings, db),
                "music_track_id": (music.name if music else ""),
                "bg_image_id": bg.name,
                "title_style_id": "long",
                "title": title,
                "description": desc,
                "tags_csv": ",".join(tags),
                "question": json.dumps(payload),
                "answer": "",
                "extra_json": "",
                "created_at_utc": utc_now_iso(),
                "status": "planned",
                "error": "",
            }
        )

    return planned

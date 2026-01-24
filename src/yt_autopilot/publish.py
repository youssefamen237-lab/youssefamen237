\
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import create_upload_record, init_db, mark_upload_failed, mark_upload_success
from .logging_utils import setup_logging
from .metadata_gen import generate_metadata
from .question_gen import generate_question
from .render import render_long_compilation, render_short
from .scheduler import refresh_schedule
from .settings import load_config, load_secrets
from .state import ChannelState, iso_utc, parse_iso_utc, utc_now
from .utils.random_utils import weighted_choice
from .youtube_auth import OAuthCandidate
from .youtube_upload import upload_video

logger = logging.getLogger(__name__)


def _oauth_candidates_for_upload(secrets: Any) -> List[OAuthCandidate]:
    cands: List[OAuthCandidate] = []
    if secrets.yt_client_id_1 and secrets.yt_client_secret_1 and secrets.yt_refresh_token_1:
        cands.append(OAuthCandidate(secrets.yt_client_id_1, secrets.yt_client_secret_1, secrets.yt_refresh_token_1))
    if secrets.yt_client_id_2 and secrets.yt_client_secret_2 and secrets.yt_refresh_token_2:
        cands.append(OAuthCandidate(secrets.yt_client_id_2, secrets.yt_client_secret_2, secrets.yt_refresh_token_2))
    if not cands:
        raise RuntimeError("Missing YouTube OAuth secrets for upload (client id/secret/refresh token)")
    return cands


def _pick_voice(config: Dict[str, Any]) -> Dict[str, Any]:
    voices = (config.get("voices") or {}).get("profiles") or []
    weights = (config.get("voices") or {}).get("weights") or {}
    if not voices:
        raise RuntimeError("No voice profiles configured")
    by_id = {v.get("id"): v for v in voices if v.get("id")}
    if not weights:
        return random.choice(voices)
    vid = weighted_choice({k: float(v) for k, v in weights.items() if k in by_id})
    return by_id.get(vid) or random.choice(voices)


def _pick_cta(config: Dict[str, Any]) -> Tuple[str, str]:
    cta_cfg = config.get("cta") or {}
    phrases = cta_cfg.get("phrases") or []
    weights = cta_cfg.get("weights") or {}
    by_id = {p.get("id"): p for p in phrases if p.get("id")}
    if weights and by_id:
        cid = weighted_choice({k: float(v) for k, v in weights.items() if k in by_id})
        txt = str((by_id.get(cid) or {}).get("text") or "Comment your answer!")
        return cid, txt
    if phrases:
        p = random.choice(phrases)
        return str(p.get("id") or "cta"), str(p.get("text") or "Comment your answer!")
    return "cta", "Comment your answer!"


def _due_items(state: ChannelState, due_window_minutes: int) -> List[Dict[str, Any]]:
    now = utc_now()
    window = timedelta(minutes=due_window_minutes)
    due: List[Dict[str, Any]] = []
    for it in state.schedule:
        if it.get("status") != "pending":
            continue
        try:
            dt = parse_iso_utc(it["due_utc"])
        except Exception:
            continue
        if now >= dt and now <= dt + window:
            due.append(it)
    due.sort(key=lambda x: x.get("due_utc") or "")
    return due


def _publish_one_short(config: Dict[str, Any], secrets: Any, oauth_candidates: List[OAuthCandidate]) -> None:
    qid, qitem = generate_question(config, secrets)
    voice_profile = _pick_voice(config)
    voice_id = str(voice_profile.get("id") or "")
    cta_id, cta_text = _pick_cta(config)

    title, desc, tags, hashtags, meta_provider = generate_metadata(
        config, secrets, kind="short", question=qitem.question, category=qitem.category
    )

    out_dir = Path("outputs") / "shorts"
    out_dir.mkdir(parents=True, exist_ok=True)

    rr = render_short(
        config=config,
        question=qitem.question,
        answer=qitem.answer,
        options=qitem.options,
        template_id=qitem.template_id,
        voice_profile=voice_profile,
        cta_text=cta_text,
        out_dir=out_dir,
    )

    pub_cfg = config.get("publishing") or {}
    upload_id = create_upload_record(
        kind="short",
        title=title,
        description=desc,
        tags=tags,
        hashtags=hashtags,
        template_id=qitem.template_id,
        voice_id=voice_id,
        cta_id=cta_id,
        question_id=qid,
        duration_seconds=rr.duration_seconds,
        scheduled_for_utc=None,
    )

    try:
        video_id = upload_video(
            oauth_candidates=oauth_candidates,
            video_path=rr.video_path,
            title=title,
            description=desc,
            tags=tags,
            category_id=str(pub_cfg.get("category_id") or "24"),
            privacy_status=str(pub_cfg.get("privacy_status") or "public"),
            made_for_kids=bool(pub_cfg.get("made_for_kids", False)),
            thumbnail_path=rr.thumbnail_path,
        )
        mark_upload_success(upload_id, video_id)
        logger.info("Uploaded short video_id=%s template=%s voice=%s provider=%s", video_id, qitem.template_id, voice_id, qitem.llm_provider)
    except Exception as e:
        mark_upload_failed(upload_id, str(e))
        logger.error("Short upload failed: %s", e)
        raise


def _publish_one_long(config: Dict[str, Any], secrets: Any, oauth_candidates: List[OAuthCandidate]) -> None:
    voice_profile = _pick_voice(config)
    voice_id = str(voice_profile.get("id") or "")

    content_cfg = config.get("content") or {}
    target_minutes = float(content_cfg.get("long_target_minutes", 6))
    q_seconds = float(content_cfg.get("long_question_seconds", 9.0))
    ans_seconds = float(content_cfg.get("long_answer_seconds", 2.0))
    per_q = q_seconds + ans_seconds
    count = max(18, min(60, int((target_minutes * 60) / max(1.0, per_q))))

    items: List[Dict[str, Any]] = []
    for _ in range(count):
        qid, qitem = generate_question(config, secrets)
        items.append(
            {
                "question_id": qid,
                "template_id": qitem.template_id,
                "question": qitem.question,
                "answer": qitem.answer,
                "options": qitem.options,
                "category": qitem.category,
            }
        )

    topic = random.choice(["General Knowledge", "Fun Trivia", "Quick Quiz", "Brain Teasers"])
    title, desc, tags, hashtags, meta_provider = generate_metadata(
        config, secrets, kind="long", long_topic=topic, long_count=len(items), category="general"
    )

    out_dir = Path("outputs") / "long"
    out_dir.mkdir(parents=True, exist_ok=True)

    rr = render_long_compilation(
        config=config,
        items=items,
        voice_profile=voice_profile,
        out_dir=out_dir,
        title_slide=f"{topic} — {len(items)} Questions",
    )

    pub_cfg = config.get("publishing") or {}
    upload_id = create_upload_record(
        kind="long",
        title=title,
        description=desc,
        tags=tags,
        hashtags=hashtags,
        template_id="compilation",
        voice_id=voice_id,
        cta_id=None,
        question_id=None,
        duration_seconds=rr.duration_seconds,
        scheduled_for_utc=None,
    )

    try:
        video_id = upload_video(
            oauth_candidates=oauth_candidates,
            video_path=rr.video_path,
            title=title,
            description=desc,
            tags=tags,
            category_id=str(pub_cfg.get("category_id") or "24"),
            privacy_status=str(pub_cfg.get("privacy_status") or "public"),
            made_for_kids=bool(pub_cfg.get("made_for_kids", False)),
            thumbnail_path=rr.thumbnail_path,
        )
        mark_upload_success(upload_id, video_id)
        logger.info("Uploaded long video_id=%s voice=%s", video_id, voice_id)
    except Exception as e:
        mark_upload_failed(upload_id, str(e))
        logger.error("Long upload failed: %s", e)
        raise


def run() -> None:
    setup_logging("publish")
    if str(os.getenv("PAUSE_PUBLISHING") or "").strip().lower() in {"1", "true", "yes", "on"}:
        logger.warning("PAUSE_PUBLISHING is enabled. Exiting without uploading.")
        return
    secrets = load_secrets()
    config = load_config()
    init_db()

    state = ChannelState.load()
    state.last_run_utc = iso_utc(utc_now())

    oauth_candidates = _oauth_candidates_for_upload(secrets)

    pub_cfg = config.get("publishing") or {}
    due_window = int(pub_cfg.get("due_window_minutes", 18))
    max_uploads = int(pub_cfg.get("max_uploads_per_run", 2))

    # First run bootstrap: publish 1 short + 1 long immediately
    if not state.bootstrapped:
        logger.info("Bootstrap run: publishing 1 short + 1 long immediately")
        _publish_one_short(config, secrets, oauth_candidates)
        _publish_one_long(config, secrets, oauth_candidates)
        state.bootstrapped = True
        state.bootstrapped_at = iso_utc(utc_now())
        state.inc_daily_counter("shorts_posted", 1)
        state.inc_weekly_counter("longs_posted", 1)
        state.save()
        return

    refresh_schedule(state, config)
    due = _due_items(state, due_window_minutes=due_window)

    uploads_done = 0
    for it in due:
        if uploads_done >= max_uploads:
            break

        kind = it.get("kind")
        if kind == "short":
            # hard cap
            if state.get_daily_counter("shorts_posted") >= int(pub_cfg.get("max_shorts_per_day_hard_cap", 6)):
                it["status"] = "skipped"
                continue
            try:
                _publish_one_short(config, secrets, oauth_candidates)
                it["status"] = "posted"
                state.inc_daily_counter("shorts_posted", 1)
                uploads_done += 1
            except Exception:
                it["status"] = "failed"
        elif kind == "long":
            if state.get_weekly_counter("longs_posted") >= int(pub_cfg.get("max_longs_per_week_hard_cap", 5)):
                it["status"] = "skipped"
                continue
            try:
                _publish_one_long(config, secrets, oauth_candidates)
                it["status"] = "posted"
                state.inc_weekly_counter("longs_posted", 1)
                uploads_done += 1
            except Exception:
                it["status"] = "failed"
        else:
            it["status"] = "skipped"

    state.prune_old_counters()
    state.save()
    logger.info("Publish run done. uploads_done=%s due=%s", uploads_done, len(due))


if __name__ == "__main__":
    run()

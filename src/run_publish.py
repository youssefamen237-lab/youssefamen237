from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .logger import setup_logging
from .config import load_yaml
from .state import load_state, save_state, record_upload
from .utils.time_utils import utcnow, plan_times_for_day, to_tz
from .generators.question_generator import generate_quiz
from .tts.tts_manager import synthesize_with_fallback
from .video.assets import pick_background, pick_local_music
from .video.short_maker import render_short
from .video.long_maker import render_long
from .video.thumbnail import generate_thumbnail
from .youtube.metadata import build_short_metadata, build_long_metadata
from .youtube.uploader import upload_video, set_thumbnail

log = logging.getLogger("run_publish")


def _sleep_between(cfg: Dict[str, Any]) -> None:
    mn = int(cfg["safety"]["min_seconds_between_uploads"])
    mx = int(cfg["safety"]["max_seconds_between_uploads"])
    time.sleep(random.randint(mn, mx))


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _should_publish_long(today_local_weekday: int) -> bool:
    # 4/week: Tue, Thu, Sat, Sun
    return today_local_weekday in {1, 3, 5, 6}


def publish_shorts(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    tz_name = str(cfg["publishing"]["target_timezone"])
    now = utcnow()
    perf_hours = state.get("performance", {}).get("publish_hours", {}) or {}
    windows = cfg["publishing"]["candidate_windows"]
    count = int(cfg["publishing"]["shorts_per_day"])
    lead_min = int(cfg["publishing"]["min_schedule_lead_minutes"])

    local_times = plan_times_for_day(
        now_utc=now,
        tz_name=tz_name,
        candidate_windows=windows,
        count=count,
        min_lead_minutes=lead_min,
        perf_publish_hours=perf_hours,
    )

    first_run = not bool(state.get("uploads"))
    temp_dir = Path(cfg["assets"]["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)

    shorts_music = pick_local_music(cfg, state)

    for idx, local_dt in enumerate(local_times, start=1):
        item = generate_quiz(cfg, state)
        meta = build_short_metadata(cfg, item)

        # Build TTS text (keep it short)
        tts_text = f"{item.question} {item.cta}"
        audio, voice_id, engine = synthesize_with_fallback(cfg, state, text=tts_text, out_dir=temp_dir, basename=f"short_{idx}_{item.qid}")

        bg = pick_background(cfg, state, width=int(cfg["content"]["short"]["width"]), height=int(cfg["content"]["short"]["height"]))
        out_video = temp_dir / f"short_{idx}_{item.qid}.mp4"
        work_dir = temp_dir / f"work_short_{idx}_{item.qid}"
        work_dir.mkdir(parents=True, exist_ok=True)

        render_short(
            cfg,
            item=item,
            voice_audio=audio,
            background_image=bg,
            music_audio=shorts_music,
            out_path=out_video,
            work_dir=work_dir,
        )

        thumb_path = temp_dir / f"thumb_short_{idx}_{item.qid}.jpg"
        generate_thumbnail(title=meta["title"], out_path=thumb_path, background_image=bg)

        # First run: publish the first short immediately (if possible)
        publish_at = None
        privacy = "public"
        notify = bool(cfg["publishing"]["notify_subscribers_shorts"])
        if not (first_run and idx == 1):
            publish_at = local_dt.astimezone(timezone.utc)
            privacy = str(cfg["publishing"]["default_privacy"])
        publish_hour_local = int(local_dt.hour)

        video_id = upload_video(
            video_path=out_video,
            metadata=meta,
            publish_at=publish_at,
            privacy_status=privacy,
            notify_subscribers=notify,
            made_for_kids=bool(cfg["content"]["made_for_kids"]),
            contains_synthetic_media=bool(cfg["content"]["contains_synthetic_media"]),
        )
        try:
            set_thumbnail(video_id, thumb_path)
        except Exception as e:
            log.warning("Thumbnail set failed: %s", e)

        record_upload(
            state,
            {
                "ts": _iso(now),
                "video_id": video_id,
                "kind": "short",
                "template": item.template,
                "voice_id": voice_id,
                "tts_engine": engine,
                "title": meta["title"],
                "publish_at": _iso(publish_at or now),
                "published_at": _iso(publish_at or now),
                "publish_hour_local": publish_hour_local,
                "scheduled": publish_at is not None,
            },
        )

        _sleep_between(cfg)


def publish_long_if_scheduled(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    tz_name = str(cfg["publishing"]["target_timezone"])
    now = utcnow()
    now_local = to_tz(now, tz_name)
    if not _should_publish_long(now_local.weekday()):
        return

    # Build a long compilation length between min/max minutes
    min_m = int(cfg["content"]["long"]["min_minutes"])
    max_m = int(cfg["content"]["long"]["max_minutes"])
    target_m = random.randint(min_m, max_m)
    q_s = float(cfg["content"]["long"]["question_seconds"])
    a_s = float(cfg["content"]["long"]["answer_seconds"])
    seg_s = q_s + a_s
    num_questions = max(15, int((target_m * 60) / seg_s))

    temp_dir = Path(cfg["assets"]["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    work_dir = temp_dir / f"work_long_{int(now.timestamp())}_{random.randint(1000,9999)}"
    work_dir.mkdir(parents=True, exist_ok=True)

    items: List[Any] = []
    voice_audios: List[Path] = []
    bgs: List[Path] = []

    long_music = pick_local_music(cfg, state)

    for i in range(num_questions):
        item = generate_quiz(cfg, state)
        items.append(item)

        # voice: question only (no CTA per segment)
        audio, voice_id, engine = synthesize_with_fallback(
            cfg, state, text=item.question, out_dir=work_dir, basename=f"long_{i+1}_{item.qid}"
        )
        voice_audios.append(audio)

        bg = pick_background(cfg, state, width=int(cfg["content"]["long"]["width"]), height=int(cfg["content"]["long"]["height"]))
        bgs.append(bg)

    meta = build_long_metadata(cfg, items)
    out_video = temp_dir / f"long_{now.date().isoformat()}_{random.randint(1000,9999)}.mp4"
    render_long(
        cfg,
        items=items,
        voice_audios=voice_audios,
        background_images=bgs,
        music_audio=long_music,
        out_path=out_video,
        work_dir=work_dir,
    )

    thumb_path = temp_dir / f"thumb_long_{now.date().isoformat()}_{random.randint(1000,9999)}.jpg"
    generate_thumbnail(title=meta["title"], out_path=thumb_path, background_image=bgs[0] if bgs else None)

    # Schedule the long video in a good window (today)
    windows = cfg["publishing"]["candidate_windows"]
    lead_min = int(cfg["publishing"]["min_schedule_lead_minutes"])
    perf_hours = state.get("performance", {}).get("publish_hours", {}) or {}
    local_times = plan_times_for_day(
        now_utc=now,
        tz_name=tz_name,
        candidate_windows=windows,
        count=1,
        min_lead_minutes=lead_min,
        perf_publish_hours=perf_hours,
    )
    publish_at = local_times[0].astimezone(timezone.utc) if local_times else (now + timedelta(hours=6))
    privacy = str(cfg["publishing"]["default_privacy"])
    notify = bool(cfg["publishing"]["notify_subscribers_long"])

    video_id = upload_video(
        video_path=out_video,
        metadata=meta,
        publish_at=publish_at,
        privacy_status=privacy,
        notify_subscribers=notify,
        made_for_kids=bool(cfg["content"]["made_for_kids"]),
        contains_synthetic_media=bool(cfg["content"]["contains_synthetic_media"]),
    )
    try:
        set_thumbnail(video_id, thumb_path)
    except Exception as e:
        log.warning("Thumbnail set failed: %s", e)

    record_upload(
        state,
        {
            "ts": _iso(now),
            "video_id": video_id,
            "kind": "long",
            "template": "compilation",
            "voice_id": "mixed",
            "tts_engine": "mixed",
            "title": meta["title"],
            "publish_at": _iso(publish_at),
            "published_at": _iso(publish_at),
            "publish_hour_local": int(to_tz(publish_at, tz_name).hour),
            "scheduled": True,
            "num_questions": num_questions,
        },
    )


def main() -> None:
    cfg = load_yaml("config/config.yaml")
    setup_logging(cfg.get("logging", {}).get("level"))
    state = load_state("state/state.json")

    publish_shorts(cfg, state)
    publish_long_if_scheduled(cfg, state)

    state["last_run_at"] = utcnow().isoformat().replace("+00:00", "Z")
    save_state("state/state.json", state)


if __name__ == "__main__":
    main()

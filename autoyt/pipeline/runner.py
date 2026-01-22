\
from __future__ import annotations

import datetime as dt
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from autoyt.pipeline.analyst import run_analyst
from autoyt.pipeline.config import ConfigManager
from autoyt.pipeline.content.country_data import CountryDataset
from autoyt.pipeline.content.plan import DailyPlan, build_daily_plan
from autoyt.pipeline.content.seo import build_long_metadata, build_short_metadata
from autoyt.pipeline.media.backgrounds import pick_background
from autoyt.pipeline.media.music import pick_music
from autoyt.pipeline.media.render_long import render_long_video
from autoyt.pipeline.media.render_short import render_short
from autoyt.pipeline.media.tts import synthesize_tts
from autoyt.pipeline.storage import Storage
from autoyt.pipeline.youtube.uploader import upload_video
from autoyt.utils.logging_utils import get_logger
from autoyt.utils.time import pick_seed_for_date, spaced_times_for_day, utc_now

log = get_logger("autoyt.runner")


def _weighted_choice(rng: random.Random, items: List[Dict[str, Any]], weights: List[float]) -> Dict[str, Any]:
    total = sum(max(0.0, w) for w in weights)
    if total <= 0:
        return rng.choice(items)
    r = rng.random() * total
    acc = 0.0
    for it, w in zip(items, weights):
        w = max(0.0, w)
        acc += w
        if r <= acc:
            return it
    return items[-1]


def pick_voice(cfg_base: Dict[str, Any], cfg_state: Dict[str, Any], rng: random.Random, used_today: List[str]) -> Dict[str, Any]:
    voices = list(cfg_base.get("voices", []))
    weights = [float(cfg_state.get("voice_weights", {}).get(v["id"], v.get("weight", 1.0))) for v in voices]

    # Avoid repeating same voice too much in a day
    if used_today:
        for i, v in enumerate(voices):
            if v["id"] == used_today[-1]:
                weights[i] *= 0.35

    pick = _weighted_choice(rng, voices, weights)
    used_today.append(pick["id"])
    return pick


def _hours_for_count(base_hours: List[int], n: int, rng: random.Random) -> List[int]:
    hours = sorted(list(dict.fromkeys([int(h) for h in base_hours])))
    if not hours:
        hours = [11, 14, 18, 21]
    if n == len(hours):
        return hours
    if n < len(hours):
        # drop random hours to get n, but keep spread
        candidates = hours[:]
        while len(candidates) > n:
            # don't drop extremes if possible
            drop_idx = rng.randrange(1, len(candidates) - 1) if len(candidates) > 2 else rng.randrange(0, len(candidates))
            candidates.pop(drop_idx)
        return candidates
    # n > len(hours): add between min/max
    while len(hours) < n:
        h = rng.randint(min(hours), max(hours))
        if h not in hours:
            hours.append(h)
            hours.sort()
    return hours[:n]




def _adjust_publish_time_for_match(
    item_meta: Dict[str, Any],
    scheduled_pub_utc: dt.datetime,
    now_utc: dt.datetime,
    rng: random.Random,
) -> dt.datetime:
    """
    If kickoff_utc is available and match is today, try to publish ~6–10 hours before kickoff.
    Falls back to scheduled_pub_utc if anything looks risky.
    """
    kickoff_str = str(item_meta.get("kickoff_utc") or "")
    match_date_str = str(item_meta.get("match_date") or "")
    if not kickoff_str or not match_date_str:
        return scheduled_pub_utc

    try:
        kickoff = dt.datetime.fromisoformat(kickoff_str.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        return scheduled_pub_utc

    # Only adjust for matches happening today (UTC date to keep it simple and safe)
    if kickoff.date().isoformat() != match_date_str:
        # If match_date was computed differently, don't risk it
        return scheduled_pub_utc

    if kickoff.date() != now_utc.date():
        # If match is not today, keep the planned schedule (e.g., 1–3 days early)
        return scheduled_pub_utc

    delta_h = rng.randint(6, 10)
    target = kickoff - dt.timedelta(hours=delta_h)

    # If target is already in the past (or too close), keep scheduled
    if target <= now_utc + dt.timedelta(minutes=45):
        return scheduled_pub_utc

    return target
def _publish_times_for_shorts(
    day: dt.date,
    tz_name: str,
    n: int,
    cfg_base: Dict[str, Any],
    cfg_state: Dict[str, Any],
) -> List[dt.datetime]:
    rng = random.Random(pick_seed_for_date(day) + 321)
    hours = _hours_for_count(list(cfg_state.get("schedule_hours_local") or cfg_base["scheduling"]["default_post_hours_local"]), n, rng)
    jitter_min = int(cfg_base["scheduling"]["jitter_minutes"]["min"])
    jitter_max = int(cfg_base["scheduling"]["jitter_minutes"]["max"])
    min_gap = int(cfg_base["scheduling"].get("short_min_gap_minutes", 90))
    seed = pick_seed_for_date(day)
    return spaced_times_for_day(day, tz_name, hours, jitter_min, jitter_max, min_gap_minutes=min_gap, seed=seed)


def run_bootstrap(repo_root: Path, shorts: int = 1, longs: int = 1, publish_now: bool = True) -> None:
    """
    Create and publish initial content immediately (no tests).
    """
    cfgm = ConfigManager(repo_root)
    bundle = cfgm.load()
    cfg_base, cfg_state = bundle.base, bundle.state

    # Minimal analyst run to set initial timezone if possible
    try:
        cfg_state = run_analyst(repo_root, cfg_base, cfg_state, upload_profile_readonly=1, analytics_profile=3)
        cfgm.save_state(cfg_state)
    except Exception as e:
        log.warning(f"Analyst skipped in bootstrap: {e}")

    ds = CountryDataset.load(repo_root / ".cache")
    storage = Storage(repo_root)

    now = utc_now()
    day = now.date()
    rng = random.Random(int(day.strftime("%Y%m%d")) + 111)

    # Generate a plan, but override counts
    plan = build_daily_plan(repo_root, cfg_base, cfg_state, ds, storage, now_utc=now)
    plan.shorts = plan.shorts[:shorts]
    plan.include_long = longs > 0

    target_tz = cfg_state.get("target_timezone") or cfg_base["channel"]["default_timezone"]

    used_voice: List[str] = []

    out_dir = repo_root / "out" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Shorts
    for idx, item in enumerate(plan.shorts):
        voice = pick_voice(cfg_base, cfg_state, rng, used_voice)
        cache_tts = repo_root / ".cache" / "tts"
        voice_path = out_dir / f"short_{idx+1:02d}_voice.mp3"

        # Voice reads question + options in one sentence (options for mc/continent)
        voice_text = item.question_text
        if item.options and item.template_id in {"mc_capital", "which_continent"}:
            labels = ["A", "B", "C", "D"]
            opts = []
            for i, opt in enumerate(item.options):
                lab = labels[i] if i < len(labels) else str(i + 1)
                opts.append(f"{lab}. {opt}")
            voice_text = voice_text + " " + " ".join(opts)

        voice_dur = synthesize_tts(voice_text.replace("\n", " "), voice, voice_path, cache_dir=cache_tts)

        bg = pick_background(
            repo_root=repo_root,
            topic=item.topic,
            cfg_state=cfg_state,
            width=cfg_base["rendering"]["shorts"]["width"],
            height=cfg_base["rendering"]["shorts"]["height"],
            rng=rng,
        )
        use_music = rng.random() < 0.65
        music = pick_music(repo_root, cfg_state, rng, allow_external=True) if use_music else None

        out_video = out_dir / f"short_{idx+1:02d}.mp4"
        rr = render_short(item, voice_path, voice_dur, bg, music, out_video, cfg_base, rng)

        title, desc, tags = build_short_metadata(item, cfg_base, cfg_state, rng)

        publish_at = None if publish_now else (now + dt.timedelta(minutes=10))
        # Upload
        try:
            res = upload_video(
                oauth_profile=1,
                file_path=out_video,
                title=title,
                description=desc,
                tags=tags,
                category_id=cfg_base["channel"]["category_id_shorts"],
                publish_at_utc=publish_at,
                made_for_kids=cfg_base["channel"]["made_for_kids"],
                default_language=cfg_base["channel"]["language"],
                notify_subscribers=False,
            )
            video_id = res.video_id
            log.info(f"Uploaded Short: {video_id}")
        except Exception as e:
            video_id = ""
            log.error(f"Upload failed (Short #{idx+1}): {e}")

        # Log & history
        storage.append_history(item.dupe_key, kind="short", template_id=item.template_id, meta=item.meta or {})
        storage.append_video_log(
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "kind": "short",
                "video_id": video_id,
                "template_id": item.template_id,
                "topic": item.topic,
                "voice_id": voice.get("id"),
                "voice_provider": voice.get("provider"),
                "used_music": rr.used_music,
                "music_id": rr.music_id,
                "background_id": rr.background_id,
                "scheduled_publish_at_utc": publish_at.isoformat().replace("+00:00", "Z") if publish_at else None,
                "target_country": cfg_state.get("target_country"),
                "target_timezone": target_tz,
                "title": title,
            }
        )

    # Long
    if plan.include_long and plan.long_questions:
        # Use a stable voice for long to reduce over-variation
        voice = pick_voice(cfg_base, cfg_state, rng, used_voice)
        out_long = out_dir / "long.mp4"
        lr = render_long_video(repo_root, plan.long_questions, voice, out_long, cfg_base, cfg_state, rng)
        title, desc, tags = build_long_metadata(cfg_base, cfg_state, rng)

        publish_at = None if publish_now else (now + dt.timedelta(minutes=30))
        try:
            res = upload_video(
                oauth_profile=1,
                file_path=out_long,
                title=title,
                description=desc,
                tags=tags,
                category_id=cfg_base["channel"]["category_id_long"],
                publish_at_utc=publish_at,
                made_for_kids=cfg_base["channel"]["made_for_kids"],
                default_language=cfg_base["channel"]["language"],
                notify_subscribers=False,
            )
            video_id = res.video_id
            log.info(f"Uploaded Long: {video_id}")
        except Exception as e:
            video_id = ""
            log.error(f"Upload failed (Long): {e}")

        storage.append_history(dupe_key=f"long::{day.isoformat()}", kind="long", template_id="long_quiz", meta={"questions": len(plan.long_questions)})
        storage.append_video_log(
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "kind": "long",
                "video_id": video_id,
                "template_id": "long_quiz",
                "topic": "quiz",
                "voice_id": voice.get("id"),
                "voice_provider": voice.get("provider"),
                "used_music": False,
                "music_id": None,
                "background_id": "mixed",
                "scheduled_publish_at_utc": publish_at.isoformat().replace("+00:00", "Z") if publish_at else None,
                "target_country": cfg_state.get("target_country"),
                "target_timezone": target_tz,
                "title": title,
            }
        )

    cfgm.save_state(cfg_state)


def run_daily(repo_root: Path, publish_now: bool = False) -> None:
    """
    Daily end-to-end:
    - analyst (updates state)
    - build plan
    - generate + schedule uploads
    """
    cfgm = ConfigManager(repo_root)
    bundle = cfgm.load()
    cfg_base, cfg_state = bundle.base, bundle.state

    # Analyst
    try:
        cfg_state = run_analyst(repo_root, cfg_base, cfg_state, upload_profile_readonly=1, analytics_profile=3)
    except Exception as e:
        log.warning(f"Analyst failed (continuing): {e}")

    ds = CountryDataset.load(repo_root / ".cache")
    storage = Storage(repo_root)

    now = utc_now()
    day = now.date()
    rng = random.Random(int(day.strftime("%Y%m%d")) + 222)

    plan = build_daily_plan(repo_root, cfg_base, cfg_state, ds, storage, now_utc=now)

    tz_name = cfg_state.get("target_timezone") or cfg_base["channel"]["default_timezone"]
    publish_times = _publish_times_for_shorts(day, tz_name, len(plan.shorts), cfg_base, cfg_state)

    out_dir = repo_root / "out" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    used_voice: List[str] = []

    # Render + upload shorts
    for idx, (item, pub_utc) in enumerate(zip(plan.shorts, publish_times)):
        if item.template_id == "match_prediction" and item.meta and not publish_now:
            pub_utc = _adjust_publish_time_for_match(item.meta, pub_utc, now, rng)

        voice = pick_voice(cfg_base, cfg_state, rng, used_voice)
        cache_tts = repo_root / ".cache" / "tts"
        voice_path = out_dir / f"short_{idx+1:02d}_voice.mp3"

        voice_text = item.question_text
        if item.options and item.template_id in {"mc_capital", "which_continent"}:
            labels = ["A", "B", "C", "D"]
            opts = []
            for i, opt in enumerate(item.options):
                lab = labels[i] if i < len(labels) else str(i + 1)
                opts.append(f"{lab}. {opt}")
            voice_text = voice_text + " " + " ".join(opts)

        voice_dur = synthesize_tts(voice_text.replace("\n", " "), voice, voice_path, cache_dir=cache_tts)

        bg = pick_background(
            repo_root=repo_root,
            topic=item.topic,
            cfg_state=cfg_state,
            width=cfg_base["rendering"]["shorts"]["width"],
            height=cfg_base["rendering"]["shorts"]["height"],
            rng=rng,
        )

        # Music probability varies by template (match a bit higher, discussion lower)
        p_music = 0.68
        if item.template_id == "would_you_rather":
            p_music = 0.55
        if item.template_id == "match_prediction":
            p_music = 0.75

        music = pick_music(repo_root, cfg_state, rng, allow_external=True) if (rng.random() < p_music) else None

        out_video = out_dir / f"short_{idx+1:02d}.mp4"
        rr = render_short(item, voice_path, voice_dur, bg, music, out_video, cfg_base, rng)

        title, desc, tags = build_short_metadata(item, cfg_base, cfg_state, rng)

        publish_at = None if publish_now else pub_utc

        try:
            res = upload_video(
                oauth_profile=1,
                file_path=out_video,
                title=title,
                description=desc,
                tags=tags,
                category_id=cfg_base["channel"]["category_id_shorts"],
                publish_at_utc=publish_at,
                made_for_kids=cfg_base["channel"]["made_for_kids"],
                default_language=cfg_base["channel"]["language"],
                notify_subscribers=False,
            )
            video_id = res.video_id
            log.info(f"Uploaded Short {idx+1}/{len(plan.shorts)}: {video_id}")
        except Exception as e:
            video_id = ""
            log.error(f"Upload failed (Short #{idx+1}): {e}")

        storage.append_history(item.dupe_key, kind="short", template_id=item.template_id, meta=item.meta or {})
        storage.append_video_log(
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "kind": "short",
                "video_id": video_id,
                "template_id": item.template_id,
                "topic": item.topic,
                "voice_id": voice.get("id"),
                "voice_provider": voice.get("provider"),
                "used_music": rr.used_music,
                "music_id": rr.music_id,
                "background_id": rr.background_id,
                "scheduled_publish_at_utc": publish_at.isoformat().replace("+00:00", "Z") if publish_at else None,
                "target_country": cfg_state.get("target_country"),
                "target_timezone": tz_name,
                "title": title,
            }
        )

    # Long video (if due)
    if plan.include_long and plan.long_questions:
        # Schedule long at best mid-day hour with jitter
        rng_long = random.Random(int(day.strftime("%Y%m%d")) + 333)
        voice = pick_voice(cfg_base, cfg_state, rng_long, used_voice)
        out_long = out_dir / "long.mp4"
        lr = render_long_video(repo_root, plan.long_questions, voice, out_long, cfg_base, cfg_state, rng_long)
        title, desc, tags = build_long_metadata(cfg_base, cfg_state, rng_long)

        # publish time: use second slot or first if missing
        publish_long = None
        if not publish_now:
            # choose a time around 16:00 local as default
            tz = pytz.timezone(tz_name)
            local_dt = tz.localize(dt.datetime.combine(day, dt.time(16, 0)))
            # jitter +/- 30 min
            j = rng_long.randint(-30, 30)
            local_dt = local_dt + dt.timedelta(minutes=j)
            publish_long = local_dt.astimezone(dt.timezone.utc)

        try:
            res = upload_video(
                oauth_profile=1,
                file_path=out_long,
                title=title,
                description=desc,
                tags=tags,
                category_id=cfg_base["channel"]["category_id_long"],
                publish_at_utc=publish_long,
                made_for_kids=cfg_base["channel"]["made_for_kids"],
                default_language=cfg_base["channel"]["language"],
                notify_subscribers=False,
            )
            video_id = res.video_id
            log.info(f"Uploaded Long: {video_id}")
        except Exception as e:
            video_id = ""
            log.error(f"Upload failed (Long): {e}")

        storage.append_history(dupe_key=f"long::{day.isoformat()}", kind="long", template_id="long_quiz", meta={"questions": len(plan.long_questions)})
        storage.append_video_log(
            {
                "created_at": now.isoformat().replace("+00:00", "Z"),
                "kind": "long",
                "video_id": video_id,
                "template_id": "long_quiz",
                "topic": "quiz",
                "voice_id": voice.get("id"),
                "voice_provider": voice.get("provider"),
                "used_music": False,
                "music_id": None,
                "background_id": "mixed",
                "scheduled_publish_at_utc": publish_long.isoformat().replace("+00:00", "Z") if publish_long else None,
                "target_country": cfg_state.get("target_country"),
                "target_timezone": tz_name,
                "title": title,
            }
        )

    cfgm.save_state(cfg_state)

from __future__ import annotations

import logging
import os
import random
from pathlib import Path

from .config import load_config
from .generators.background import generate_background
from .generators.llm import LLMConfig, LLMOrchestrator
from .generators.question import ShortSpec, generate_unique_short_spec
from .generators.thumbnail import generate_thumbnail
from .state import StateStore
from .tts.manager import TTSManager
from .utils.text import clamp_list, sha256_hex
from .utils.time import today_utc_ymd, utc_now
from .utils.logging import setup_logging
from .video.compilation import render_compilation
from .video.short import render_short
from .youtube.auth import get_authenticated_service
from .youtube.throttle import UploadThrottle
from .youtube.upload import set_thumbnail, upload_video


log = logging.getLogger(__name__)


def _final_description(base: str, hashtags: list[str]) -> str:
    base = (base or "").strip()
    tags_line = " ".join(dict.fromkeys([h.strip() for h in hashtags if h.strip()]))
    extra = "\n\n" + tags_line if tags_line else ""
    out = (base + extra).strip()
    return out[:4800]


def _safe_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        t = "10-Second Trivia (10s Quiz)"
    if len(t) > 95:
        t = t[:92].rstrip() + "..."
    return t


def _safe_tags(tags: list[str]) -> list[str]:
    cleaned = []
    for t in tags:
        s = (t or "").strip()
        if not s:
            continue
        if len(s) > 28:
            s = s[:28].strip()
        cleaned.append(s)
    return clamp_list(cleaned, 450)


def _build_daily_title() -> str:
    return "Daily Trivia Compilation (4 Shorts)"


def _build_daily_description(specs: list[ShortSpec]) -> str:
    lines = [
        "4 quick trivia questions from today!",
        "",
        "Questions included:",
    ]
    for i, s in enumerate(specs, start=1):
        q = s.question.replace("\n", " ").strip()
        if len(q) > 140:
            q = q[:137].rstrip() + "..."
        lines.append(f"{i}) {q}")
    lines.append("")
    lines.append("Comment your score!")
    lines.append("")
    lines.append("#trivia #quiz")
    return "\n".join(lines)


def main() -> int:
    setup_logging()
    cfg = load_config()

    if not cfg.yt_profiles:
        log.error("Missing YouTube OAuth secrets. Set YT_CLIENT_ID_1, YT_CLIENT_SECRET_1, YT_REFRESH_TOKEN_1.")
        return 2

    state = StateStore(cfg.state_path, max_used_questions=cfg.max_used_questions)
    state.load()

    llm = LLMOrchestrator(LLMConfig(groq_api_key=cfg.groq_api_key, gemini_api_key=cfg.gemini_api_key))
    tts = TTSManager()
    throttle = UploadThrottle(min_interval_s=20.0)

    rng = random.Random()
    rng.seed(sha256_hex(today_utc_ymd() + "|" + os.getenv("GITHUB_RUN_ID", "0")))

    day = today_utc_ymd()
    out_dir = cfg.out_dir

    short_specs: list[ShortSpec] = []
    short_paths: list[Path] = []
    uploaded_ids: list[str] = []
    run_qhashes: set[str] = set()

    auth_ctx, youtube = get_authenticated_service(cfg.yt_profiles)
    log.info("Authenticated with YouTube OAuth profile #%d", auth_ctx.profile_index + 1)

    for idx in range(cfg.shorts_per_run):
        spec = None
        for _ in range(1, 25):
            candidate = generate_unique_short_spec(llm, state, rng)
            qh = state.question_hash(candidate.question)
            if qh in run_qhashes:
                continue
            spec = candidate
            run_qhashes.add(qh)
            break
        if spec is None:
            spec = generate_unique_short_spec(llm, state, rng)

        bg = out_dir / f"{day}.short{idx+1}.bg.png"
        wav = out_dir / f"{day}.short{idx+1}.tts.wav"
        mp4 = out_dir / f"{day}.short{idx+1}.mp4"
        thumb = out_dir / f"{day}.short{idx+1}.thumb.png"

        generate_background(bg, width=cfg.width, height=cfg.height, rng=rng)

        tts_text = spec.voice_script()
        tts.synthesize(tts_text, wav)

        render_short(
            bg_path=bg,
            question=spec.question,
            answer=spec.answer,
            tts_wav=wav,
            out_mp4=mp4,
            font_bold_path=cfg.font_bold_path,
            width=cfg.width,
            height=cfg.height,
            fps=cfg.fps,
            countdown_s=cfg.countdown_seconds,
            answer_s=cfg.answer_seconds,
        )

        generate_thumbnail(bg, thumb, headline=spec.question, font_bold_path=cfg.font_bold_path)

        title = _safe_title(spec.title)
        tags = _safe_tags(spec.tags)
        desc = _final_description(spec.description, spec.hashtags)

        throttle.wait()
        result = upload_video(
            youtube,
            file_path=str(mp4),
            title=title,
            description=desc,
            tags=tags,
            category_id=cfg.category_id,
            privacy_status="public",
            publish_at_iso=None,
            notify_subscribers=cfg.notify_subscribers,
            made_for_kids=False,
            contains_synthetic_media=True,
        )
        throttle.wait()
        set_thumbnail(youtube, video_id=result.video_id, thumbnail_path=str(thumb))

        qhash = state.mark_used(spec.question, spec.answer, video_id=result.video_id)

        short_specs.append(spec)
        short_paths.append(mp4)
        uploaded_ids.append(result.video_id)

        state.add_day_entry(
            day,
            {
                "shorts": [
                    {
                        "idx": idx + 1,
                        "video_id": result.video_id,
                        "qhash": qhash,
                        "title": title,
                        "privacy": "public",
                        "publish_at": None,
                    }
                ]
            },
        )
        log.info("Uploaded short %d/%d: %s", idx + 1, cfg.shorts_per_run, result.video_id)

    comp_bg = out_dir / f"{day}.comp.bg.png"
    comp_mp4 = out_dir / f"{day}.compilation.mp4"
    comp_thumb = out_dir / f"{day}.compilation.thumb.png"

    generate_background(comp_bg, width=cfg.width, height=cfg.height, rng=rng)
    render_compilation(
        short_paths=short_paths,
        bg_path=comp_bg,
        out_mp4=comp_mp4,
        font_bold_path=cfg.font_bold_path,
        width=cfg.width,
        height=cfg.height,
        fps=cfg.fps,
    )

    generate_thumbnail(comp_bg, comp_thumb, headline="4 Questions | Daily Compilation", font_bold_path=cfg.font_bold_path)

    comp_title = _safe_title(_build_daily_title())
    comp_desc = _final_description(_build_daily_description(short_specs), ["#trivia", "#quiz"])
    comp_tags = _safe_tags(["trivia", "quiz", "compilation", "general knowledge", "education"])

    throttle.wait()
    comp_res = upload_video(
        youtube,
        file_path=str(comp_mp4),
        title=comp_title,
        description=comp_desc,
        tags=comp_tags,
        category_id=cfg.category_id,
        privacy_status="public",
        publish_at_iso=None,
        notify_subscribers=False,
        made_for_kids=False,
        contains_synthetic_media=True,
    )
    throttle.wait()
    set_thumbnail(youtube, video_id=comp_res.video_id, thumbnail_path=str(comp_thumb))

    uploaded_ids.append(comp_res.video_id)

    state.add_day_entry(
        day,
        {
            "compilation": {
                "video_id": comp_res.video_id,
                "title": comp_title,
                "privacy": "public",
                "publish_at": None,
            }
        },
    )

    state.set_last_upload(uploaded_ids)
    state.save()

    log.info("All done. Uploaded video IDs: %s", ",".join(uploaded_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

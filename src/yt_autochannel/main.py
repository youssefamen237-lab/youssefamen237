from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from .config import load_settings
from .db.sqlite_db import DB, utc_now_iso
from .planner import plan_today
from .providers.tts_chain import TTSChain
from .providers.tts_edge import EdgeTTS
from .providers.tts_espeak import EspeakTTS
from .providers.youtube_uploader import YouTubeUploader
from .render.backgrounds import ensure_backgrounds
from .render.music import ensure_music
from .render.short_renderer import ShortRenderSpec, render_short
from .render.long_renderer import LongEpisodeSpec, render_long_episode
from .render.thumbnail import create_long_thumbnail
from .run_report import RunReport
from .utils.text_utils import sanitize_text


def _ensure_dirs(root: Path, *rel_paths: str) -> None:
    for rp in rel_paths:
        (root / rp).mkdir(parents=True, exist_ok=True)


def main() -> int:
    settings = load_settings()
    repo_root = Path(settings.repo_root)
    _ensure_dirs(repo_root, settings.output_dir, settings.artifacts_dir, settings.logs_dir)

    report = RunReport(repo_root / settings.artifacts_dir)
    report.add("info", "run_start", {"utc": utc_now_iso(), "dry_run": settings.dry_run})

    db_path = repo_root / settings.artifacts_dir / "state.sqlite"
    db = DB(str(db_path))

    try:
        if not settings.run_enabled:
            report.add("warn", "RUN_ENABLED=false; pipeline is disabled")
            report.write()
            return 0

        # Ensure minimal assets exist
        bg_dir = repo_root / settings.assets_dir / "backgrounds"
        music_dir = repo_root / settings.assets_dir / "music"
        ensure_backgrounds(bg_dir)
        ensure_music(music_dir)

        # Plan today's content (by LOCAL day) if not already planned.
        tz = pytz.timezone(settings.timezone)
        local_now = datetime.now(tz=tz)
        local_date = local_now.date().isoformat()

        planned_key = f"planned_local:{local_date}"
        if db.get_state(planned_key) != "1":
            planned = plan_today(settings, db)
            report.add("info", "planned", {"count": len(planned), "local_date": local_date})
            db.set_state(planned_key, "1")
        else:
            report.add("info", "planning_skipped", {"local_date": local_date})

        # Select pending items within the local-day window.
        local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_day_end = local_day_start + timedelta(days=1)
        window_start_utc = local_day_start.astimezone(pytz.UTC).isoformat()
        window_end_utc = local_day_end.astimezone(pytz.UTC).isoformat()
        report.add(
            "info",
            "selection_window",
            {"local_date": local_date, "window_start_utc": window_start_utc, "window_end_utc": window_end_utc},
        )

        rows = db.list_pending_between(window_start_utc, window_end_utc)

        # Fallback window (covers edge cases if timezone math or jitter causes date-prefix mismatch)
        if not rows:
            now_utc = datetime.now(tz=pytz.UTC)
            w2_start = (now_utc - timedelta(hours=2)).isoformat()
            w2_end = (now_utc + timedelta(hours=36)).isoformat()
            rows = db.list_pending_between(w2_start, w2_end)
            report.add("warn", "fallback_window_used", {"window_start_utc": w2_start, "window_end_utc": w2_end, "count": len(rows)})

        pending_count = len(rows)
        report.add("info", "pending_rows", {"count": pending_count})

        # Build providers
        tts_chain = TTSChain([EdgeTTS(), EspeakTTS()])

        uploader = None
        if not settings.dry_run:
            uploader = YouTubeUploader(
                channel_id=settings.yt_channel_id,
                client_id=settings.yt_client_id,
                client_secret=settings.yt_client_secret,
                refresh_token=settings.yt_refresh_token,
            )

        uploaded_today = 0
        uploaded_video_ids: list[str] = []
        first_run_done = (db.get_state("first_run_done") == "1")

        for row in rows:
            row_id = int(row["id"])
            kind = str(row["kind"])

            # Render if needed
            if row["status"] == "planned":
                try:
                    if kind == "short":
                        bg_path = bg_dir / str(row["bg_image_id"])
                        music_path = (music_dir / str(row["music_track_id"])) if row["music_track_id"] else None
                        voice_gender = str(row["voice_gender"])
                        voice = settings.tts_edge_voice_female if voice_gender == "female" else settings.tts_edge_voice_male

                        q = sanitize_text(str(row["question"] or ""))
                        a = sanitize_text(str(row["answer"] or ""))
                        choices = None
                        correct_index = None
                        meta = {}
                        try:
                            if row["extra_json"]:
                                meta = json.loads(str(row["extra_json"]))
                                if isinstance(meta, dict):
                                    if isinstance(meta.get("choices"), list):
                                        choices = [sanitize_text(str(x)) for x in meta.get("choices")]
                                    if isinstance(meta.get("correct_index"), int):
                                        correct_index = int(meta.get("correct_index"))
                        except Exception:
                            meta = {}

                        spec = ShortRenderSpec(
                            template_id=str(row["template_id"]),
                            question=q,
                            answer=a,
                            choices=choices,
                            correct_index=correct_index,
                            countdown_seconds=int(row["countdown_seconds"] or settings.countdown_seconds),
                            answer_seconds=float(settings.answer_seconds),
                            bg_path=bg_path,
                            font_path=settings.font_path,
                            fps=settings.fps,
                            resolution=settings.short_resolution,
                            brand_primary=settings.brand_primary,
                            brand_secondary=settings.brand_secondary,
                            brand_accent=settings.brand_accent,
                            music_enabled=bool(row["music_track_id"]) and str(row["template_id"]) != 'zoom_reveal',
                            music_path=music_path,
                            music_target_db=settings.music_target_db,
                            tts_chain=tts_chain,
                            tts_voice=voice,
                            output_path=repo_root / settings.output_dir / f"short_{row_id}.mp4",
                        )
                        render_short(spec)
                        db.update_video(row_id, status="rendered")
                        report.add("info", "rendered_short", {"id": row_id, "file": str(spec.output_path)})

                    elif kind == "long":
                        bg_path = bg_dir / str(row["bg_image_id"])
                        music_path = (music_dir / str(row["music_track_id"])) if row["music_track_id"] else None
                        voice_gender = str(row["voice_gender"])
                        voice = settings.tts_edge_voice_female if voice_gender == "female" else settings.tts_edge_voice_male
                        payload = json.loads(str(row["question"]))
                        episode = LongEpisodeSpec(
                            title=str(row["title"] or "Trivia Episode"),
                            qas=payload,
                            bg_path=bg_path,
                            font_path=settings.font_path,
                            fps=settings.fps,
                            resolution=settings.long_resolution,
                            brand_primary=settings.brand_primary,
                            brand_secondary=settings.brand_secondary,
                            brand_accent=settings.brand_accent,
                            music_enabled=bool(row["music_track_id"]),
                            music_path=music_path,
                            music_target_db=settings.music_target_db,
                            tts_chain=tts_chain,
                            tts_voice=voice,
                            output_path=repo_root / settings.output_dir / f"long_{row_id}.mp4",
                        )
                        render_long_episode(episode)
                        db.update_video(row_id, status="rendered")
                        report.add("info", "rendered_long", {"id": row_id, "file": str(episode.output_path)})

                    else:
                        db.update_video(row_id, status="failed", error=f"Unknown kind: {kind}")
                        report.add("error", "unknown_kind", {"id": row_id, "kind": kind})

                except Exception as e:
                    db.update_video(row_id, status="failed", error=str(e))
                    report.add("error", "render_failed", {"id": row_id, "error": str(e)})
                    continue

            # Upload if rendered
            if settings.dry_run:
                continue
            if uploaded_today >= settings.daily_upload_cap:
                report.add("warn", "daily_upload_cap_reached", {"cap": settings.daily_upload_cap})
                break

            row2 = db._conn.execute("SELECT * FROM videos WHERE id=?", (row_id,)).fetchone()
            if row2 is None or row2["status"] != "rendered":
                continue

            try:
                publish_at = datetime.fromisoformat(str(row2["publish_at_utc"]))
                if publish_at.tzinfo is None:
                    publish_at = publish_at.replace(tzinfo=pytz.UTC)

                # First-ever run: publish a real Short ASAP
                if not first_run_done and kind == "short":
                    publish_at = datetime.now(tz=pytz.UTC) + timedelta(minutes=2)

                title = str(row2["title"] or "")
                description = str(row2["description"] or "")
                tags = []
                try:
                    tags = [t.strip() for t in (row2["tags_csv"] or "").split(",") if t.strip() and not row2["tags_csv"].startswith("{")]
                except Exception:
                    tags = []

                # Ensure Shorts get a #shorts hashtag somewhere without fingerprinting
                if kind == "short" and "#shorts" not in description.lower():
                    description = (description.rstrip() + "\n#shorts").strip()

                video_path = repo_root / settings.output_dir / (f"short_{row_id}.mp4" if kind == "short" else f"long_{row_id}.mp4")

                upload_res = uploader.upload_video(
                    video_file=video_path,
                    title=title,
                    description=description,
                    tags=tags,
                    publish_at_utc=publish_at,
                    is_short=(kind == "short"),
                )

                video_id = upload_res.video_id
                db.update_video(row_id, status="uploaded", video_id=video_id, uploaded_at_utc=utc_now_iso())
                uploaded_today += 1
                uploaded_video_ids.append(video_id)

                report.add(
                    "info",
                    "uploaded",
                    {
                        "id": row_id,
                        "kind": kind,
                        "video_id": video_id,
                        "publish_at_utc": publish_at.isoformat(),
                    },
                )

                if kind == "long":
                    # Create and set thumbnail
                    thumb_path = repo_root / settings.output_dir / f"thumb_{row_id}.jpg"
                    create_long_thumbnail(
                        bg_path=bg_dir / str(row2["bg_image_id"]),
                        title=title,
                        out_path=thumb_path,
                        font_path=settings.font_path,
                        primary=settings.brand_primary,
                        secondary=settings.brand_secondary,
                        accent=settings.brand_accent,
                    )
                    uploader.set_thumbnail(video_id=video_id, thumbnail_file=thumb_path)
                    report.add("info", "thumbnail_set", {"id": row_id, "video_id": video_id})

                if not first_run_done and kind == "short":
                    db.set_state("first_run_done", "1")
                    first_run_done = True

            except Exception as e:
                db.update_video(row_id, status="failed", error=str(e))
                report.add("error", "upload_failed", {"id": row_id, "error": str(e)})

        report.add("info", "run_end", {"uploaded_today": uploaded_today})
        report.write()

        # Emit a compact summary to stdout so you can debug without downloading artifacts.
        print(
            "RUN_SUMMARY_JSON="
            + json.dumps(
                {
                    "dry_run": settings.dry_run,
                    "pending_rows": pending_count,
                    "uploaded_today": uploaded_today,
                    "uploaded_video_ids": uploaded_video_ids,
                    "artifacts_dir": str(repo_root / settings.artifacts_dir),
                }
            )
        )
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

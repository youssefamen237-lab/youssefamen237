"""
compilation/long_video_engine.py – Quizzaro Long Video Compilation Engine
=========================================================================
Every week, concatenates the best-performing Shorts of the past 7 days
into a single long-form video (8–15 minutes) with intro/outro cards.
Uploads it as a regular YouTube video (not a Short).
"""
from __future__ import annotations

import json
import random
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

PUBLISH_LOG_PATH = Path("data/publish_log.json")
COMPILATION_DIR = Path("data/compilations")
COMPILATION_DIR.mkdir(parents=True, exist_ok=True)

INTRO_TEXT = "Welcome to Quizzaro's Weekly Brain Challenge! 🧠"
OUTRO_TEXT = "Thanks for watching! Subscribe for daily trivia and quizzes! 🔔"


class LongVideoEngine:

    def __init__(self, uploader, metadata_gen, ai_engine) -> None:
        self._uploader = uploader
        self._meta = metadata_gen
        self._ai = ai_engine

    def _load_recent_shorts(self) -> list[dict]:
        """Return Shorts published in the last 7 days that have a local video path."""
        if not PUBLISH_LOG_PATH.exists():
            return []
        try:
            with open(PUBLISH_LOG_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            return []

        cutoff = datetime.utcnow() - timedelta(days=7)
        results = []
        for e in entries:
            try:
                pub_at = datetime.fromisoformat(e.get("published_at", "").replace("Z", "+00:00").replace("+00:00", ""))
                if pub_at >= cutoff and e.get("local_video_path"):
                    results.append(e)
            except Exception:
                continue
        return results

    def _build_concat_list(self, entries: list[dict], list_path: str) -> None:
        with open(list_path, "w") as f:
            for e in entries:
                safe_path = e["local_video_path"].replace("'", r"'\''")
                f.write(f"file '{safe_path}'\n")

    def _add_text_card(self, text: str, duration: int, output_path: str) -> str:
        """Generate a 3-second black card with centered white text using FFmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:size=1080x1920:duration={duration}:rate=30",
            "-vf", (
                f"drawtext=text='{text}':"
                "fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2:"
                "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"[LongVideo] Text card generation failed: {result.stderr[:200]}")
        return output_path

    def _generate_title(self, entries: list[dict]) -> str:
        categories = list({e.get("category", "") for e in entries if e.get("category")})
        cat_str = ", ".join(categories[:3]) if categories else "Trivia"
        prompt = (
            f"Write ONE YouTube video title (max 90 chars) for a compilation of trivia questions "
            f"covering: {cat_str}. Must be engaging, contain 1 emoji, no clickbait. Output title only."
        )
        try:
            raw = self._ai.generate_raw(prompt).strip().split("\n")[0]
            if 10 < len(raw) <= 100:
                return raw
        except Exception as exc:
            logger.warning(f"[LongVideo] AI title failed: {exc}")
        return f"🧠 Weekly Brain Challenge Compilation #{datetime.utcnow().strftime('%W')} | Trivia Quiz"

    def run(self) -> None:
        entries = self._load_recent_shorts()
        if len(entries) < 5:
            logger.warning(f"[LongVideo] Only {len(entries)} Shorts available. Need ≥5. Skipping.")
            return

        logger.info(f"[LongVideo] Building compilation from {len(entries)} Shorts …")

        job_dir = COMPILATION_DIR / datetime.utcnow().strftime("%Y-%m-%d")
        job_dir.mkdir(parents=True, exist_ok=True)

        # Add intro + outro cards as separate video clips
        intro_path = str(job_dir / "intro.mp4")
        outro_path = str(job_dir / "outro.mp4")
        self._add_text_card(INTRO_TEXT, 3, intro_path)
        self._add_text_card(OUTRO_TEXT, 4, outro_path)

        # Build concat list: intro + all shorts + outro
        all_clips = [{"local_video_path": intro_path}] + entries + [{"local_video_path": outro_path}]
        list_path = str(job_dir / "concat_list.txt")
        self._build_concat_list(all_clips, list_path)

        output_path = str(job_dir / "weekly_compilation.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"[LongVideo] FFmpeg concat failed:\n{result.stderr}")

        logger.success(f"[LongVideo] Compilation ready: {output_path}")

        title = self._generate_title(entries)
        description = (
            f"🧠 Welcome to Quizzaro's Weekly Brain Challenge!\n\n"
            f"This week's compilation features {len(entries)} trivia questions across multiple categories.\n\n"
            f"Can you get them all right? Drop your score in the comments!\n\n"
            f"🔔 Subscribe for daily quiz Shorts!\n\n"
            f"#Quiz #Trivia #BrainChallenge #WeeklyQuiz #GeneralKnowledge"
        )
        tags = ["quiz", "trivia", "compilation", "brain challenge", "general knowledge",
                "weekly quiz", "trivia compilation", "quiz game", "brain teaser"]

        publish_at = datetime.utcnow() + timedelta(hours=2)

        video_id = self._uploader.upload_short(
            video_path=output_path,
            title=title,
            description=description,
            tags=tags,
            publish_at=publish_at,
        )
        logger.success(f"[LongVideo] Uploaded → https://youtu.be/{video_id}")

"""
main.py – Quizzaro YouTube Automation
======================================
Central entry point called by every GitHub Actions workflow.

Usage (via workflow):
    python main.py --mode publish          # produce & upload N shorts for today
    python main.py --mode polls            # post community polls
    python main.py --mode manager          # run analytics + strategy optimizer
    python main.py --mode compilation      # build & upload weekly long video
    python main.py --mode bootstrap        # first-run: produce & upload 1 short NOW

All secrets are read exclusively from environment variables (never hardcoded).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime

from loguru import logger

# ── internal imports ──────────────────────────────────────────────────────────
from utils.secrets_loader import SecretsLoader
from utils.logger import configure_logger
from utils.fallback_manager import FallbackManager
from utils.rate_limiter import RateLimiter

from core.question_bank import QuestionBank
from core.ai_engine import AIEngine
from core.content_fetcher import ContentFetcher
from core.anti_duplicate import AntiDuplicate

from audio.audio_engine import AudioEngine
from audio.voice_humanizer import VoiceHumanizer
from audio.sfx_manager import SFXManager

from video.template_engine import TemplateEngine
from video.background_manager import BackgroundManager
from video.music_engine import MusicEngine
from video.video_composer import VideoComposer
from video.watermark import WatermarkEngine

from publishing.youtube_uploader import YouTubeUploader
from publishing.metadata_generator import MetadataGenerator
from publishing.scheduler import PublishScheduler
from publishing.polls_engine import PollsEngine

from manager.project_manager import ProjectManager
from compilation.long_video_engine import LongVideoEngine


# ─────────────────────────────────────────────────────────────────────────────
#  Bootstrap: wire all services together into a shared context
# ─────────────────────────────────────────────────────────────────────────────

def build_context() -> dict:
    """
    Load secrets, initialise every service, and return a shared context dict.
    This is the single wiring point – every mode consumes the same context.
    """
    configure_logger()
    secrets = SecretsLoader.load_all()

    fallback = FallbackManager()
    rate_limiter = RateLimiter()

    ai = AIEngine(
        gemini_key=secrets["GEMINI_API_KEY"],
        groq_key=secrets["GROQ_API_KEY"],
        openai_key=secrets["OPENAI_API_KEY"],
        openrouter_key=secrets["OPENROUTER_KEY"],
        fallback_manager=fallback,
    )

    content_fetcher = ContentFetcher(
        serpapi_key=secrets["SERPAPI"],
        tavily_key=secrets["TAVILY_API_KEY"],
        news_api_key=secrets["NEWS_API"],
        youtube_api_key=secrets["YOUTUBE_API_KEY"],
    )

    anti_dup = AntiDuplicate()

    question_bank = QuestionBank(
        ai_engine=ai,
        content_fetcher=content_fetcher,
        anti_duplicate=anti_dup,
    )

    tts = AudioEngine(
        hf_token=secrets["HF_API_TOKEN"],
        freesound_api_key=secrets["FREESOUND_API"],
        freesound_client_id=secrets["FREESOUND_ID"],
    )
    humanizer = VoiceHumanizer()
    sfx = SFXManager(
        freesound_api_key=secrets["FREESOUND_API"],
        freesound_client_id=secrets["FREESOUND_ID"],
    )

    bg_manager = BackgroundManager(
        pexels_key=secrets["PEXELS_API_KEY"],
        pixabay_key=secrets["PIXABAY_API_KEY"],
        anti_duplicate=anti_dup,
    )
    music_engine = MusicEngine(
        freesound_api_key=secrets["FREESOUND_API"],
        anti_duplicate=anti_dup,
    )
    template_engine = TemplateEngine()
    watermark = WatermarkEngine(channel_handle="@Quizzaro_1")
    composer = VideoComposer(
        tts_engine=tts,
        voice_humanizer=humanizer,
        sfx_manager=sfx,
        background_manager=bg_manager,
        music_engine=music_engine,
        template_engine=template_engine,
        watermark_engine=watermark,
    )

    metadata_gen = MetadataGenerator(ai_engine=ai)

    uploader = YouTubeUploader(
        client_id=secrets["YT_CLIENT_ID_1"],
        client_secret=secrets["YT_CLIENT_SECRET_1"],
        refresh_token=secrets["YT_REFRESH_TOKEN_1"],
        channel_id=secrets["YT_CHANNEL_ID"],
    )

    scheduler = PublishScheduler()

    polls = PollsEngine(
        ai=ai,
        client_id=secrets["YT_CLIENT_ID_2"],
        client_secret=secrets["YT_CLIENT_SECRET_2"],
        refresh_token=secrets["YT_REFRESH_TOKEN_2"],
        channel_id=secrets["YT_CHANNEL_ID"],
    )

    pm = ProjectManager(
        client_id=secrets["YT_CLIENT_ID_3"],
        client_secret=secrets["YT_CLIENT_SECRET_3"],
        refresh_token=secrets["YT_REFRESH_TOKEN_3"],
        channel_id=secrets["YT_CHANNEL_ID"],
        ai_engine=ai,
    )

    long_video = LongVideoEngine(
        uploader=uploader,
        metadata_gen=metadata_gen,
        ai_engine=ai,
    )

    return {
        "secrets": secrets,
        "ai": ai,
        "question_bank": question_bank,
        "composer": composer,
        "metadata_gen": metadata_gen,
        "uploader": uploader,
        "scheduler": scheduler,
        "polls": polls,
        "project_manager": pm,
        "long_video": long_video,
        "anti_dup": anti_dup,
        "rate_limiter": rate_limiter,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MODE: publish  –  produce & upload today's batch of Shorts
# ─────────────────────────────────────────────────────────────────────────────

def run_publish(ctx: dict) -> None:
    """
    Determine today's video count (4–8, randomised), produce each Short
    end-to-end, and upload them on a randomised schedule.
    """
    scheduler: PublishScheduler = ctx["scheduler"]
    question_bank: QuestionBank = ctx["question_bank"]
    composer: VideoComposer = ctx["composer"]
    metadata_gen: MetadataGenerator = ctx["metadata_gen"]
    uploader: YouTubeUploader = ctx["uploader"]

    count = scheduler.todays_video_count()          # random int 4–8
    publish_times = scheduler.todays_publish_times(count)  # list[datetime]

    logger.info(f"[PUBLISH] Today's plan: {count} Shorts at {[t.strftime('%H:%M') for t in publish_times]}")

    for i, publish_at in enumerate(publish_times, start=1):
        logger.info(f"[PUBLISH] Producing Short {i}/{count} …")

        try:
            # 1. Pull a fresh, non-duplicate question
            question = question_bank.get_next_question()

            # 2. Render the full Short video
            video_path = composer.render_short(question)

            # 3. Generate SEO metadata
            metadata = metadata_gen.generate(question)

            # 4. Upload to YouTube (scheduled at publish_at)
            video_id = uploader.upload_short(
                video_path=video_path,
                title=metadata["title"],
                description=metadata["description"],
                tags=metadata["tags"],
                publish_at=publish_at,
            )

            logger.success(f"[PUBLISH] Short {i}/{count} uploaded → https://youtu.be/{video_id}")

        except Exception as exc:
            logger.error(f"[PUBLISH] Short {i}/{count} FAILED: {exc}\n{traceback.format_exc()}")
            # Never stop – continue to next video
            continue


# ─────────────────────────────────────────────────────────────────────────────
#  MODE: bootstrap  –  first-run: produce & upload ONE Short immediately
# ─────────────────────────────────────────────────────────────────────────────

def run_bootstrap(ctx: dict) -> None:
    """
    Immediate production of a single Short with publish_at = NOW.
    Called once when the repository is first activated.
    """
    question_bank: QuestionBank = ctx["question_bank"]
    composer: VideoComposer = ctx["composer"]
    metadata_gen: MetadataGenerator = ctx["metadata_gen"]
    uploader: YouTubeUploader = ctx["uploader"]

    logger.info("[BOOTSTRAP] First run – producing Short immediately …")

    question = question_bank.get_next_question()
    video_path = composer.render_short(question)
    metadata = metadata_gen.generate(question)

    video_id = uploader.upload_short(
        video_path=video_path,
        title=metadata["title"],
        description=metadata["description"],
        tags=metadata["tags"],
        publish_at=datetime.utcnow(),   # publish NOW, no scheduling delay
    )

    logger.success(f"[BOOTSTRAP] First Short uploaded → https://youtu.be/{video_id}")


# ─────────────────────────────────────────────────────────────────────────────
#  MODE: polls  –  post 1–4 community poll posts
# ─────────────────────────────────────────────────────────────────────────────

def run_polls(ctx: dict) -> None:
    polls: PollsEngine = ctx["polls"]
    logger.info("[POLLS] Starting community polls engine …")
    polls.run_daily()
    logger.success("[POLLS] Done.")


# ─────────────────────────────────────────────────────────────────────────────
#  MODE: manager  –  analytics + strategy auto-optimisation
# ─────────────────────────────────────────────────────────────────────────────

def run_manager(ctx: dict) -> None:
    pm: ProjectManager = ctx["project_manager"]
    logger.info("[MANAGER] Running analytics & strategy optimisation …")
    pm.run()
    logger.success("[MANAGER] Strategy updated.")


# ─────────────────────────────────────────────────────────────────────────────
#  MODE: compilation  –  build weekly long video from recent Shorts
# ─────────────────────────────────────────────────────────────────────────────

def run_compilation(ctx: dict) -> None:
    lv: LongVideoEngine = ctx["long_video"]
    logger.info("[COMPILATION] Building weekly long video …")
    lv.run()
    logger.success("[COMPILATION] Long video uploaded.")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

MODES = {
    "publish": run_publish,
    "polls": run_polls,
    "manager": run_manager,
    "compilation": run_compilation,
    "bootstrap": run_bootstrap,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quizzaro – Fully Automated YouTube Shorts Channel"
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES.keys()),
        required=True,
        help="Operation mode for this run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mode_fn = MODES[args.mode]

    logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(f"  Quizzaro | Mode: {args.mode.upper()} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    try:
        ctx = build_context()
        mode_fn(ctx)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.critical(f"FATAL ERROR in mode '{args.mode}': {exc}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()

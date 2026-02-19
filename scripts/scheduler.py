import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from .duplicate_manager import DuplicateManager
from .llm_client import LLMClient
from .video_builder import ShortVideoBuilder, LongVideoBuilder
from .youtube_uploader import YouTubeUploader
from .strategy_manager import StrategyManager
from .config import Config

logger = logging.getLogger("scheduler")
handler = logging.FileHandler(Config.LOG_DIR / "scheduler.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class ContentScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.dup_manager = DuplicateManager()
        self.llm = LLMClient()
        self.short_builder = ShortVideoBuilder()
        self.long_builder = LongVideoBuilder()
        self.uploader = YouTubeUploader()
        self.strategy = StrategyManager()

    def start(self):
        # Schedule daily short batch generation (4 shorts)
        self.scheduler.add_job(self._run_daily_shorts, 'cron', hour=0, minute=5)  # run shortly after midnight UTC
        # Schedule weekly long video batch (4 videos)
        self.scheduler.add_job(self._run_weekly_long, 'cron', day_of_week='mon', hour=1, minute=0)
        self.scheduler.start()
        logger.info("Scheduler started.")

    def _run_daily_shorts(self):
        logger.info("Starting daily shorts generation.")
        for i in range(4):
            try:
                publish_time = self.strategy.choose_publish_time()
                self.scheduler.add_job(
                    self._process_and_publish_short,
                    trigger='date',
                    run_date=publish_time,
                    kwargs={'publish_time': publish_time}
                )
                logger.info(f"Scheduled short #{i+1} for {publish_time}")
            except Exception as e:
                logger.exception(f"Failed to schedule short #{i+1}: {e}")

    def _process_and_publish_short(self, publish_time: datetime):
        logger.info(f"Processing short for scheduled time {publish_time}")
        # 1️⃣ Generate question with duplicate check
        for attempt in range(5):
            q_data = self.llm.generate_question()
            if not self.dup_manager.is_recent_question(q_data["question"]):
                break
            logger.warning("Duplicate question detected, regenerating.")
        else:
            logger.error("Failed to generate a non‑duplicate question after retries.")
            return

        # Register question to prevent future duplicates
        self.dup_manager.register_question(q_data["question"])

        # 2️⃣ Build video
        assets = self.short_builder.build(q_data)

        # 3️⃣ SEO metadata
        title = self.llm.generate_seo_title(assets["question_text"])
        # Ensure title not duplicate
        while self.dup_manager.is_recent_title(title):
            title = self.llm.generate_seo_title(assets["question_text"])
        self.dup_manager.register_title(title)

        description = self.llm.generate_seo_description(assets["question_text"])
        tags = self.llm.generate_tags(title)
        hashtags = self.llm.generate_hashtags(title)
        full_description = f"{description}\n\n{' '.join(hashtags)}"

        # 4️⃣ Upload
        video_id = self.uploader.upload_short(
            video_path=assets["video_path"],
            title=title,
            description=full_description,
            tags=tags,
            thumbnail_path=assets["thumbnail_path"]
        )
        logger.info(f"Short video uploaded with ID {video_id}")

        # 5️⃣ Update strategy based on performance (future runs)
        self.strategy.update_weights_from_video(video_id, publish_time)

    def _run_weekly_long(self):
        logger.info("Starting weekly long video compilation.")
        # Determine which shorts to include (most recent 40 shorts)
        short_dir = Config.SHORT_VIDEO_DIR
        shorts = [p for p in short_dir.iterdir() if p.suffix.lower() == ".mp4"]
        shorts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if len(shorts) < 40:
            logger.warning("Not enough short videos to compile a long video.")
            return
        # We'll create 4 long videos, each with 10 shorts
        for i in range(4):
            selected = shorts[i*10:(i+1)*10]
            title = f"Daily Quiz Marathon #{i+1} – Test Your Knowledge"
            assets = self.long_builder.compile_long_video(
                short_video_paths=selected,
                title_text=title
            )
            description = f"Enjoy a compilation of 10 quick quizzes! 🧠\n\nSubscribe for daily challenges.\n\n#Quiz #Trivia #Shorts"
            tags = self.llm.generate_tags(title) + ["Quiz", "Trivia", "Compilation"]
            hashtags = self.llm.generate_hashtags(title)
            full_description = f"{description}\n\n{' '.join(hashtags)}"

            publish_time = self.strategy.choose_publish_time()
            self.scheduler.add_job(
                self._upload_long_video,
                trigger='date',
                run_date=publish_time,
                kwargs={
                    'video_path': assets["video_path"],
                    'title': title,
                    'description': full_description,
                    'tags': tags,
                    'thumbnail_path': assets["thumbnail_path"],
                    'publish_time': publish_time
                }
            )
            logger.info(f"Scheduled long video #{i+1} for {publish_time}")

    def _upload_long_video(self, video_path, title, description, tags, thumbnail_path, publish_time):
        logger.info(f"Uploading long video scheduled for {publish_time}")
        video_id = self.uploader.upload_long(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            thumbnail_path=thumbnail_path,
        )
        logger.info(f"Long video uploaded with ID {video_id}")
        self.strategy.update_weights_from_video(video_id, publish_time)

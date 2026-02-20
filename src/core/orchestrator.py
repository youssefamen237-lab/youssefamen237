from datetime import datetime, timezone

from core.config import CONFIG
from core.scheduler import Scheduler
from core.state import StateStore
from engines.analytics_engine import AnalyticsEngine
from engines.audio_engine import AudioEngine
from engines.image_engine import ImageEngine
from engines.question_engine import QuestionEngine
from engines.seo_engine import SEOEngine
from engines.thumbnail_engine import ThumbnailEngine
from engines.video_engine import VideoEngine
from integrations.llm_providers import LLMProviders
from integrations.youtube_engine import YouTubeEngine


class Orchestrator:
    def __init__(self) -> None:
        self.state = StateStore()
        self.scheduler = Scheduler()
        self.questions = QuestionEngine()
        self.image_engine = ImageEngine()
        self.audio = AudioEngine()
        self.video = VideoEngine()
        self.seo = SEOEngine()
        self.thumb = ThumbnailEngine()
        self.youtube = YouTubeEngine()
        self.llm = LLMProviders()

    @staticmethod
    def _clean_text(text: str) -> str:
        return text.replace("'", "").replace(":", "-")

    def _publish_short(self) -> None:
        q = self.questions.create()
        bg = self.image_engine.fetch_background()
        q_audio = self.audio.synthesize(self._clean_text(q["question"]), CONFIG.output_dir / "question.mp3")
        cta_audio = self.audio.synthesize(self._clean_text(q["cta"]), CONFIG.output_dir / "cta.mp3")
        video_path = self.video.build_short(bg, self._clean_text(q["question"]), self._clean_text(q["cta"]), self._clean_text(q["answer"]), q_audio, cta_audio)
        seo = self.seo.build(q["question"], "short")
        thumb = self.thumb.create(bg, seo["title"], "short")
        video_id = self.youtube.upload(str(video_path), str(thumb), seo, is_short=True)
        now = datetime.now(timezone.utc).isoformat()
        self.state.update(
            lambda s: (
                s["uploads"].append({"video_id": video_id, "type": "short", "created_at": now}),
                s.update({"last_short_at": now}),
            )
        )

    def _publish_long(self) -> None:
        prompt = (
            "Create a 5+ minute quiz script in English with 25 numbered questions and answers for a general foreign audience. "
            "Return plain text only."
        )
        script = self.llm.generate(prompt)
        bg = self.image_engine.fetch_background()
        narration = self.audio.synthesize(script[:2500], CONFIG.output_dir / "long_narration.mp3")
        slides = CONFIG.output_dir / "long_slides.txt"
        slides.write_text(self._clean_text(script[:4000]))
        video_path = self.video.build_long(bg, slides, narration)
        seo = self.seo.build("Ultimate General Knowledge Quiz", "long")
        thumb = self.thumb.create(bg, seo["title"], "long")
        video_id = self.youtube.upload(str(video_path), str(thumb), seo, is_short=False)
        now = datetime.now(timezone.utc).isoformat()
        self.state.update(
            lambda s: (
                s["uploads"].append({"video_id": video_id, "type": "long", "created_at": now}),
                s.update({"last_long_at": now}),
            )
        )

    def _bootstrap_if_needed(self) -> None:
        state = self.state.get()
        if not state.get("initialized"):
            self._publish_short()
            self._publish_long()
            self.state.update(lambda s: s.update({"initialized": True}))

    def _scheduled_publish(self) -> None:
        if self.scheduler.due_short():
            self._publish_short()
        if self.scheduler.due_long():
            self._publish_long()

    def run(self, mode: str) -> None:
        if mode == "autonomous":
            self._bootstrap_if_needed()
            self._scheduled_publish()
            AnalyticsEngine().run()
            return

        if mode == "bootstrap":
            self._bootstrap_if_needed()
            return

        if mode == "short":
            if self.scheduler.due_short():
                self._publish_short()
            return

        if mode == "long":
            if self.scheduler.due_long():
                self._publish_long()
            return

        if mode == "analytics":
            AnalyticsEngine().run()
            return

        if mode == "recovery":
            self._scheduled_publish()

import json
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config
from .analytics_manager import AnalyticsManager

logger = logging.getLogger("strategy_manager")
handler = logging.FileHandler(Config.LOG_DIR / "strategy_manager.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class StrategyManager:
    def __init__(self):
        self.path = Config.STRATEGY_PATH
        self.data = self._load()
        self.analytics = AnalyticsManager()
        # Initialize hour_weights if not present
        if "hour_weights" not in self.data:
            self.data["hour_weights"] = {str(h): 1.0 for h in range(6, 24)}  # 6am‑11pm
            self._save()

    def _load(self) -> dict:
        if self.path.is_file():
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def update_weights_from_video(self, video_id: str, publish_dt: datetime):
        perf = self.analytics.get_video_performance(video_id, days=7)
        view_score = perf["views"] / 1000.0  # scale factor
        hour = str(publish_dt.hour)
        current = self.data["hour_weights"].get(hour, 1.0)
        self.data["hour_weights"][hour] = max(0.5, current + view_score)  # avoid zero/negative
        logger.info(f"Updated hour weight for {hour} to {self.data['hour_weights'][hour]}")
        self._save()

    def choose_publish_time(self) -> datetime:
        hours = list(self.data["hour_weights"].keys())
        weights = list(self.data["hour_weights"].values())
        chosen_hour = int(random.choices(hours, weights=weights, k=1)[0])
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        now = datetime.utcnow()
        chosen_dt = datetime(
            year=now.year,
            month=now.month,
            day=now.day,
            hour=chosen_hour,
            minute=minute,
            second=second,
        )
        if chosen_dt <= now:
            chosen_dt += timedelta(days=1)  # push to next day if already passed
        logger.info(f"Chosen publish time: {chosen_dt.isoformat()} UTC")
        return chosen_dt

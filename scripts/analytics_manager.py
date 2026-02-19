import logging
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import Config

logger = logging.getLogger("analytics_manager")
handler = logging.FileHandler(Config.LOG_DIR / "analytics_manager.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class AnalyticsManager:
    def __init__(self):
        self.creds = Credentials(
            token=None,
            refresh_token=Config.YT_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.YT_CLIENT_ID,
            client_secret=Config.YT_CLIENT_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/yt-analytics.readonly",
            ],
        )
        self.analytics = build("youtubeAnalytics", "v2", credentials=self.creds, cache_discovery=False)

    def get_video_performance(self, video_id: str, days: int = 7) -> dict:
        """
        Retrieve basic performance metrics for the given video over the past `days`.
        Returns a dict with view count, average view duration, watch time (minutes).
        """
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)
        request = self.analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,averageViewDuration,watchTime",
            filters=f"video=={video_id}"
        )
        response = request.execute()
        logger.info(f"Analytics fetched for video {video_id}")
        if "rows" in response and response["rows"]:
            row = response["rows"][0]
            return {
                "views": row[0],
                "average_view_duration": row[1],
                "watch_time_minutes": row[2],
            }
        else:
            return {"views": 0, "average_view_duration": 0, "watch_time_minutes": 0}

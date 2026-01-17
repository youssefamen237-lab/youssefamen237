from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class PlannedVideo:
    kind: str  # short|long
    publish_at_utc: datetime
    template_id: str
    topic: str
    difficulty: str
    countdown_seconds: int
    voice_gender: str
    music_enabled: bool
    bg_image_path: Path
    bg_image_id: str
    music_path: Optional[Path]
    music_track_id: Optional[str]
    question: str
    answer: str
    choices: Optional[List[str]] = None
    correct_index: Optional[int] = None
    title: str = ""
    description: str = ""
    tags: Optional[List[str]] = None
    title_style_id: str = ""
    # output paths
    video_path: Optional[Path] = None
    thumbnail_path: Optional[Path] = None

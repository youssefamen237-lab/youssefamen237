#!/usr/bin/env python3
"""
run_batch.py

طريقة سريعة لتوليد المحتوى وفقًا للجدول:
    python -m scripts.run_batch daily   # ينتج 4 Shorts
    python -m scripts.run_batch weekly  # يُجمّع 4 Long‑Videos من آخر 40 Short
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime

from .duplicate_manager import DuplicateManager
from .llm_client import LLMClient
from .video_builder import ShortVideoBuilder, LongVideoBuilder
from .youtube_uploader import YouTubeUploader

# إعداد سجل موحد
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

def generate_and_upload_short(publish_dt: datetime):
    dup = DuplicateManager()
    llm = LLMClient()
    builder = ShortVideoBuilder()
    uploader = YouTubeUploader()

    # 1️⃣ سؤال غير مكرر
    for _ in range(5):
        q = llm.generate_question()
        if not dup.is_recent_question(q["question"]):
            break
    else:
        raise RuntimeError("فشل توليد سؤال غير مكرر بعد 5 محاولات")

    dup.register_question(q["question"])

    # 2️⃣ بناء الفيديو
    assets = builder.build(q)

    # 3️⃣ SEO
    title = llm.generate_seo_title(assets["question_text"])
    while dup.is_recent_title(title):
        title = llm.generate_seo_title(assets["question_text"])
    dup.register_title(title)

    description = llm.generate_seo_description(assets["question_text"])
    tags = llm.generate_tags(title)
    hashtags = llm.generate_hashtags(title)
    full_desc = f"{description}\n\n{' '.join(hashtags)}"

    # 4️⃣ رفع الـ Short
    video_id = uploader.upload_short(
        video_path=assets["video_path"],
        title=title,
        description=full_desc,
        tags=tags,
        thumbnail_path=assets["thumbnail_path"],
    )
    logging.info(f"Short uploaded – ID: {video_id}")

def compile_and_upload_long():
    long_builder = LongVideoBuilder()
    uploader = YouTubeUploader()
    llm = LLMClient()

    # نختار أحدث 40 Shorts
    short_dir = Path(__file__).parents[2] / "data" / "short_videos"
    shorts = sorted(
        [p for p in short_dir.iterdir() if p.suffix.lower() == ".mp4"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:40]

    if len(shorts) < 40:
        logging.warning("عدد الـ Shorts غير كافٍ لإنشاء فيديو أسبوعي.")
        return

    for i in range(4):  # 4 فيديوهات طويلة، كل واحدة 10 Shorts
        batch = shorts[i * 10 : (i + 1) * 10]
        title = f"Daily Quiz Marathon #{i + 1} – Test Your Knowledge"
        assets = long_builder.compile_long_video(batch, title)

        description = (
            "Enjoy a compilation of 10 quick quizzes! 🧠\n\n"
            "Subscribe for daily challenges.\n\n#Quiz #Trivia #Compilation"
        )
        tags = llm.generate_tags(title) + ["Quiz", "Trivia", "Compilation"]
        hashtags = llm.generate_hashtags(title)
        full_desc = f"{description}\n\n{' '.join(hashtags)}"

        video_id = uploader.upload_long(
            video_path=assets["video_path"],
            title=title,
            description=full_desc,
            tags=tags,
            thumbnail_path=assets["thumbnail_path"],
        )
        logging.info(f"Long video uploaded – ID: {video_id}")

def main():
    parser = argparse.ArgumentParser(description="Run a single batch (daily/weekly).")
    parser.add_argument(
        "mode", choices=["daily", "weekly"], help="نوع الدفعة المراد تشغيلها"
    )
    args = parser.parse_args()

    now = datetime.utcnow()
    if args.mode == "daily":
        # توليد 4 Shorts مع توقيتات عشوائية (مستَخدم لتقليد جدول الـ Scheduler)
        for i in range(4):
            # نولد توقيت عشوائي بين الآن + 0‑24 ساعة
            publish_dt = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1, seconds=random.randint(0, 86400))
            generate_and_upload_short(publish_dt)
    else:  # weekly
        compile_and_upload_long()


if __name__ == "__main__":
    main()

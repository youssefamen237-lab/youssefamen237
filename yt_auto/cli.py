diff --git a/yt_auto/cli.py b/yt_auto/cli.py
index 2ca08cfa140b88174a6ca386e3a1e2eca8fe3976..53ea7378dd451f3023e45f3dabee38300c80c69f 100644
--- a/yt_auto/cli.py
+++ b/yt_auto/cli.py
@@ -127,53 +127,67 @@ def _build_short_pipeline(cfg, state: StateStore, slot: int, date_yyyymmdd: str)
 def _build_long_pipeline(cfg, state: StateStore, date_yyyymmdd: str) -> str:
     ensure_dir(cfg.out_dir)
 
     if state.was_long_published(date_yyyymmdd):
         return ""
 
     token = cfg.github_token.strip()
     if not token:
         return ""
 
     owner_repo = _repo_full_name()
 
     clips = download_shorts_for_date(cfg.out_dir, date_yyyymmdd, token, owner_repo)
     if len(clips) < 4:
         return ""
 
     out_long = cfg.out_dir / f"long-{date_yyyymmdd}.mp4"
     build_long_compilation(cfg, clips, out_long, date_yyyymmdd)
 
     bg = pick_background(cfg, abs(hash(date_yyyymmdd)) % (10**9))
     thumb = cfg.out_dir / f"thumb-{date_yyyymmdd}.jpg"
     build_long_thumbnail(cfg, bg, thumb, date_yyyymmdd)
 
     uploader = YouTubeUploader(cfg.youtube_oauths)
 
-    title = f"Quizzaro Daily Compilation ({date_yyyymmdd})"
-    desc = "Today's 10-second quizzes in one compilation.\n\nSubscribe to Quizzaro for more!"
-    tags = ["quiz", "trivia", "compilation", "daily quiz", "brain teaser", "knowledge", "quizzaro"]
+    clip_count = len(clips)
+    title = f"Quizzaro Daily Compilation - {date_yyyymmdd} | {clip_count} Questions"
+    desc = (
+        "Today's 10-second quizzes in one compilation.\n"
+        "Comment your score and subscribe to Quizzaro for more!\n\n"
+        "#quiz #trivia #quizzaro"
+    )
+    tags = [
+        "quiz",
+        "trivia",
+        "compilation",
+        "daily quiz",
+        "brain teaser",
+        "general knowledge",
+        "quizzaro",
+        "quiz compilation",
+    ]
 
     res = uploader.upload_video(
         file_path=out_long,
         title=title[:100],
         description=desc[:5000],
         tags=tags,
         category_id=cfg.category_id_long,
         privacy_status=cfg.privacy_long,
         made_for_kids=cfg.made_for_kids,
         default_language=cfg.language,
         default_audio_language=cfg.language,
     )
 
     try:
         uploader.set_thumbnail(res.video_id, thumb)
     except Exception:
         pass
 
     state.record_long(date_yyyymmdd, res.video_id)
     state.save()
 
     return res.video_id
 
 
 def main() -> int:

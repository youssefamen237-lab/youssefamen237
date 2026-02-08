@@ -32,52 +32,68 @@ def _final_description(base: str, hashtags: list[str]) -> str:
     out = (base + extra).strip()
     return out[:4800]
 
 
 def _safe_title(title: str) -> str:
     t = (title or "").strip()
     if not t:
         t = "10-Second Trivia (10s Quiz)"
     if len(t) > 95:
         t = t[:92].rstrip() + "..."
     return t
 
 
 def _safe_tags(tags: list[str]) -> list[str]:
     cleaned = []
     for t in tags:
         s = (t or "").strip()
         if not s:
             continue
         if len(s) > 28:
             s = s[:28].strip()
         cleaned.append(s)
     return clamp_list(cleaned, 450)
 
 
-def _build_daily_title() -> str:
-    return "Daily Trivia Compilation (4 Shorts)"
+def _build_daily_title(day: str, specs: list[ShortSpec]) -> str:
+    base = f"Quizzaro Daily Trivia Compilation - {day}"
+    total = len(specs)
+    categories: list[str] = []
+    seen: set[str] = set()
+    for spec in specs:
+        cat = (spec.category or "").strip()
+        key = cat.lower()
+        if not cat or key in seen:
+            continue
+        seen.add(key)
+        categories.append(cat)
+        if len(categories) >= 3:
+            break
+    if categories:
+        cat_label = ", ".join(categories)
+        return f"{base} | {total} Questions: {cat_label}"
+    return f"{base} | {total} Questions"
 
 
 def _build_daily_description(specs: list[ShortSpec]) -> str:
     lines = [
         "4 quick trivia questions from today!",
         "",
         "Questions included:",
     ]
     for i, s in enumerate(specs, start=1):
         q = s.question.replace("\n", " ").strip()
         if len(q) > 140:
             q = q[:137].rstrip() + "..."
         lines.append(f"{i}) {q}")
     lines.append("")
     lines.append("Comment your score!")
     lines.append("")
     lines.append("#trivia #quiz")
     return "\n".join(lines)
 
 
 def main() -> int:
     setup_logging()
     cfg = load_config()
 
     if not cfg.yt_profiles:
@@ -183,51 +199,51 @@ def main() -> int:
                         "privacy": "public",
                         "publish_at": None,
                     }
                 ]
             },
         )
         log.info("Uploaded short %d/%d: %s", idx + 1, cfg.shorts_per_run, result.video_id)
 
     comp_bg = out_dir / f"{day}.comp.bg.png"
     comp_mp4 = out_dir / f"{day}.compilation.mp4"
     comp_thumb = out_dir / f"{day}.compilation.thumb.png"
 
     generate_background(comp_bg, width=cfg.width, height=cfg.height, rng=rng)
     render_compilation(
         short_paths=short_paths,
         bg_path=comp_bg,
         out_mp4=comp_mp4,
         font_bold_path=cfg.font_bold_path,
         width=cfg.width,
         height=cfg.height,
         fps=cfg.fps,
     )
 
     generate_thumbnail(comp_bg, comp_thumb, headline="4 Questions | Daily Compilation", font_bold_path=cfg.font_bold_path)
 
-    comp_title = _safe_title(_build_daily_title())
+    comp_title = _safe_title(_build_daily_title(day, short_specs))
     comp_desc = _final_description(_build_daily_description(short_specs), ["#trivia", "#quiz"])
     comp_tags = _safe_tags(["trivia", "quiz", "compilation", "general knowledge", "education"])
 
     throttle.wait()
     comp_res = upload_video(
         youtube,
         file_path=str(comp_mp4),
         title=comp_title,
         description=comp_desc,
         tags=comp_tags,
         category_id=cfg.category_id,
         privacy_status="public",
         publish_at_iso=None,
         notify_subscribers=False,
         made_for_kids=False,
         contains_synthetic_media=True,
     )
     throttle.wait()
     set_thumbnail(youtube, video_id=comp_res.video_id, thumbnail_path=str(comp_thumb))
 
     uploaded_ids.append(comp_res.video_id)
 
     state.add_day_entry(
         day,
         {

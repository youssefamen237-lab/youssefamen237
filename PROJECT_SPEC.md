# YouTube Auto Channel (GitHub-Only) — Project Spec

> الهدف: قناة Quiz/Trivia (YouTube Shorts + Long Compilation) تعمل أوتوماتيك بالكامل عبر GitHub Actions.
> المحتوى: English فقط + Original + Transformative + بدون حقوق ملكية.

---

## 1) Output Types

### Shorts
- Vertical 1080x1920
- Timer: 3s
- Answer reveal: 1s
- No voice during answer
- Background: صورة عشوائية + Blur (أو fallback مولّد)

### Long
- Horizontal 1920x1080
- 5–10 minutes
- Compilation من أسئلة مختلفة
- Thumbnail مخصص
- ينزل كفيديو عادي (مش Shorts)

---

## 2) Automation (GitHub Actions)
- Workflow: `.github/workflows/publish.yml`
  - ينفّذ يوميًا + عند أول Push
  - ينشر 4 Shorts يوميًا + 4 Long أسبوعيًا (على أيام محددة)
- Workflow: `.github/workflows/analyze.yml`
  - تحليل يومي للأداء + تقرير في `reports/`

---

## 3) Non-Repetition Rules
- لا تكرار سؤال خلال 15 يوم (Anti-duplicate similarity + hash)
- لا تكرار نفس الخلفية/الموسيقى خلال 7 أيام (إذا كانت موجودة)

---

## 4) TTS (Voice Branding)
- Primary: Edge TTS (free)
- Fallback: ElevenLabs (requires ELEVEN_API_KEY + ELEVEN_VOICE_ID)
- دعم ذكور/إناث (قائمة أصوات في `config/config.yaml`)
- تحليل يومي يحدّث تفضيل الأصوات بناءً على Views خلال 24 ساعة

---

## 5) Assets
- `assets/images/` : ضع صورك هنا (اختيار عشوائي + Blur)
- `assets/music/` : ضع موسيقى/مؤثرات هنا (اختياري — لو فاضي يتم تخطي الموسيقى)

---

## 6) Secrets (GitHub Repository Secrets)
Required:
- `YT_CHANNEL_ID`
- `YOUTUBE_API_KEY`
- `YT_CLIENT_ID_1`
- `YT_CLIENT_SECRET_1`
- `YT_REFRESH_TOKEN_1`

Optional:
- `YT_CLIENT_ID_2`
- `YT_CLIENT_SECRET_2`
- `YT_REFRESH_TOKEN_2`
- `PEXELS_API_KEY` / `PIXABAY_API_KEY` / `UNSPLASH_ACCESS_KEY` (fallback images)
- `ELEVEN_API_KEY` + `ELEVEN_VOICE_ID` (TTS fallback)

---

## 7) Run Behavior
- أول تشغيل: يحاول نشر Short واحد فورًا (Public) والباقي Scheduled (Private + publishAt)
- بعد كده: ينشر يوميًا تلقائيًا حسب أوقات محسوبة + متغيرة

---

## 8) Important Note
- YouTube Data API قد يقيّد الفيديوهات المرفوعة عبر API للمشاريع غير المُدققة (قد تظل Private).
- لازم تتأكد من حالة مشروع Google Cloud المرتبط بـ OAuth.


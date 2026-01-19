# YouTube Quiz Factory (GitHub Actions)

هذا الريبو ينشئ ويرفع محتوى **YouTube Shorts** + فيديو **Long Compilation** تلقائيًا باستخدام GitHub Actions وواجهة **YouTube Data API** الرسمية.

> ملاحظة مهمة (صراحة):
> - لا يمكنني من داخل هذه المحادثة رفع الملفات إلى GitHub بدلًا منك.
> - لا يوجد ضمان للربح/القبول في YPP أو عدم وجود قيود — لكن الكود مصمم لتقليل المخاطر عبر:
>   - محتوى نصي أصلي (Trivia) بدون موسيقى/حقوق.
>   - منع التكرار لمدة 15 يوم.
>   - Fallback حقيقي للموديلات + للصوت + للخلفيات.
>   - Rate limiting + Backoff + Circuit-style safeguards بسيطة.
> - الهدف هنا **الالتزام بسياسات YouTube** واستخدام الطرق الرسمية، وليس التحايل على أنظمة المنصة.

---

## 1) المتطلبات

- GitHub Actions مفعّل على الريبو.
- إضافة Secrets في إعدادات الريبو (Settings → Secrets and variables → Actions).
- قناة YouTube مرتبطة بحساب Google يسمح بالرفع عبر API.

---

## 2) Secrets المطلوبة لرفع الفيديو

ضع واحدة من مجموعتين (الأولى أو الثانية):

### مجموعة 1 (مفضلة)
- `YT_CLIENT_ID_1`
- `YT_CLIENT_SECRET_1`
- `YT_REFRESH_TOKEN_1`

### مجموعة 2 (Fallback)
- `YT_CLIENT_ID_2`
- `YT_CLIENT_SECRET_2`
- `YT_REFRESH_TOKEN_2`

> **مهم:** لازم Refresh Token يكون صالح مع Scopes رفع يوتيوب.

---

## 3) Secrets اختيارية (لتحسين الاعتمادية)

### توليد الأسئلة/الـSEO (AI)
- `GEMINI_API_KEY` (مفضل)
- `GROQ_API_KEY` (Fallback)

> لو الاتنين مش موجودين، هيشتغل مولّد محلي بسيط (Fallback) عشان البايبلاين مايقفش.

### الخلفيات (لو فولدر الصور فاضي)
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`
- `UNSPLASH_ACCESS_KEY`

---

## 4) إضافة الخلفيات

ارفع صورك هنا:

`assets/backgrounds/`

- الصيغ المدعومة: `.jpg .jpeg .png .webp`
- كل فيديو بيختار صورة عشوائية ويعمل Blur.

---

## 5) التشغيل

### أول تشغيل (Bootstrap)
- افتح تبويب **Actions** ثم Workflow: **YouTube Quiz Factory**
- اضغط **Run workflow**
- اختر `mode = bootstrap`

ده بيرفع **Short حقيقي فورًا**.

### التشغيل اليومي التلقائي
الـWorkflow بيشتغل تلقائيًا يوميًا (Cron) ويعمل:
- 4 Shorts مجدولين في أوقات مختلفة خلال اليوم
- 1 Long Compilation (16:9 و>60s) مجدول آخر اليوم

---

## 6) تعديل الإعدادات

ملف الإعدادات:

`config.json`

تقدر تعدّل:
- timezone
- schedule_times (4 أوقات HH:MM)
- jitter_minutes (تذبذب بسيط في التوقيت)
- duplicate_days (منع التكرار)
- voice (Edge TTS)

---

## 7) ملاحظات عن السلامة وسياسات YouTube

- الكود يمنع تلقائيًا الأسئلة ذات الحساسية العالية أو المحتوى غير المناسب.
- يمنع أسئلة "lyrics" أو اقتباسات طويلة لتقليل مخاطر الكوبي رايت.
- لا يستخدم موسيقى أو مقاطع محمية.
- العناوين/الوصف/الـTags يتم توليدها بشكل غير مضلل (مع Fallback).

---

## 8) الملفات التي يتم تحديثها تلقائيًا

- `data/history.json` لتتبع الأسئلة ومنع التكرار 15 يوم
- `data/uploads.json` لتسجيل الفيديوهات التي تم رفعها

GitHub Actions سيقوم بعمل commit لهذه الملفات تلقائيًا بعد كل Run.

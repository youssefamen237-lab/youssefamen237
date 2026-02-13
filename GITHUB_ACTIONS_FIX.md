# ❌ خطأ GitHub Actions - الحل السريع

## المشكلة
```
❌ Failure - 2 errors
produce-and-upload: Failed
performance-analysis: Failed
```

## السبب الأساسي
**لم تُضف API Keys إلى GitHub Secrets**

---

## ✅ الحل الفوري (5 دقائق)

### 1️⃣ اذهب إلى GitHub
```
your-repo → Settings → Secrets and variables → Actions
```

### 2️⃣ أضف هذه المفاتيح الإجبارية

#### المفاتيح اليوتيوب (REQUIRED)
```
YT_CLIENT_ID_3 = من Google Cloud Console
YT_CLIENT_SECRET_3 = من Google Cloud Console  
YT_REFRESH_TOKEN_3 = من OAuth2 token
YT_CHANNEL_ID = رقم قناتك على يوتيوب
```

#### مفتاح AI (اختر واحد - REQUIRED)
```
OPENAI_API_KEY = من https://platform.openai.com
    أو
GEMINI_API_KEY = من https://makersuite.google.com
    أو
GROQ_API_KEY = من https://console.groq.com
```

### 3️⃣ كيف تحصل على المفاتيح؟

#### YouTube API Key:
```bash
1. اذهب: https://console.cloud.google.com/
2. أنشئ مشروع جديد
3. فعّل "YouTube Data API v3"
4. اضغط Create Credentials
5. اختر "OAuth 2.0 Client ID"
6. نوع التطبيق: "Web application"
7. Authorized redirect URIs: 
   https://localhost:8080/callback
8. انسخ: Client ID و Client Secret
9. استخدم script في SETUP.md لالحصول على Refresh Token
```

#### OpenAI/Gemini/Groq (اختر أسهل):
```
OpenAI: https://platform.openai.com/api-keys
Gemini: https://makersuite.google.com/app/apikey
Groq: https://console.groq.com (مجاني!)
```

### 4️⃣ أضف المفاتيح

```
اضغط "New repository secret"
للمفتاح الأول:
  Name: YT_CLIENT_ID_3
  Value: (الرقم من Google Cloud)

كرر لكل مفتاح...
```

### 5️⃣ تشغيل جديد

```
اذهب Actions → Smart Shorts Daily Production
اضغط "Run workflow"
```

---

## 🔧 للاختبار المحلي بدون مفاتيح يوتيوب

```bash
# 1. إنشء .env ملف
cat > .env << 'EOF'
OPENAI_API_KEY=sk-your-key
# YouTube keys (optional للاختبار)
YT_CHANNEL_ID=test
EOF

# 2. تشغيل الاختبار
source .env
python src/brain.py --single-cycle

# أو بدون .env (سيعطيك رسالة واضحة)
python src/brain.py --single-cycle
```

---

## 📋 قائمة التحقق

- [ ] أضفت YT_CLIENT_ID_3
- [ ] أضفت YT_CLIENT_SECRET_3  
- [ ] أضفت YT_REFRESH_TOKEN_3
- [ ] أضفت YT_CHANNEL_ID
- [ ] أضفت OPENAI_API_KEY أو GEMINI_API_KEY أو GROQ_API_KEY
- [ ] ذهبت إلى Actions و رأيت Workflow يعمل
- [ ] انتظرت 2-3 دقائق

---

## 🎯 النتائج المتوقعة

بعد الإصلاح:
```
✅ produce-and-upload: Success
✅ performance-analysis: Success
✅ First video appears on YouTube
✅ Database filled with data
```

---

## ❓ مشاكل إضافية

### "Invalid credentials"
```
✓ تحقق من نقل الرقم بدون مسافات
✓ تأكد refresh token صحيح
✓ أعد إنشاء tokens في Google Cloud
```

### "API rate limit"
```
✓ انتظر ساعة واحدة
✓ قلل في config/system.json max_daily_uploads
```

### "FFmpeg not found"
```
✓ GitHub Actions تثبته تلقائياً
✓ محلياً: apt-get install ffmpeg
```

---

## 📚 مراجع سريعة

| المشكلة | الحل |
|--------|------|
| "YT_CLIENT_ID_3 not found" | أضف في Secrets |
| "Authentication failed" | تحقق من tokens |
| "No videos uploaded" | تحقق من CHANNEL_ID |
| "Import error" | pip install -r requirements.txt |

---

## 🚀 بعد الإصلاح؟

1. انتظر workflow ينجح
2. شوف logs في Actions tab
3. استعرض الفيديو على قناتك
4. اقرأ NEXT_STEPS_AR.md للخطوة التالية

---

**تحتاج مساعدة؟** اقرأ SETUP.md أو TROUBLESHOOTING.md

تم التحديث: 2026-02-13

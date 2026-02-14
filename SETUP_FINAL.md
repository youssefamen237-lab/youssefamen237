# 📋 خطوات الإعداد النهائي

## ✅ ما تم إنجازه:

1. **إزالة Demo Mode**: النظام الآن يتطلب YouTube OAuth الحقيقي للنشر
2. **Scripts جديد**:
   - `publish_shorts.py` - ينشر شورت واحد مع validation
   - `publish_long.py` - ينشر فيديو طويل واحد مع validation
3. **Workflows محدثة**:
   - تستخدم `publish_shorts.py` و `publish_long.py` بدلاً من MASTER_RUN
   - سيفشل إذا لم توجد credentials (وهذا مقصود)

---

## 🎯 الخطوات المتبقية (لك):

### 1️⃣ احصل على YouTube OAuth Credentials

يجب عليك الحصول على بيانات اعتماد OAuth من Google:

**للشورتس (YT_CLIENT_ID_1, YT_CLIENT_SECRET_1, YT_REFRESH_TOKEN_1):**
1. اذهب إلى https://console.cloud.google.com
2. أنشئ OAuth 2.0 Client ID (Desktop application)
3. حمل JSON وأضف `client_id` و `client_secret`
4. جرب تسجيل الدخول الأول: `python -m yt_auto bootstrap`
5. انسخ `refresh_token` من ملف state

**للفيديوهات الطويلة (YT_CLIENT_ID_2, ...):**
- يمكن استخدام نفس credentials أو channel مختلف

---

### 2️⃣ أضف Credentials إلى GitHub Secrets

1. اذهب إلى: GitHub Repo → Settings → Secrets and variables → Actions
2. أضف:
   ```
   YT_CLIENT_ID_1=<value>
   YT_CLIENT_SECRET_1=<value>
   YT_REFRESH_TOKEN_1=<value>
   YT_CLIENT_ID_2=<value>
   YT_CLIENT_SECRET_2=<value>
   YT_REFRESH_TOKEN_2=<value>
   YT_CHANNEL_ID=<your_channel_id>
   GITHUB_TOKEN=<github_token>
   ```

---

### 3️⃣ اختبر locally (اختياري):

```bash
# اختبر شورت واحد
python publish_shorts.py

# اختبر فيديو طويل
python publish_long.py
```

---

### 4️⃣ Push إلى GitHub

```bash
git add .
git commit -m "fix: require YouTube upload for success"
git push origin main
```

---

## 🎬 ماذا يحدث بعدها:

**Publish YouTube Shorts** (كل 6 ساعات):
- ✅ ينشر شورت واحد إلى YouTube
- ❌ سيفشل بدون YT_CLIENT_ID_1, YT_CLIENT_SECRET_1, YT_REFRESH_TOKEN_1

**Publish Long-Form Videos** (كل 3 أيام):
- ✅ ينشر فيديو طويل إلى YouTube
- ❌ سيفشل بدون YT_CLIENT_ID_2, YT_CLIENT_SECRET_2, YT_REFRESH_TOKEN_2, GITHUB_TOKEN

---

## 📊 متى يُعتبر نجح؟

✅ **النجاح:**
- الـ workflow يكمل بدون أخطاء
- شورت واحد موجود على YouTube
- فيديو طويل واحد موجود على YouTube

❌ **الفشل:**
- الـ workflow يفشل (red X)
- لا يوجد فيديو على YouTube

---

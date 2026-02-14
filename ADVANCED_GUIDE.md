# دليل الاستخدام المتقدم

## 🚀 البدء السريع

### 1. التثبيت الأولي
```bash
# استنساخ المستودع
git clone <repo-url>
cd youssefamen237

# تثبيت المتطلبات
pip install -r requirements.txt

# تثبيت أدوات النظام
apt-get install ffmpeg imagemagick fontconfig
```

### 2. إعداد متغيرات البيئة
```bash
# إنشاء ملف .env
cp .env.example .env

# ملء المفاتيح في .env:
GEMINI_API_KEY=your_key
GROQ_API_KEY=your_key
ELEVEN_API_KEY=your_key
YT_CLIENT_ID_3=your_id
YT_CLIENT_SECRET_3=your_secret
YT_REFRESH_TOKEN_3=your_token
YT_CHANNEL_ID=your_channel
```

### 3. الاختبار الأولي
```bash
# تشغيل عملية بناء اختبارية
python -m yt_auto bootstrap

# هذا سيقوم بـ:
# 1. توليد سؤال
# 2. حرق شورت
# 3. نشر أول فيديو
```

## 📅 الجدولة التلقائية

### GitHub Actions Setup
1. اذهب إلى `Settings > Secrets and variables > Actions`
2. أضف جميع متغيرات البيئة
3. GitHub Actions سيبدأ تلقائياً بعد الكمت

### الجداول المحددة مسبقاً

**الشورتس**: كل ساعة
```bash
# publish-shorts.yml
# يحاول نشر 4 شورتس يومياً
```

**الفيديوهات الطويلة**: يومياً (أيام محددة)
```bash
# publish-long.yml
# ينشر مرة واحدة يومياً (الإثنين-الخميس)
```

**التحليل**: يومياً
```bash
# analyze.yml
# يحلل الأداء ويحسن الاستراتيجية
```

## ⚙️ التخصيص المتقدم

### تغيير أوقات النشر

ملف: `yt_auto/scheduler.py`
```python
def _generate_schedule(self) -> dict[str, Any]:
    ...
    # العدد المسموح به
    # شورتس في الساعة: RATE_LIMIT_SHORTS_PER_HOUR
    # فيديوهات طويلة: RATE_LIMIT_LONG_PER_HOUR
```

### إضافة فئات أسئلة جديدة

ملف: `yt_auto/config.py`
```python
QUESTION_CATEGORIES = [
    "General Knowledge",
    "Science",
    # أضف فئات هنا
]
```

### تغيير نموذج اللغة

ملف: `.env`
```bash
LLM_PROVIDER_ORDER="gemini,groq,openrouter"
GEMINI_MODEL="gemini-1.5-flash"
GROQ_MODEL="llama-3.1-70b-versatile"
```

### تغيير قيم الصوت

ملف: `.env`
```bash
TTS_ORDER="elevenlabs,edge,espeak"
ELEVEN_VOICE_ID="21m00Tcm4TlvDq8ikWAM"
EDGE_VOICE="ar-SA-LeenNeural"
```

## 🔍 المراقبة والتتبع

### عرض الحالة الحالية
```bash
cat state/state.json
```

### عرض التحليلات
```bash
cat state/analysis.json
```

### عرض الاستراتيجية
```bash
cat state/strategy.json
```

### عرض جدول النشر
```bash
cat state/schedule.json
```

### التحقق من المخاطر
```bash
cat state/risk.json
```

## 🐛 استكشاف الأخطاء

### المشكلة: لا توجد مفاتيح API

```bash
# تحقق من .env
echo $GEMINI_API_KEY

# التأكد من أن البيئة محملة
python -c "import os; print(os.getenv('GEMINI_API_KEY'))"
```

### المشكلة: فشل FFmpeg

```bash
# تحقق التثبيت
ffmpeg -version

# تأكد من وجود الخطوط
fc-list | grep -i dejavu
```

### المشكلة: فشل YouTube Upload

```bash
# تحقق من الرموز
curl -H "Authorization: Bearer $YT_REFRESH_TOKEN_3" \
     https://oauth2.googleapis.com/tokeninfo

# تحقق من صلاحيات القناة
python -m yt_auto short --slot 1 --date 20250101
```

## 🎯 تحسين الأداء

### زيادة جودة المحتوى

1. استخدم نماذج أفضل:
```bash
# استخدم GPT-4 للفئات الحساسة
OPENAI_API_KEY=... (يكلف أموال)
```

2. زيادة التنويع:
```python
# أضف قوالب جديدة في config.py
TEMPLATES = [
    # أضف 5+ قوالب جديدة
]
```

3. تحسين الصوت:
```bash
# استخدم صوت مختلف
ELEVEN_VOICE_ID="different_id"
```

### تحسين الوصول (SEO)

ملف: `yt_auto/llm.py`
- قم بتحديث الكلمات المفتاحية
- حسّن الأوصاف
- أضف علامات ذات صلة

### تحسين المخاطر

ملف: `yt_auto/manager.py`
```python
# راقب معدل الأخطاء
risk_mgr.get_risk_level()

# عالج المخاطر
risk_mgr.get_recommendations()
```

## 📊 الإحصائيات والتقارير

### إنشاء تقرير يومي

```python
from yt_auto.manager import ContentAnalyzer
from yt_auto.config import load_config

cfg = load_config()
analyzer = ContentAnalyzer(cfg)
recs = analyzer.get_recommendations()

print("=" * 50)
print("تقرير الأداء اليومي")
print("=" * 50)
print(f"أفضل القوالب: {recs['best_templates']}")
print(f"أفضل الأصوات: {recs['best_voices']}")
print(f"أفضل الأوقات: {recs['best_posting_times']}")
print(f"الملخص: {recs['summary']}")
```

### تصدير البيانات

```bash
# تصدير state إلى JSON
cp state/state.json reports/state_$(date +%Y%m%d).json

# تصدير التحليلات
cp state/analysis.json reports/analysis_$(date +%Y%m%d).json
```

## 🔐 الأمان

### حماية المفاتيح

1. لا تضع مفاتيح في الكود
2. استخدم متغيرات البيئة فقط
3. استخدم `.env` المحلي فقط (أضفه إلى .gitignore)

### نسخة احتياطية من الحالة

```bash
# نسخ احتياطية يومية
git add state/
git commit -m "daily state backup"
git push
```

### مراقبة التكرار

```bash
# تحقق من الأسئلة المكررة
grep -r "question" state/state.json

# امسح السجل القديم
python -m yt_auto analyze  # يقوم بالتنظيف التلقائي
```

## 📱 التكامل مع الخدمات الخارجية

### Webhook للإشعارات

أضف إلى `yt_auto/cli.py`:

```python
import requests

def notify_slack(message):
    webhook = os.getenv("SLACK_WEBHOOK")
    requests.post(webhook, json={"text": message})
```

### التكامل مع Google Sheets

```python
from google.colab import auth
auth.authenticate_user()

# تصدير الإحصائيات إلى Sheets
```

## 🎓 الموارد والدراسة

### توثيق YouTube API
- https://developers.google.com/youtube/v3

### توثيق Gemini
- https://ai.google.dev/docs

### توثيق ElevenLabs
- https://elevenlabs.io/docs

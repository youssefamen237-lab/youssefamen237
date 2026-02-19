# Self‑Governing AI YouTube Channel System

A fully automated pipeline that:

* Generates quiz questions via free LLMs (Gemini / Groq)  
* Synthesises natural‑sounding speech (ElevenLabs → gTTS fallback)  
* Creates Shorts (question → CTA → 5‑second countdown → answer) with blurred backgrounds and dynamic thumbnails  
* Publishes 4 Shorts per day at varied times and 4 long‑form compilation videos per week  
* Optimises titles, descriptions, tags, hashtags via the LLM  
* Tracks performance with YouTube Analytics and adapts publishing hour weights automatically  
* Includes fall‑back logic for every external service (LLM, TTS, image, YouTube API)  

All secrets are read from a `.env` file; no credentials are hard‑coded.  
All third‑party services used are free‑tier or open‑source.

## Quick Start

```bash
# 1️⃣ Clone the repo
git clone <repo-url>
cd project_root

# 2️⃣ Create .env (copy from .env.example and fill values)
cp .env.example .env

# 3️⃣ Build Docker image (optional)
docker build -t yt‑bot .

# 4️⃣ Run (Docker)
docker run -d --restart unless-stopped -v $(pwd)/data:/app/data yt‑bot

# Or run locally
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m scripts.main

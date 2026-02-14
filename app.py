#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import base64
import contextlib
import datetime as dt
import hashlib
import json
import logging
import math
import os
import random
import re
import shutil
import string
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dateutil import tz
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
BG_DIR = ASSETS_DIR / "backgrounds"
OUT_DIR = ROOT / "out"
CONFIG_PATH = ROOT / "config.json"

HISTORY_PATH = DATA_DIR / "history.json"
UPLOADS_PATH = DATA_DIR / "uploads.json"

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

DEFAULT_FONT_LINUX = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

SAFE_ASCII = set(string.ascii_letters + string.digits + " .,!?'\"-()/&+%#:@")
BANNED_PATTERNS = [
    r"\bporn\b",
    r"\bsex\b",
    r"\bnude\b",
    r"\bnsfw\b",
    r"\bonlyfans\b",
    r"\bdrug(s)?\b",
    r"\bcocaine\b",
    r"\bheroin\b",
    r"\bmeth\b",
    r"\bsuicide\b",
    r"\bkill(ed|ing)?\b",
    r"\bmurder\b",
    r"\bterror(ism|ist)?\b",
    r"\bbomb(s)?\b",
    r"\bgun(s)?\b",
    r"\bweapon(s)?\b",
    r"\bnazi(s)?\b",
    r"\bhitler\b",
    r"\bracist\b",
    r"\bslur(s)?\b",
    r"\bpolitic(s|al)?\b",
    r"\belection(s)?\b",
    r"\bwar(s)?\b",
    r"\bpalestin(e|ian)?\b",
    r"\bisrael(i)?\b",
    r"\bukrain(e|ian)?\b",
    r"\brussia(n)?\b",
    r"\bcovid(19)?\b",
    r"\bvaccine(s)?\b",
    r"\bbitcoin\b",
    r"\bcrypto(currency)?\b",
    r"\bstock(s)?\b",
    r"\bforex\b",
    r"\bgambl(ing|e)?\b",
    r"\bcasino(s)?\b",
    r"\bbet(s|ting)?\b",
    r"\badult\b",
    r"\bxxx\b",
]
LYRICS_RISK_PATTERNS = [
    r"\blyrics\b",
    r"\bwhich song\b.*\bline\b",
    r"\bwhat song\b.*\bline\b",
    r"\bwhat song\b.*\bthis (line|lyric)\b",
    r"\bfinish the lyric\b",
    r"\bguess the song\b.*\blyric\b",
    r"\bquote from\b",
    r"\bline from\b",
    r"\bfinish the quote\b",
    r"\bwhat (movie|film|show|tv show|tv series)\b.*\b(quote|line|phrase)\b",
    r"\bwhich (movie|film|show|tv show|tv series)\b.*\b(quote|line|phrase)\b",
    r"\".{15,}\"",  # quoted long text
    r"“.{15,}”",
    r"‘.{15,}’",
    r"'.{20,}'",
]

CTA_PHRASES = [
    "If you know the answer before the timer ends, type it in the comments!",
    "Beat the timer—drop your answer in the comments!",
    "Got it fast? Comment your answer before time runs out!",
    "Think you know it? Write your answer in the comments before the countdown ends!",
    "Quick! Comment your answer before the last second!",
    "No cheating—comment your answer before the timer hits zero!",
]

THEMES = [
    {
        "question_fontsize": 72,
        "answer_fontsize": 96,
        "countdown_fontsize": 110,
        "question_y": 0.40,
        "countdown_y": 0.78,
        "box_alpha": 0.35,
        "show_bar": True,
    },
    {
        "question_fontsize": 76,
        "answer_fontsize": 104,
        "countdown_fontsize": 120,
        "question_y": 0.42,
        "countdown_y": 0.80,
        "box_alpha": 0.30,
        "show_bar": False,
    },
    {
        "question_fontsize": 68,
        "answer_fontsize": 92,
        "countdown_fontsize": 108,
        "question_y": 0.38,
        "countdown_y": 0.76,
        "box_alpha": 0.40,
        "show_bar": True,
    },
]


@dataclass
class Config:
    language: str
    timezone: str
    shorts_per_day: int
    lead_seconds: float
    countdown_seconds: int
    answer_seconds: float
    schedule_times: List[str]
    long_publish_time: str
    jitter_minutes: int
    duplicate_days: int
    max_generation_attempts: int
    max_api_retries: int
    groq_model: str
    gemini_model: str
    edge_voice: str
    edge_rate_min: str
    edge_rate_max: str
    edge_pitch_min: str
    edge_pitch_max: str
    notify_subscribers_for_long: bool
    notify_subscribers_for_shorts: bool


def load_config() -> Config:
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        raw = {}
    return Config(
        language=str(raw.get("language", "en")),
        timezone=str(raw.get("timezone", "UTC")),
        shorts_per_day=int(raw.get("shorts_per_day", 4)),
        lead_seconds=float(raw.get("lead_seconds", 2.0)),
        countdown_seconds=int(raw.get("countdown_seconds", 8)),
        answer_seconds=float(raw.get("answer_seconds", 1.0)),
        schedule_times=list(raw.get("schedule_times", ["15:10", "19:20", "23:05", "03:15"])),
        long_publish_time=str(raw.get("long_publish_time", "23:55")),
        jitter_minutes=int(raw.get("jitter_minutes", 20)),
        duplicate_days=int(raw.get("duplicate_days", 15)),
        max_generation_attempts=int(raw.get("max_generation_attempts", 12)),
        max_api_retries=int(raw.get("max_api_retries", 6)),
        groq_model=str(raw.get("groq_model", os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"))),
        gemini_model=str(raw.get("gemini_model", os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))),
        edge_voice=str(raw.get("edge_voice", os.getenv("EDGE_TTS_VOICE", "en-US-JennyNeural"))),
        edge_rate_min=str(raw.get("edge_rate_min", "-6%")),
        edge_rate_max=str(raw.get("edge_rate_max", "+6%")),
        edge_pitch_min=str(raw.get("edge_pitch_min", "-2Hz")),
        edge_pitch_max=str(raw.get("edge_pitch_max", "+2Hz")),
        notify_subscribers_for_long=bool(raw.get("notify_subscribers_for_long", True)),
        notify_subscribers_for_shorts=bool(raw.get("notify_subscribers_for_shorts", False)),
    )


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    BG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("Failed to read JSON: %s", path)
    return default


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def rfc3339(dt_obj: dt.datetime) -> str:
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return dt_obj.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_hhmm(s: str) -> Tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s.strip())
    if not m:
        raise ValueError(f"Invalid time: {s}")
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise ValueError(f"Invalid time: {s}")
    return hh, mm


def jitter_minutes(minutes: int) -> int:
    if minutes <= 0:
        return 0
    return random.randint(-minutes, minutes)


def next_publish_times(cfg: Config, count: int, now: Optional[dt.datetime] = None) -> List[dt.datetime]:
    tzinfo = tz.gettz(cfg.timezone)
    if tzinfo is None:
        tzinfo = dt.timezone.utc
    if now is None:
        now = utc_now()
    now_local = now.astimezone(tzinfo)

    times: List[dt.datetime] = []
    for i in range(count):
        hh, mm = parse_hhmm(cfg.schedule_times[i % len(cfg.schedule_times)])
        base = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        base = base + dt.timedelta(minutes=jitter_minutes(cfg.jitter_minutes))
        if base <= now_local + dt.timedelta(minutes=10):
            base = base + dt.timedelta(days=1)
        times.append(base.astimezone(dt.timezone.utc))
    times.sort()
    return times


def compute_long_publish_time(cfg: Config, after: dt.datetime, now: Optional[dt.datetime] = None) -> dt.datetime:
    tzinfo = tz.gettz(cfg.timezone) or dt.timezone.utc
    if now is None:
        now = utc_now()
    after_local = after.astimezone(tzinfo)
    hh, mm = parse_hhmm(cfg.long_publish_time)
    candidate = after_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    candidate = candidate + dt.timedelta(minutes=jitter_minutes(cfg.jitter_minutes))
    if candidate <= after_local + dt.timedelta(minutes=5):
        candidate = candidate + dt.timedelta(days=1)
    if candidate <= now.astimezone(tzinfo) + dt.timedelta(minutes=10):
        candidate = candidate + dt.timedelta(days=1)
    return candidate.astimezone(dt.timezone.utc)


def normalize_for_dedupe(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return s.strip()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def within_days(ts_iso: str, days: int, now: Optional[dt.datetime] = None) -> bool:
    try:
        when = dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return False
    if now is None:
        now = utc_now()
    return when >= (now - dt.timedelta(days=days))


def within_hours(ts_iso: str, hours: int, now: Optional[dt.datetime] = None) -> bool:
    try:
        when = dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return False
    if now is None:
        now = utc_now()
    return when >= (now - dt.timedelta(hours=hours))


def clean_history(history: List[Dict[str, Any]], keep_days: int = 90) -> List[Dict[str, Any]]:
    now = utc_now()
    out = []
    for item in history:
        ts = str(item.get("ts", ""))
        if within_days(ts, keep_days, now=now):
            out.append(item)
    return out


class RateLimiter:
    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = float(min_interval_s)
        self._next_ok: float = 0.0

    def wait(self) -> None:
        now = time.time()
        if now < self._next_ok:
            time.sleep(self._next_ok - now)
        self._next_ok = time.time() + self.min_interval_s


def with_backoff(
    fn,
    *,
    retries: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.3,
    retry_on: Tuple[type, ...] = (Exception,),
):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except retry_on as e:
            last_exc = e
            if attempt >= retries:
                break
            delay = min(max_delay, base_delay * (2**attempt))
            delay = delay * (1.0 + random.uniform(-jitter, jitter))
            delay = max(0.2, delay)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found")
    blob = text[start : end + 1]
    return json.loads(blob)


def is_safe_text(s: str) -> bool:
    if not s or len(s.strip()) == 0:
        return False
    lower = s.lower()
    for pat in BANNED_PATTERNS:
        if re.search(pat, lower):
            return False
    for pat in LYRICS_RISK_PATTERNS:
        if re.search(pat, s, flags=re.IGNORECASE | re.DOTALL):
            return False
    # keep it mostly simple ASCII (drawtext + consistency)
    if any(ch not in SAFE_ASCII and ch not in {"\n", "\t"} for ch in s):
        return False
    return True


def wrap_lines(text: str, max_chars: int = 26, max_lines: int = 3) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    words = text.split(" ")
    lines: List[str] = []
    current: List[str] = []
    for w in words:
        if not current:
            current = [w]
            continue
        trial = " ".join(current + [w])
        if len(trial) <= max_chars:
            current.append(w)
        else:
            lines.append(" ".join(current))
            current = [w]
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines and current:
        lines.append(" ".join(current))
    lines = [ln.strip() for ln in lines if ln.strip()]
    return "\n".join(lines[:max_lines])


def pick_theme() -> Dict[str, Any]:
    base = random.choice(THEMES)
    # shallow copy
    theme = dict(base)
    # micro-variation
    theme["question_fontsize"] = int(theme["question_fontsize"] + random.randint(-2, 2))
    theme["answer_fontsize"] = int(theme["answer_fontsize"] + random.randint(-2, 2))
    theme["countdown_fontsize"] = int(theme["countdown_fontsize"] + random.randint(-4, 4))
    theme["question_y"] = float(theme["question_y"] + random.uniform(-0.01, 0.01))
    theme["countdown_y"] = float(theme["countdown_y"] + random.uniform(-0.01, 0.01))
    theme["box_alpha"] = float(min(0.5, max(0.2, theme["box_alpha"] + random.uniform(-0.03, 0.03))))
    return theme


def ffmpeg_exists() -> bool:
    return shutil.which("ffmpeg") is not None


def run_cmd(cmd: List[str], *, timeout: int = 900) -> None:
    logging.debug("Running command: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if proc.returncode != 0:
        logging.error("Command failed (%s): %s", proc.returncode, " ".join(cmd))
        logging.error("STDOUT:\n%s", proc.stdout[-4000:])
        logging.error("STDERR:\n%s", proc.stderr[-4000:])
        raise RuntimeError(f"Command failed: {cmd[0]}")


def pick_local_background(exclude: Optional[set[str]] = None) -> Optional[Path]:
    if not BG_DIR.exists():
        return None
    files: List[Path] = []
    for p in BG_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            if exclude and str(p.resolve()) in exclude:
                continue
            files.append(p)
    if not files:
        return None
    return random.choice(files)


def download_background_from_pexels(tmp_dir: Path) -> Optional[Path]:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        return None
    headers = {"Authorization": api_key}
    query = random.choice(["abstract", "nature", "bokeh", "gradient", "texture", "city lights"])
    url = "https://api.pexels.com/v1/search"
    params = {"query": query, "per_page": 20, "orientation": "portrait"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    photos = data.get("photos") or []
    if not photos:
        return None
    photo = random.choice(photos)
    src = (photo.get("src") or {}).get("portrait") or (photo.get("src") or {}).get("large")
    if not src:
        return None
    img = requests.get(src, timeout=60)
    if img.status_code != 200:
        return None
    out = tmp_dir / f"pexels_{photo.get('id','')}.jpg"
    out.write_bytes(img.content)
    return out


def download_background_from_pixabay(tmp_dir: Path) -> Optional[Path]:
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None
    query = random.choice(["abstract", "background", "nature", "bokeh", "gradient", "texture"])
    url = "https://pixabay.com/api/"
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "orientation": "vertical",
        "safesearch": "true",
        "per_page": 50,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    hits = data.get("hits") or []
    if not hits:
        return None
    hit = random.choice(hits)
    src = hit.get("largeImageURL") or hit.get("webformatURL")
    if not src:
        return None
    img = requests.get(src, timeout=60)
    if img.status_code != 200:
        return None
    out = tmp_dir / f"pixabay_{hit.get('id','')}.jpg"
    out.write_bytes(img.content)
    return out


def download_background_from_unsplash(tmp_dir: Path) -> Optional[Path]:
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not access_key:
        return None
    query = random.choice(["abstract", "texture", "bokeh", "nature", "gradient", "pattern"])
    url = "https://api.unsplash.com/photos/random"
    params = {"query": query, "orientation": "portrait", "content_filter": "high"}
    headers = {"Authorization": f"Client-ID {access_key}"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    src = (data.get("urls") or {}).get("regular") or (data.get("urls") or {}).get("full")
    if not src:
        return None
    img = requests.get(src, timeout=60)
    if img.status_code != 200:
        return None
    out = tmp_dir / f"unsplash_{data.get('id','')}.jpg"
    out.write_bytes(img.content)
    return out


def get_background_image(tmp_dir: Path, exclude: Optional[set[str]] = None) -> Path:
    local = pick_local_background(exclude=exclude)
    if local is not None:
        return local

    downloaders = [
        download_background_from_pexels,
        download_background_from_pixabay,
        download_background_from_unsplash,
    ]
    random.shuffle(downloaders)
    for dl in downloaders:
        try:
            out = with_backoff(lambda: dl(tmp_dir), retries=2, base_delay=2.0)
            if out is not None and out.exists() and out.stat().st_size > 10_000:
                return out
        except Exception:
            logging.warning("Background downloader failed: %s", dl.__name__)
            continue

    # last resort: solid color image
    out = tmp_dir / "fallback_bg.jpg"
    Image.new("RGB", (1080, 1920), (15, 15, 15)).save(out, format="JPEG", quality=95)
    return out


def gemini_generate_json(prompt: str, *, api_key: str, model: str, retries: int) -> Dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": api_key}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topP": 0.95,
            "maxOutputTokens": 512,
        },
    }

    def _call() -> Dict[str, Any]:
        r = requests.post(url, params=params, json=payload, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = ""
        for cand in data.get("candidates") or []:
            content = cand.get("content") or {}
            parts = content.get("parts") or []
            for p in parts:
                t = p.get("text")
                if t:
                    text += t
        if not text:
            raise RuntimeError("Gemini empty response")
        return extract_json_object(text)

    return with_backoff(_call, retries=retries, base_delay=1.5, max_delay=20.0)


def groq_generate_json(prompt: str, *, api_key: str, model: str, retries: int) -> Dict[str, Any]:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant that outputs ONLY valid JSON. No markdown. No extra text.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
        "top_p": 0.95,
        "max_tokens": 512,
    }

    def _call() -> Dict[str, Any]:
        r = requests.post(url, headers=headers, json=payload, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        msg = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        if not msg:
            raise RuntimeError("Groq empty response")
        return extract_json_object(msg)

    return with_backoff(_call, retries=retries, base_delay=1.5, max_delay=20.0)


def local_fallback_question() -> Dict[str, Any]:
    bank = [
        ("Geography", "What is the capital of Australia?", "Canberra"),
        ("Science", "What gas do plants absorb from the air?", "Carbon dioxide"),
        ("History", "In which continent is Egypt located?", "Africa"),
        ("Language", "Which letter comes after 'G' in the English alphabet?", "H"),
        ("Space", "What is the name of our galaxy?", "Milky Way"),
        ("Animals", "Which animal is known as the largest mammal?", "Blue whale"),
        ("Food", "Sushi is a traditional cuisine from which country?", "Japan"),
        ("Sports", "How many players are on a soccer team on the field?", "11"),
    ]
    cat, q, a = random.choice(bank)
    return {"category": cat, "question": q, "answer": a, "difficulty": "easy"}


def validate_qa(obj: Dict[str, Any]) -> Tuple[bool, str]:
    q = str(obj.get("question", "")).strip()
    a = str(obj.get("answer", "")).strip()
    if not q or not a:
        return False, "Empty question/answer"
    if len(q) < 8 or len(q) > 110:
        return False, "Question length"
    if len(a) < 1 or len(a) > 40:
        return False, "Answer length"
    if not q.endswith("?"):
        return False, "Question must end with ?"
    if not is_safe_text(q) or not is_safe_text(a):
        return False, "Unsafe content"
    # avoid too many options / clutter
    if q.count("\n") > 2:
        return False, "Too many lines"
    if any(ch in q for ch in ["\r", "\0"]):
        return False, "Bad chars"
    return True, "ok"


def build_question_prompt(category: str) -> str:
    return (
        "Create ONE short trivia question for a YouTube Short for an English-speaking audience.\n"
        "Return ONLY a JSON object with keys: category, question, answer, difficulty.\n"
        "Rules:\n"
        "- The question must be original, safe for all audiences, and NOT political.\n"
        "- No copyrighted lyrics or long quotes. No song lyric lines.\n"
        "- Keep the question concise (<= 110 characters), and make the answer short (<= 40 characters).\n"
        "- The question MUST end with a question mark.\n"
        "- Use simple ASCII characters only (no emojis).\n"
        f"- Category: {category}\n"
        "Output example:\n"
        '{"category":"Geography","question":"What is the capital of Australia?","answer":"Canberra","difficulty":"easy"}'
    )


def generate_unique_question(cfg: Config, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    recent = [h for h in history if within_days(str(h.get("ts", "")), cfg.duplicate_days)]
    recent_hashes = {str(h.get("hash", "")) for h in recent if h.get("hash")}

    categories = [
        "Geography",
        "Science",
        "History",
        "Movies & TV (no quotes)",
        "Music (no lyrics)",
        "Sports",
        "Animals",
        "Food",
        "Language",
        "Space",
        "Technology (basic)",
        "Random Facts",
    ]

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()

    providers = []
    if gemini_key:
        providers.append(
            (
                "gemini",
                lambda p: gemini_generate_json(p, api_key=gemini_key, model=cfg.gemini_model, retries=cfg.max_api_retries),
            )
        )
    if groq_key:
        providers.append(
            (
                "groq",
                lambda p: groq_generate_json(p, api_key=groq_key, model=cfg.groq_model, retries=cfg.max_api_retries),
            )
        )
    providers.append(("local", lambda p: local_fallback_question()))

    for attempt in range(cfg.max_generation_attempts):
        category = random.choice(categories)
        prompt = build_question_prompt(category)

        last_err = None
        for name, fn in providers:
            try:
                obj = fn(prompt)
                ok, reason = validate_qa(obj)
                if not ok:
                    last_err = f"{name}: {reason}"
                    continue

                q = str(obj["question"]).strip()
                a = str(obj["answer"]).strip()
                h = sha256_text(normalize_for_dedupe(q) + "|" + normalize_for_dedupe(a))
                if h in recent_hashes:
                    last_err = f"{name}: duplicate"
                    continue

                obj["category"] = str(obj.get("category", category)).strip() or category
                obj["difficulty"] = str(obj.get("difficulty", "easy")).strip() or "easy"
                obj["_provider"] = name
                obj["_hash"] = h
                return obj
            except Exception as e:
                last_err = f"{name}: {e}"
                continue

        logging.warning("Question generation attempt %d failed: %s", attempt + 1, last_err)

    raise RuntimeError("Failed to generate a unique question after many attempts")


def build_metadata_prompt(kind: str, question: str, answer: str, category: str) -> str:
    hashtags = "#shorts #quiz #trivia" if kind == "short" else "#quiz #trivia"
    return (
        f"Create YouTube metadata for a {kind} video in English.\n"
        "Return ONLY a JSON object with keys: title, description, tags, hashtags.\n"
        "Rules:\n"
        "- Must be safe, family-friendly, non-political.\n"
        "- Must NOT be misleading or clickbait. No promises.\n"
        "- Title max 90 chars.\n"
        "- Description should include a short call-to-action to subscribe.\n"
        "- Tags must be a JSON array of strings, total combined length <= 450 chars.\n"
        f"- Include these hashtags at the end of description: {hashtags}\n"
        f"- Category context: {category}\n"
        f"- Question: {question}\n"
        f"- Answer: {answer}\n"
        "Output example:\n"
        '{"title":"Can you answer in 8 seconds?","description":"Try this quick question! Subscribe for more. #shorts #quiz #trivia","tags":["quiz","trivia","shorts"],"hashtags":"#shorts #quiz #trivia"}'
    )


def validate_metadata(meta: Dict[str, Any], kind: str) -> Tuple[bool, str]:
    title = str(meta.get("title", "")).strip()
    desc = str(meta.get("description", "")).strip()
    tags = meta.get("tags", [])
    hashtags = str(meta.get("hashtags", "")).strip()

    if not title or len(title) > 95:
        return False, "Bad title"
    if not desc or len(desc) < 40 or len(desc) > 4500:
        return False, "Bad description"
    if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
        return False, "Bad tags"
    joined = ",".join(tags)
    if len(joined) > 450:
        return False, "Tags too long"
    if not is_safe_text(title) or not is_safe_text(desc):
        return False, "Unsafe text"
    if kind == "short" and "#shorts" not in (desc.lower() + " " + hashtags.lower()):
        return False, "Missing #shorts"
    return True, "ok"


def fallback_metadata(kind: str, question: str, category: str) -> Dict[str, Any]:
    base_titles = [
        "Can you answer in 8 seconds?",
        "Quick trivia challenge!",
        "Only 8 seconds — can you get it?",
        "Fast quiz — comment your answer!",
        "8-second brain teaser!",
    ]
    title = random.choice(base_titles)
    hint = re.sub(r"[^A-Za-z0-9 ]+", "", question).strip()
    if len(hint) > 36:
        hint = hint[:36].rstrip()
    if hint:
        title = f"{title} {hint}"
    title = title[:90].strip()

    hashtags = "#shorts #quiz #trivia" if kind == "short" else "#quiz #trivia"
    desc = (
        f"Category: {category}\n\n"
        "Try to answer before the timer ends, then comment your guess!\n"
        "Subscribe for daily quizzes and trivia.\n\n"
        f"{hashtags}"
    )
    tags = ["quiz", "trivia", "challenge", "brain teaser", "general knowledge"]
    if kind == "short":
        tags.append("shorts")
    return {"title": title, "description": desc, "tags": tags, "hashtags": hashtags}


def generate_metadata(cfg: Config, kind: str, question: str, answer: str, category: str) -> Dict[str, Any]:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()

    providers = []
    if gemini_key:
        providers.append(
            (
                "gemini",
                lambda p: gemini_generate_json(p, api_key=gemini_key, model=cfg.gemini_model, retries=cfg.max_api_retries),
            )
        )
    if groq_key:
        providers.append(
            (
                "groq",
                lambda p: groq_generate_json(p, api_key=groq_key, model=cfg.groq_model, retries=cfg.max_api_retries),
            )
        )
    providers.append(("fallback", lambda p: fallback_metadata(kind, question, category)))

    prompt = build_metadata_prompt(kind, question, answer, category)

    for name, fn in providers:
        try:
            meta = fn(prompt)
            ok, reason = validate_metadata(meta, kind)
            if not ok:
                logging.warning("Metadata provider %s invalid: %s", name, reason)
                continue
            meta["_provider"] = name
            return meta
        except Exception as e:
            logging.warning("Metadata provider %s failed: %s", name, e)
            continue

    return fallback_metadata(kind, question, category)


async def edge_tts_async(text: str, out_mp3: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_mp3))


def tts_edge(text: str, out_mp3: Path, cfg: Config) -> None:
    voice = cfg.edge_voice
    rate = random.choice([cfg.edge_rate_min, "0%", cfg.edge_rate_max])
    pitch = random.choice([cfg.edge_pitch_min, "0Hz", cfg.edge_pitch_max])
    asyncio.run(edge_tts_async(text, out_mp3, voice, rate, pitch))


def tts_gtts(text: str, out_mp3: Path) -> None:
    from gtts import gTTS  # type: ignore

    tts = gTTS(text=text, lang="en", slow=False)
    tts.save(str(out_mp3))


def tts_espeak(text: str, out_mp3: Path) -> None:
    tmp_wav = out_mp3.with_suffix(".wav")
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        raise RuntimeError("espeak not installed")
    run_cmd([espeak, "-v", "en-us", "-s", "165", "-w", str(tmp_wav), text], timeout=120)
    run_cmd(["ffmpeg", "-y", "-i", str(tmp_wav), "-vn", "-acodec", "libmp3lame", "-q:a", "4", str(out_mp3)], timeout=180)
    with contextlib.suppress(Exception):
        tmp_wav.unlink()


def generate_tts_audio(text: str, out_mp3: Path, cfg: Config) -> str:
    providers = [
        ("edge", lambda: tts_edge(text, out_mp3, cfg)),
        ("gtts", lambda: tts_gtts(text, out_mp3)),
        ("espeak", lambda: tts_espeak(text, out_mp3)),
    ]
    last_err = None
    for name, fn in providers:
        try:
            fn()
            if out_mp3.exists() and out_mp3.stat().st_size > 5_000:
                return name
        except Exception as e:
            last_err = e
            logging.warning("TTS provider %s failed: %s", name, e)
            continue
    raise RuntimeError(f"TTS failed: {last_err}")


def render_short_video(
    *,
    cfg: Config,
    question: str,
    answer: str,
    audio_mp3: Path,
    background_img: Path,
    out_mp4: Path,
    theme: Dict[str, Any],
) -> None:
    if not ffmpeg_exists():
        raise RuntimeError("ffmpeg not found")

    fontfile = os.getenv("FONT_FILE", DEFAULT_FONT_LINUX)
    if not Path(fontfile).exists():
        fontfile = DEFAULT_FONT_LINUX

    lead = float(cfg.lead_seconds)
    countdown = int(cfg.countdown_seconds)
    reveal = float(cfg.answer_seconds)
    total = float(lead + countdown + reveal)

    q_wrapped = wrap_lines(question, max_chars=26, max_lines=3)
    a_wrapped = wrap_lines(answer, max_chars=22, max_lines=2)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        q_file = td_path / "question.txt"
        a_file = td_path / "answer.txt"
        q_file.write_text(q_wrapped, encoding="utf-8")
        a_file.write_text(a_wrapped, encoding="utf-8")

        question_y = float(theme["question_y"])
        countdown_y = float(theme["countdown_y"])
        q_fs = int(theme["question_fontsize"])
        a_fs = int(theme["answer_fontsize"])
        c_fs = int(theme["countdown_fontsize"])
        box_alpha = float(theme["box_alpha"])
        show_bar = bool(theme.get("show_bar", True))

        countdown_expr = f"%{{eif\\\\:max(1,ceil({countdown}-t+{lead}))\\\\:d}}"

        q_draw = (
            f"drawtext=fontfile='{fontfile}':textfile='{q_file}':reload=0:"
            f"fontcolor=white:fontsize={q_fs}:line_spacing=10:"
            f"borderw=5:bordercolor=black:"
            f"box=1:boxcolor=black@{box_alpha}:boxborderw=24:"
            f"x=(w-text_w)/2:y=(h*{question_y})-(text_h/2)"
        )

        c_draw = (
            f"drawtext=fontfile='{fontfile}':text='{countdown_expr}':"
            f"fontcolor=white:fontsize={c_fs}:"
            f"borderw=6:bordercolor=black:"
            f"x=(w-text_w)/2:y=(h*{countdown_y})-(text_h/2):"
            f"enable='between(t,{lead},{lead}+{countdown}-0.05)'"
        )

        bar_bg = (
            f"drawbox=x=w*0.2:y=h*{min(0.90, countdown_y+0.05)}:w=w*0.6:h=26:"
            f"color=white@0.18:t=fill:enable='between(t,{lead},{lead}+{countdown}-0.05)'"
        )
        bar_fg = (
            f"drawbox=x=w*0.2:y=h*{min(0.90, countdown_y+0.05)}:"
            f"w=(w*0.6)*(1-((t-{lead})/{countdown})):h=26:"
            f"color=white@0.65:t=fill:enable='between(t,{lead},{lead}+{countdown}-0.05)'"
        )

        a_draw = (
            f"drawtext=fontfile='{fontfile}':textfile='{a_file}':reload=0:"
            f"fontcolor=white:fontsize={a_fs}:line_spacing=8:"
            f"borderw=6:bordercolor=black:"
            f"box=1:boxcolor=black@0.45:boxborderw=28:"
            f"x=(w-text_w)/2:y=(h*0.50)-(text_h/2):"
            f"enable='between(t,{total - reveal},{total})'"
        )

        filters = [
            "scale=1080:1920:force_original_aspect_ratio=increase",
            "crop=1080:1920",
            "boxblur=20:1",
            "format=yuv420p",
            q_draw,
            c_draw,
        ]
        if show_bar:
            filters.append(bar_bg)
            filters.append(bar_fg)
        filters.append(a_draw)

        vf = ",".join(filters)

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(background_img),
            "-i",
            str(audio_mp3),
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]aformat=channel_layouts=stereo:sample_rates=44100,apad,atrim=0:{total},asetpts=N/SR/TB[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            str(total),
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out_mp4),
        ]
        run_cmd(cmd, timeout=900)


def make_thumbnail(
    *,
    title: str,
    question: str,
    background_img: Path,
    out_jpg: Path,
) -> None:
    W, H = 1280, 720
    img = Image.open(background_img).convert("RGB")
    img_ratio = img.width / img.height
    target_ratio = W / H
    if img_ratio > target_ratio:
        new_h = img.height
        new_w = int(new_h * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, new_h))
    else:
        new_w = img.width
        new_h = int(new_w / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, new_w, top + new_h))

    img = img.resize((W, H), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(radius=10))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_path = os.getenv("FONT_FILE", DEFAULT_FONT_LINUX)
    if not Path(font_path).exists():
        font_path = DEFAULT_FONT_LINUX

    try:
        title_font = ImageFont.truetype(font_path, 64)
        q_font = ImageFont.truetype(font_path, 52)
    except Exception:
        title_font = ImageFont.load_default()
        q_font = ImageFont.load_default()

    panel_h = 320
    draw.rectangle([(0, H - panel_h), (W, H)], fill=(0, 0, 0, 165))

    title_text = title.strip()
    q_text = re.sub(r"\s+", " ", question.strip())
    if len(q_text) > 70:
        q_text = q_text[:70].rstrip() + "…"

    def _center_text(y: int, text: str, font: ImageFont.FreeTypeFont) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 220))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    _center_text(H - panel_h + 30, title_text, title_font)
    _center_text(H - panel_h + 140, q_text, q_font)

    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    out.save(out_jpg, format="JPEG", quality=92, optimize=True)


def to_16x9_segment(in_mp4: Path, out_mp4: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(in_mp4),
        "-filter_complex",
        (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1920:1080,boxblur=20:1[bg2];"
            "[fg]scale=-1:1080[fg2];"
            "[bg2][fg2]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_mp4),
    ]
    run_cmd(cmd, timeout=900)


def make_title_card(text: str, duration_s: float, background_img: Path, out_mp4: Path) -> None:
    fontfile = os.getenv("FONT_FILE", DEFAULT_FONT_LINUX)
    if not Path(fontfile).exists():
        fontfile = DEFAULT_FONT_LINUX

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        tfile = td_path / "title.txt"
        tfile.write_text(wrap_lines(text, max_chars=22, max_lines=3), encoding="utf-8")

        vf = ",".join(
            [
                "scale=1920:1080:force_original_aspect_ratio=increase",
                "crop=1920:1080",
                "boxblur=20:1",
                "format=yuv420p",
                (
                    f"drawtext=fontfile='{fontfile}':textfile='{tfile}':reload=0:"
                    "fontcolor=white:fontsize=96:line_spacing=12:"
                    "borderw=6:bordercolor=black:"
                    "box=1:boxcolor=black@0.45:boxborderw=30:"
                    "x=(w-text_w)/2:y=(h-text_h)/2"
                ),
            ]
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(background_img),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]atrim=0:{duration_s},asetpts=N/SR/TB[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            str(duration_s),
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out_mp4),
        ]
        run_cmd(cmd, timeout=600)


def concat_videos(inputs: List[Path], out_mp4: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        list_file = td_path / "concat.txt"
        lines = []
        for p in inputs:
            lines.append(f"file '{p.as_posix()}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out_mp4),
        ]
        run_cmd(cmd, timeout=1800)


def render_long_compilation(
    *,
    cfg: Config,
    short_paths: List[Path],
    background_img: Path,
    out_mp4: Path,
) -> None:
    if len(short_paths) == 0:
        raise ValueError("No shorts to compile")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        segments: List[Path] = []

        intro = td_path / "intro.mp4"
        make_title_card("Daily Quiz Compilation", duration_s=7.0, background_img=background_img, out_mp4=intro)
        segments.append(intro)

        for idx, sp in enumerate(short_paths, start=1):
            seg = td_path / f"seg_{idx:02d}.mp4"
            to_16x9_segment(sp, seg)
            segments.append(seg)
            if idx != len(short_paths):
                mid = td_path / f"mid_{idx:02d}.mp4"
                make_title_card("Next question…", duration_s=2.5, background_img=background_img, out_mp4=mid)
                segments.append(mid)

        outro = td_path / "outro.mp4"
        make_title_card("Comment your score & subscribe!", duration_s=7.0, background_img=background_img, out_mp4=outro)
        segments.append(outro)

        concat_videos(segments, out_mp4)


def get_youtube_service() -> Any:
    client_id = os.getenv("YT_CLIENT_ID_1", "").strip()
    client_secret = os.getenv("YT_CLIENT_SECRET_1", "").strip()
    refresh_token = os.getenv("YT_REFRESH_TOKEN_1", "").strip()

    if not client_id or not client_secret or not refresh_token:
        client_id = os.getenv("YT_CLIENT_ID_2", "").strip()
        client_secret = os.getenv("YT_CLIENT_SECRET_2", "").strip()
        refresh_token = os.getenv("YT_REFRESH_TOKEN_2", "").strip()

    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError("Missing YouTube OAuth credentials (client id/secret/refresh token)")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES,
    )
    creds.refresh(GoogleAuthRequest())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def youtube_upload(
    service: Any,
    *,
    video_path: Path,
    title: str,
    description: str,
    tags: List[str],
    publish_at: Optional[dt.datetime],
    notify_subscribers: bool,
) -> str:
    body: Dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": "public" if publish_at is None else "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at is not None:
        body["status"]["publishAt"] = rfc3339(publish_at)

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=1024 * 1024 * 8)

    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=bool(notify_subscribers),
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logging.info("Upload progress: %.1f%%", status.progress() * 100)

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"Upload failed: {response}")
    return str(video_id)


def youtube_set_thumbnail(service: Any, *, video_id: str, thumbnail_path: Path) -> None:
    media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg", resumable=False)
    service.thumbnails().set(videoId=video_id, media_body=media).execute()


def safe_tags(meta_tags: List[str]) -> List[str]:
    cleaned: List[str] = []
    for t in meta_tags:
        t2 = re.sub(r"\s+", " ", str(t)).strip()
        if not t2:
            continue
        if len(t2) > 40:
            t2 = t2[:40].rstrip()
        if not is_safe_text(t2):
            continue
        cleaned.append(t2)
    seen = set()
    out: List[str] = []
    for t in cleaned:
        k = normalize_for_dedupe(t)
        if k and k not in seen:
            out.append(t)
            seen.add(k)
    return out[:18]


def build_voice_text(question: str) -> str:
    cta = random.choice(CTA_PHRASES)
    return f"{question} {cta}"


def main() -> None:
    setup_logging()
    ensure_dirs()

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bootstrap", "daily"], required=True)
    args = parser.parse_args()

    cfg = load_config()

    history_obj = load_json(HISTORY_PATH, default={"items": []})
    uploads_obj = load_json(UPLOADS_PATH, default={"items": []})

    history_items: List[Dict[str, Any]] = list(history_obj.get("items") or [])
    uploads_items: List[Dict[str, Any]] = list(uploads_obj.get("items") or [])
    history_items = clean_history(history_items, keep_days=120)

    # Idempotency guard: avoid double-posting if the workflow is re-run within a short window
    if args.mode == "daily":
        now = utc_now()
        recent_shorts = [
            u for u in uploads_items
            if str(u.get("kind", "")) == "short" and within_hours(str(u.get("ts", "")), 20, now=now)
        ]
        if len(recent_shorts) >= cfg.shorts_per_day:
            logging.info("Daily run skipped: already uploaded %d shorts in the last 20 hours.", len(recent_shorts))
            return

    service = get_youtube_service()

    api_rl = RateLimiter(min_interval_s=0.8)

    def _sleep_human(min_s: float, max_s: float) -> None:
        time.sleep(random.uniform(min_s, max_s))

    target_count = 1 if args.mode == "bootstrap" else cfg.shorts_per_day
    publish_schedule: List[Optional[dt.datetime]]
    if args.mode == "bootstrap":
        publish_schedule = [None]
    else:
        publish_schedule = next_publish_times(cfg, target_count)

    used_backgrounds: set[str] = set()
    generated_shorts: List[Dict[str, Any]] = []

    consecutive_failures = 0
    max_total_attempts = target_count + 6

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        attempt = 0
        while len(generated_shorts) < target_count and attempt < max_total_attempts:
            attempt += 1
            idx = len(generated_shorts)
            publish_at = publish_schedule[idx] if idx < len(publish_schedule) else None

            try:
                api_rl.wait()
                qa = generate_unique_question(cfg, history_items)

                q = str(qa["question"]).strip()
                a = str(qa["answer"]).strip()
                category = str(qa["category"]).strip()

                bg = get_background_image(td_path, exclude=used_backgrounds)
                with contextlib.suppress(Exception):
                    used_backgrounds.add(str(bg.resolve()))

                voice_text = build_voice_text(q)
                audio_path = td_path / f"tts_{idx+1:02d}.mp3"

                api_rl.wait()
                tts_provider = with_backoff(
                    lambda: generate_tts_audio(voice_text, audio_path, cfg),
                    retries=2,
                    base_delay=2.0,
                    max_delay=10.0,
                )
                logging.info("TTS provider used: %s", tts_provider)

                theme = pick_theme()
                short_mp4 = td_path / f"short_{idx+1:02d}.mp4"
                render_short_video(
                    cfg=cfg,
                    question=q,
                    answer=a,
                    audio_mp3=audio_path,
                    background_img=bg,
                    out_mp4=short_mp4,
                    theme=theme,
                )

                meta = generate_metadata(cfg, "short", q, a, category)
                title = str(meta["title"]).strip()
                desc = str(meta["description"]).strip()
                tags = safe_tags(list(meta.get("tags") or []))
                if "shorts" not in ",".join(tags).lower():
                    tags.append("shorts")

                thumb = td_path / f"thumb_short_{idx+1:02d}.jpg"
                make_thumbnail(title=title, question=q, background_img=bg, out_jpg=thumb)

                api_rl.wait()
                vid = youtube_upload(
                    service,
                    video_path=short_mp4,
                    title=title,
                    description=desc,
                    tags=tags,
                    publish_at=publish_at,
                    notify_subscribers=cfg.notify_subscribers_for_shorts,
                )
                logging.info("Uploaded short videoId=%s publish_at=%s", vid, publish_at)

                with contextlib.suppress(Exception):
                    youtube_set_thumbnail(service, video_id=vid, thumbnail_path=thumb)

                now_iso = rfc3339(utc_now())
                history_items.append(
                    {
                        "ts": now_iso,
                        "hash": qa["_hash"],
                        "question": q,
                        "answer": a,
                        "category": category,
                    }
                )
                uploads_items.append(
                    {
                        "ts": now_iso,
                        "kind": "short",
                        "video_id": vid,
                        "title": title,
                        "publish_at": None if publish_at is None else rfc3339(publish_at),
                    }
                )

                generated_shorts.append(
                    {
                        "qa": qa,
                        "meta": meta,
                        "video_path": short_mp4,
                        "video_id": vid,
                        "publish_at": publish_at,
                        "background": str(bg),
                    }
                )

                consecutive_failures = 0
                _sleep_human(18.0, 55.0)

            except Exception as e:
                consecutive_failures += 1
                logging.exception("Short pipeline failed (attempt %d/%d): %s", attempt, max_total_attempts, e)
                _sleep_human(8.0, 20.0)
                if consecutive_failures >= 3:
                    raise RuntimeError("Too many consecutive failures; stopping for safety.")
                continue

        if not generated_shorts:
            raise RuntimeError("No Shorts were uploaded.")

        if args.mode == "daily":
            last_pub = max([t for t in publish_schedule if t is not None], default=utc_now())

            long_publish_at = compute_long_publish_time(cfg, after=last_pub)
            min_after = last_pub + dt.timedelta(minutes=45)
            if long_publish_at < min_after:
                long_publish_at = min_after

            bg_long = get_background_image(td_path, exclude=used_backgrounds)

            long_mp4 = td_path / "long_compilation.mp4"
            render_long_compilation(
                cfg=cfg,
                short_paths=[s["video_path"] for s in generated_shorts],
                background_img=bg_long,
                out_mp4=long_mp4,
            )

            questions = [str(s["qa"]["question"]).strip() for s in generated_shorts]
            answers = [str(s["qa"]["answer"]).strip() for s in generated_shorts]
            combined_q = " | ".join([re.sub(r"\s+", " ", q) for q in questions])[:220]
            combined_a = ", ".join([re.sub(r"\s+", " ", a) for a in answers])[:220]

            meta_long = generate_metadata(cfg, "long", combined_q, combined_a, "Compilation")
            long_title = str(meta_long["title"]).strip()
            long_desc = str(meta_long["description"]).strip()
            long_tags = safe_tags(list(meta_long.get("tags") or []))

            long_thumb = td_path / "thumb_long.jpg"
            make_thumbnail(title=long_title, question="Daily Quiz Compilation", background_img=bg_long, out_jpg=long_thumb)

            api_rl.wait()
            long_vid = youtube_upload(
                service,
                video_path=long_mp4,
                title=long_title,
                description=long_desc,
                tags=long_tags,
                publish_at=long_publish_at,
                notify_subscribers=cfg.notify_subscribers_for_long,
            )
            logging.info("Uploaded long videoId=%s publish_at=%s", long_vid, long_publish_at)

            with contextlib.suppress(Exception):
                youtube_set_thumbnail(service, video_id=long_vid, thumbnail_path=long_thumb)

            now_iso = rfc3339(utc_now())
            uploads_items.append(
                {
                    "ts": now_iso,
                    "kind": "long",
                    "video_id": long_vid,
                    "title": long_title,
                    "publish_at": rfc3339(long_publish_at),
                }
            )

    history_obj["items"] = clean_history(history_items, keep_days=120)
    uploads_obj["items"] = uploads_items[-400:]

    atomic_write_json(HISTORY_PATH, history_obj)
    atomic_write_json(UPLOADS_PATH, uploads_obj)

    logging.info("Done. State saved.")


if __name__ == "__main__":
    main()

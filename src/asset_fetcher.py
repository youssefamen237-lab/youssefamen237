"""
asset_fetcher.py
Fetches backgrounds (images/videos), SFX, and background music from free APIs.
Pexels, Pixabay, Freesound, Unsplash.
Falls back to generated gradient if all APIs fail.
"""

import os
import random
import requests
import tempfile
import hashlib
import json
from PIL import Image, ImageFilter
import numpy as np

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
FREESOUND_API = os.environ.get("FREESOUND_API", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

BACKGROUND_DIR = "assets/backgrounds"
MUSIC_DIR = "assets/music"
SFX_DIR = "assets/sfx"

os.makedirs(BACKGROUND_DIR, exist_ok=True)
os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(SFX_DIR, exist_ok=True)

BG_VIDEO_QUERIES = [
    "satisfying sand art",
    "soap cutting satisfying",
    "colorful liquid mixing",
    "nature forest calm",
    "ocean waves relaxing",
    "minecraft parkour",
    "city timelapse night",
    "fireworks celebration",
    "stars milky way",
    "abstract geometric shapes",
    "waterfall nature",
    "aurora borealis",
]

SFX_QUERIES = {
    "tick": "clock tick ticking",
    "ding": "success ding correct answer bell",
    "whoosh": "whoosh swipe transition",
    "countdown": "countdown beep timer",
}


def _download_file(url: str, dest_path: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        if resp.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"[AssetFetcher] Download failed {url}: {e}")
    return False


def fetch_background_video(query: str = None) -> str:
    """
    Downloads a vertical background video from Pexels or Pixabay.
    Returns local file path.
    """
    if query is None:
        query = random.choice(BG_VIDEO_QUERIES)

    # Try Pexels
    if PEXELS_API_KEY:
        try:
            url = "https://api.pexels.com/videos/search"
            headers = {"Authorization": PEXELS_API_KEY}
            params = {"query": query, "orientation": "portrait", "per_page": 15, "size": "medium"}
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                videos = resp.json().get("videos", [])
                if videos:
                    video = random.choice(videos[:10])
                    # Find HD or SD file
                    files = video.get("video_files", [])
                    target = None
                    for f in files:
                        if f.get("width", 0) <= 720 and f.get("height", 0) >= 1080:
                            target = f
                            break
                    if not target:
                        target = files[0] if files else None
                    if target:
                        vid_url = target["link"]
                        fname = f"bg_pexels_{hashlib.md5(vid_url.encode()).hexdigest()[:8]}.mp4"
                        fpath = os.path.join(BACKGROUND_DIR, fname)
                        if os.path.exists(fpath):
                            return fpath
                        if _download_file(vid_url, fpath):
                            print(f"[AssetFetcher] Downloaded BG video from Pexels: {fname}")
                            return fpath
        except Exception as e:
            print(f"[AssetFetcher] Pexels video failed: {e}")

    # Try Pixabay
    if PIXABAY_API_KEY:
        try:
            url = "https://pixabay.com/api/videos/"
            params = {"key": PIXABAY_API_KEY, "q": query, "video_type": "all", "per_page": 15}
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                if hits:
                    video = random.choice(hits[:10])
                    vid_url = video.get("videos", {}).get("medium", {}).get("url") or \
                              video.get("videos", {}).get("small", {}).get("url")
                    if vid_url:
                        fname = f"bg_pixabay_{hashlib.md5(vid_url.encode()).hexdigest()[:8]}.mp4"
                        fpath = os.path.join(BACKGROUND_DIR, fname)
                        if os.path.exists(fpath):
                            return fpath
                        if _download_file(vid_url, fpath):
                            print(f"[AssetFetcher] Downloaded BG video from Pixabay: {fname}")
                            return fpath
        except Exception as e:
            print(f"[AssetFetcher] Pixabay video failed: {e}")

    # Fallback: return None (video_composer will use gradient)
    print("[AssetFetcher] Could not fetch background video, will use gradient fallback.")
    return None


def fetch_background_image(category: str = "abstract colorful") -> str:
    """
    Downloads a background image from Unsplash or Pexels.
    Returns local file path.
    """
    # Try Unsplash
    if UNSPLASH_ACCESS_KEY:
        try:
            url = "https://api.unsplash.com/photos/random"
            params = {"query": category, "orientation": "portrait", "client_id": UNSPLASH_ACCESS_KEY}
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                img_url = data["urls"].get("regular") or data["urls"].get("full")
                if img_url:
                    fname = f"bg_unsplash_{hashlib.md5(img_url.encode()).hexdigest()[:8]}.jpg"
                    fpath = os.path.join(BACKGROUND_DIR, fname)
                    if os.path.exists(fpath):
                        return fpath
                    if _download_file(img_url, fpath):
                        return fpath
        except Exception as e:
            print(f"[AssetFetcher] Unsplash failed: {e}")

    # Try Pexels Photos
    if PEXELS_API_KEY:
        try:
            url = "https://api.pexels.com/v1/search"
            headers = {"Authorization": PEXELS_API_KEY}
            params = {"query": category, "orientation": "portrait", "per_page": 15}
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                photos = resp.json().get("photos", [])
                if photos:
                    photo = random.choice(photos)
                    img_url = photo["src"].get("large") or photo["src"].get("medium")
                    if img_url:
                        fname = f"bg_pexels_{hashlib.md5(img_url.encode()).hexdigest()[:8]}.jpg"
                        fpath = os.path.join(BACKGROUND_DIR, fname)
                        if os.path.exists(fpath):
                            return fpath
                        if _download_file(img_url, fpath):
                            return fpath
        except Exception as e:
            print(f"[AssetFetcher] Pexels photo failed: {e}")

    # Fallback: generate gradient image
    return _generate_gradient_image()


def _generate_gradient_image() -> str:
    """Generate a beautiful gradient image as background fallback."""
    colors = [
        [(20, 20, 40), (100, 20, 120)],
        [(0, 30, 60), (0, 120, 180)],
        [(40, 0, 60), (180, 40, 80)],
        [(10, 40, 10), (20, 160, 80)],
        [(60, 20, 0), (200, 100, 20)],
    ]
    color_pair = random.choice(colors)
    c1, c2 = color_pair

    width, height = 1080, 1920
    img_array = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        ratio = y / height
        for c in range(3):
            img_array[y, :, c] = int(c1[c] * (1 - ratio) + c2[c] * ratio)

    img = Image.fromarray(img_array)
    fpath = os.path.join(BACKGROUND_DIR, f"gradient_{random.randint(1000,9999)}.jpg")
    img.save(fpath, quality=85)
    return fpath


def fetch_sfx(sfx_type: str) -> str:
    """
    Fetches a sound effect file. Returns local path.
    sfx_type: 'tick', 'ding', 'whoosh', 'countdown'
    """
    cached_path = os.path.join(SFX_DIR, f"{sfx_type}.mp3")
    if os.path.exists(cached_path):
        return cached_path

    query = SFX_QUERIES.get(sfx_type, sfx_type)

    if FREESOUND_API:
        try:
            # Search for sounds
            url = "https://freesound.org/apiv2/search/text/"
            params = {
                "query": query,
                "fields": "id,name,previews,duration",
                "filter": "duration:[0.1 TO 3.0]",
                "token": FREESOUND_API,
                "page_size": 10,
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    sound = random.choice(results[:5])
                    preview_url = sound.get("previews", {}).get("preview-hq-mp3") or \
                                  sound.get("previews", {}).get("preview-lq-mp3")
                    if preview_url:
                        if _download_file(preview_url, cached_path):
                            print(f"[AssetFetcher] Downloaded SFX '{sfx_type}' from Freesound")
                            return cached_path
        except Exception as e:
            print(f"[AssetFetcher] Freesound SFX failed for '{sfx_type}': {e}")

    # Fallback: generate synthetic SFX with numpy
    return _generate_synthetic_sfx(sfx_type, cached_path)


def _generate_synthetic_sfx(sfx_type: str, output_path: str) -> str:
    """Generate synthetic sound effects using numpy + scipy."""
    import struct
    import wave
    import math

    sample_rate = 44100

    if sfx_type == "ding":
        duration = 0.8
        freq = 880
        t = np.linspace(0, duration, int(sample_rate * duration))
        wave_data = (np.sin(2 * np.pi * freq * t) * np.exp(-3 * t) * 32767).astype(np.int16)
    elif sfx_type == "tick":
        duration = 0.1
        t = np.linspace(0, duration, int(sample_rate * duration))
        wave_data = (np.sin(2 * np.pi * 1200 * t) * np.exp(-20 * t) * 32767).astype(np.int16)
    elif sfx_type == "whoosh":
        duration = 0.4
        t = np.linspace(0, duration, int(sample_rate * duration))
        noise = np.random.randn(len(t)) * np.exp(-3 * t)
        wave_data = (noise * 16000).astype(np.int16)
    else:
        duration = 0.3
        t = np.linspace(0, duration, int(sample_rate * duration))
        wave_data = (np.sin(2 * np.pi * 660 * t) * 20000).astype(np.int16)

    wav_path = output_path.replace(".mp3", ".wav")
    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(wave_data.tobytes())

    # Convert to mp3 if ffmpeg available
    import subprocess
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, output_path],
        capture_output=True
    )
    if result.returncode == 0 and os.path.exists(wav_path):
        os.remove(wav_path)
    else:
        import shutil
        shutil.copy(wav_path, output_path)

    return output_path


def fetch_background_music(duration_seconds: float = 60.0) -> str:
    """
    Fetches a random segment of royalty-free background music.
    Returns local path to trimmed audio clip.
    """
    cache_dir = MUSIC_DIR
    query = random.choice(["lofi quiz background music", "game show music upbeat", "trivia background instrumental"])

    if PIXABAY_API_KEY:
        try:
            url = "https://pixabay.com/api/"
            params = {
                "key": PIXABAY_API_KEY,
                "q": "quiz background music",
                "media_type": "music",
                "per_page": 10,
            }
            # Pixabay music API
            music_url = "https://pixabay.com/api/music/"
            params2 = {"key": PIXABAY_API_KEY, "per_page": 10}
            resp = requests.get(music_url, params=params2, timeout=15)
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                if hits:
                    track = random.choice(hits)
                    audio_url = track.get("audio")
                    if audio_url:
                        fname = f"music_{hashlib.md5(audio_url.encode()).hexdigest()[:8]}.mp3"
                        fpath = os.path.join(cache_dir, fname)
                        if os.path.exists(fpath):
                            return _trim_audio(fpath, duration_seconds)
                        if _download_file(audio_url, fpath):
                            return _trim_audio(fpath, duration_seconds)
        except Exception as e:
            print(f"[AssetFetcher] Pixabay music failed: {e}")

    # Fallback: generate synthetic music-like tone
    return _generate_synthetic_bgm(duration_seconds)


def _trim_audio(audio_path: str, duration: float) -> str:
    """Trims audio to duration starting from random offset."""
    import subprocess
    offset = random.uniform(5, 30)
    out_path = audio_path.replace(".mp3", f"_trim_{int(duration)}s.mp3")
    if os.path.exists(out_path):
        return out_path
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(offset),
        "-t", str(duration),
        "-i", audio_path,
        "-af", "afade=in:st=0:d=1,afade=out:st=" + str(max(0, duration - 1)) + ":d=1",
        out_path
    ]
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(out_path):
        return out_path
    return audio_path


def _generate_synthetic_bgm(duration_seconds: float) -> str:
    """Generates synthetic lo-fi background music."""
    import wave
    sample_rate = 44100
    num_samples = int(sample_rate * duration_seconds)
    t = np.linspace(0, duration_seconds, num_samples)

    # Simple lo-fi chord progression
    chord_freqs = [261.63, 329.63, 392.00, 329.63]  # C-E-G-E loop
    beat_duration = 2.0
    wave_data = np.zeros(num_samples)

    for i, freq in enumerate(chord_freqs * (int(duration_seconds / beat_duration) + 1)):
        start = int(i * beat_duration * sample_rate)
        end = int((i + 1) * beat_duration * sample_rate)
        if start >= num_samples:
            break
        end = min(end, num_samples)
        t_seg = np.linspace(0, beat_duration, end - start)
        envelope = np.exp(-0.5 * t_seg)
        wave_data[start:end] += np.sin(2 * np.pi * freq * t_seg) * envelope * 0.3
        wave_data[start:end] += np.sin(2 * np.pi * freq * 2 * t_seg) * envelope * 0.15

    wave_data = (wave_data / np.max(np.abs(wave_data) + 1e-9) * 10000).astype(np.int16)

    fpath = os.path.join(MUSIC_DIR, f"synth_bgm_{random.randint(1000,9999)}.wav")
    with wave.open(fpath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(wave_data.tobytes())
    return fpath

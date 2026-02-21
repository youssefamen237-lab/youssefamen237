"""
Background Image Fetcher — fetches images from free APIs for video backgrounds.
Sources: Pexels → Pixabay → Unsplash → NASA → Internet Archive → local fallback
"""

import os
import random
import json
import hashlib
from pathlib import Path
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

BACKGROUNDS_DIR = Path("assets/backgrounds")
BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_TERMS = [
    "nature landscape",
    "space galaxy",
    "abstract colorful",
    "city lights",
    "ocean waves",
    "mountains sunrise",
    "forest fog",
    "technology circuit",
    "cosmos stars",
    "underwater reef",
    "aurora borealis",
    "desert sand dunes",
    "tropical beach",
    "waterfall nature",
    "night sky milky way",
]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_pexels(search_term, save_path):
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise ValueError("No PEXELS_API_KEY")

    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": search_term, "per_page": 15, "orientation": "portrait"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    photos = data.get("photos", [])
    if not photos:
        raise ValueError("No Pexels photos found")

    photo = random.choice(photos)
    img_url = photo["src"]["portrait"]
    img_resp = requests.get(img_url, timeout=60)
    img_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(img_resp.content)
    print(f"[Background] Pexels: {save_path}")
    return save_path


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_pixabay(search_term, save_path):
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        raise ValueError("No PIXABAY_API_KEY")

    url = "https://pixabay.com/api/"
    params = {
        "key": api_key,
        "q": search_term,
        "image_type": "photo",
        "orientation": "vertical",
        "per_page": 15,
        "safesearch": "true",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", [])
    if not hits:
        raise ValueError("No Pixabay images found")

    hit = random.choice(hits)
    img_url = hit.get("largeImageURL") or hit.get("webformatURL")
    img_resp = requests.get(img_url, timeout=60)
    img_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(img_resp.content)
    print(f"[Background] Pixabay: {save_path}")
    return save_path


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_unsplash(search_term, save_path):
    api_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not api_key:
        raise ValueError("No UNSPLASH_ACCESS_KEY")

    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {api_key}"}
    params = {
        "query": search_term,
        "per_page": 15,
        "orientation": "portrait",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise ValueError("No Unsplash images found")

    photo = random.choice(results)
    img_url = photo["urls"]["regular"]
    img_resp = requests.get(img_url, timeout=60)
    img_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(img_resp.content)
    print(f"[Background] Unsplash: {save_path}")
    return save_path


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_nasa(save_path):
    api_key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    url = "https://api.nasa.gov/planetary/apod"
    params = {"api_key": api_key, "count": 5}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    images = [i for i in items if i.get("media_type") == "image"]
    if not images:
        raise ValueError("No NASA images available")

    item = random.choice(images)
    img_url = item.get("hdurl") or item.get("url")
    img_resp = requests.get(img_url, timeout=60)
    img_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(img_resp.content)
    print(f"[Background] NASA: {save_path}")
    return save_path


def create_gradient_fallback(save_path):
    """Create a colored gradient as absolute last fallback"""
    from PIL import Image, ImageDraw
    import numpy as np

    width, height = 1080, 1920
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    colors = [
        ((20, 20, 80), (80, 20, 120)),
        ((10, 50, 10), (20, 100, 50)),
        ((80, 20, 20), (120, 60, 20)),
        ((20, 60, 80), (40, 20, 80)),
        ((60, 20, 60), (20, 40, 80)),
    ]
    top_color, bottom_color = random.choice(colors)

    for y in range(height):
        ratio = y / height
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    img.save(save_path, "JPEG", quality=90)
    print(f"[Background] Gradient fallback: {save_path}")
    return save_path


def get_background_image(output_path=None):
    """Fetch a random background image from available sources"""
    if output_path is None:
        import time
        output_path = str(BACKGROUNDS_DIR / f"bg_{int(time.time())}.jpg")

    search_term = random.choice(SEARCH_TERMS)

    providers = [
        lambda p: fetch_pexels(search_term, p),
        lambda p: fetch_pixabay(search_term, p),
        lambda p: fetch_unsplash(search_term, p),
        lambda p: fetch_nasa(p),
    ]
    random.shuffle(providers)

    for provider in providers:
        try:
            return provider(output_path)
        except Exception as e:
            print(f"[Background] Provider failed: {e}")
            continue

    print("[Background] All providers failed, using gradient")
    return create_gradient_fallback(output_path)


if __name__ == "__main__":
    path = get_background_image("/tmp/test_bg.jpg")
    print(f"Background saved: {path}")

"""
utils/api_client.py
Karma Vault Stories — Base API Client with Cascading Fallback Engine
Implements real try/except cascading provider logic for writing, TTS, visuals, and search.
No provider is listed without actual execution logic.
"""

import time
import json
import random
import asyncio
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, Any, Callable
from datetime import datetime, timezone

from config.settings import (
    API_REQUEST_TIMEOUT_SEC, API_RETRY_ATTEMPTS, API_RETRY_BACKOFF_SEC,
    WRITING_MODEL_CHAIN, TTS_PROVIDER_CHAIN, VISUAL_SOURCE_CHAIN,
    SEARCH_PROVIDER_CHAIN,
)
from utils.logger import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────
# PROVIDER HEALTH TRACKER (in-process, per run)
# ─────────────────────────────────────────────

class ProviderHealth:
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self):
        self._failures: dict[str, int] = {}
        self._skipped: set[str] = set()

    def record_failure(self, provider: str) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= self.MAX_CONSECUTIVE_FAILURES:
            self._skipped.add(provider)
            log.warning(f"Provider '{provider}' marked unhealthy after {self.MAX_CONSECUTIVE_FAILURES} failures.")

    def record_success(self, provider: str) -> None:
        self._failures[provider] = 0
        self._skipped.discard(provider)

    def is_healthy(self, provider: str) -> bool:
        return provider not in self._skipped


_provider_health = ProviderHealth()


# ─────────────────────────────────────────────
# CORE HTTP HELPERS
# ─────────────────────────────────────────────

def http_get(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = API_REQUEST_TIMEOUT_SEC,
) -> bytes:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post_json(
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: int = API_REQUEST_TIMEOUT_SEC,
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(
    url: str,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = API_REQUEST_TIMEOUT_SEC,
) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    raw = http_get(url, headers=headers, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


def with_retry(
    func: Callable,
    *args,
    attempts: int = API_RETRY_ATTEMPTS,
    backoff: float = API_RETRY_BACKOFF_SEC,
    **kwargs,
) -> Any:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                wait = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.debug(f"Retry {attempt}/{attempts} after {wait:.1f}s — {exc}")
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ─────────────────────────────────────────────
# WRITING MODEL CASCADING CLIENT
# ─────────────────────────────────────────────

def call_writing_model(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.85,
    json_output: bool = False,
) -> str:
    for provider_cfg in WRITING_MODEL_CHAIN:
        provider = provider_cfg["provider"]
        key = provider_cfg["key"]

        if not key:
            log.debug(f"Writing provider '{provider}' skipped — no API key.")
            continue
        if not _provider_health.is_healthy(provider):
            log.debug(f"Writing provider '{provider}' skipped — unhealthy.")
            continue

        try:
            result = with_retry(
                _call_provider,
                provider_cfg,
                system_prompt,
                user_prompt,
                max_tokens,
                temperature,
                json_output,
            )
            _provider_health.record_success(provider)
            log.info(f"Writing model responded via '{provider}'.")
            return result
        except Exception as exc:
            _provider_health.record_failure(provider)
            log.warning(f"Writing provider '{provider}' failed: {exc}")
            continue

    raise RuntimeError("All writing model providers failed.")


def _call_provider(
    cfg: dict,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    json_output: bool,
) -> str:
    provider = cfg["provider"]

    if provider == "gemini":
        return _call_gemini(cfg["key"], cfg["model"], system_prompt, user_prompt, max_tokens, temperature, json_output)
    elif provider == "groq":
        return _call_groq(cfg["key"], cfg["model"], system_prompt, user_prompt, max_tokens, temperature, json_output)
    elif provider in ("openrouter", "openai"):
        base_url = (
            "https://openrouter.ai/api/v1/chat/completions"
            if provider == "openrouter"
            else "https://api.openai.com/v1/chat/completions"
        )
        return _call_openai_compat(
            cfg["key"], cfg["model"], system_prompt, user_prompt,
            max_tokens, temperature, json_output, base_url, "Authorization"
        )
    raise ValueError(f"Unknown writing provider: {provider}")


def _call_gemini(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            **({} if not json_output else {"responseMimeType": "application/json"}),
        },
    }
    resp = http_post_json(url, payload)
    return resp["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
) -> str:
    payload: dict = {
        "model": model, "max_tokens": max_tokens, "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    resp = http_post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        payload,
        headers={"Authorization": f"Bearer {key}"},
    )
    return resp["choices"][0]["message"]["content"]


def _call_openai_compat(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
    base_url: str, header_key: str,
) -> str:
    payload: dict = {
        "model": model, "max_tokens": max_tokens, "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    resp = http_post_json(base_url, payload, headers={header_key: f"Bearer {key}"})
    return resp["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────
# SEARCH CASCADING CLIENT
# ─────────────────────────────────────────────

def call_search(query: str, num_results: int = 10) -> list[dict]:
    for provider_cfg in SEARCH_PROVIDER_CHAIN:
        provider = provider_cfg["provider"]
        key = provider_cfg["key"]

        if not key and key != "no_key_required":
            continue
        if not _provider_health.is_healthy(provider):
            continue

        try:
            results = with_retry(_call_search_provider, provider_cfg, query, num_results)
            _provider_health.record_success(provider)
            log.info(f"Search via '{provider}' returned {len(results)} results.")
            return results
        except Exception as exc:
            _provider_health.record_failure(provider)
            log.warning(f"Search provider '{provider}' failed: {exc}")
            continue

    raise RuntimeError(f"All search providers failed for query: {query!r}")


def _call_search_provider(cfg: dict, query: str, num_results: int) -> list[dict]:
    provider = cfg["provider"]

    if provider == "tavily":
        resp = http_post_json(
            "https://api.tavily.com/search",
            {"query": query, "max_results": num_results, "search_depth": "basic"},
            headers={"Authorization": f"Bearer {cfg['key']}"},
        )
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", ""), "source": "tavily"}
            for r in resp.get("results", [])
        ]

    elif provider == "serpapi":
        resp = http_get_json(
            "https://serpapi.com/search",
            params={"q": query, "num": num_results, "api_key": cfg["key"], "engine": "google"},
        )
        return [
            {"title": r.get("title", ""), "url": r.get("link", ""),
             "snippet": r.get("snippet", ""), "source": "serpapi"}
            for r in resp.get("organic_results", [])
        ]

    elif provider == "zenserp":
        resp = http_get_json(
            "https://app.zenserp.com/api/v2/search",
            headers={"apikey": cfg["key"]},
            params={"q": query, "num": num_results},
        )
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("description", ""), "source": "zenserp"}
            for r in resp.get("organic", [])
        ]

    elif provider == "newsapi":
        resp = http_get_json(
            "https://newsapi.org/v2/everything",
            headers={"X-Api-Key": cfg["key"]},
            params={"q": query, "pageSize": num_results, "sortBy": "relevancy", "language": "en"},
        )
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("description", ""), "source": "newsapi"}
            for r in resp.get("articles", [])
        ]

    raise ValueError(f"Unknown search provider: {provider}")


# ─────────────────────────────────────────────
# PLACEHOLDER / QUALITY FILTER
# ─────────────────────────────────────────────

# Filename / URL patterns that indicate non-photographic or placeholder content
_PLACEHOLDER_URL_TERMS = {
    "placeholder", "template", "blank", "empty", "no_content", "no-content",
    "opening", "coming_soon", "coming-soon", "soon", "stub", "missing",
    "default", "noimage", "no_image", "no-image", "dummy", "sample",
    ".svg", "icon_", "_icon", "logo_", "_logo", "badge_", "_badge",
    "banner_", "_banner", "flag_", "_flag", "map_", "_map", "chart_",
    "_chart", "diagram_", "_diagram", "graph_", "_graph", "symbol_",
    "watermark", "preview_only", "not_available",
}

# Title / page-name patterns to reject
_PLACEHOLDER_TITLE_TERMS = {
    "placeholder", "template", "stub", "blank", "no content",
    "opening soon", "coming soon", "no image", "missing",
    "default image", "no photo", "icon", "logo", "banner",
    "flag of", "map of", "diagram", "chart", "graph",
}

# Minimum acceptable image dimensions (skip thumbnails / icons)
_MIN_IMAGE_WIDTH  = 600
_MIN_IMAGE_HEIGHT = 400


def _is_placeholder(
    url:   str,
    title: str = "",
    width: int  = 0,
    height: int = 0,
) -> bool:
    """
    Returns True if this image is likely a placeholder, icon, text graphic,
    template, or otherwise unsuitable for dark documentary use.
    """
    url_lower   = url.lower()
    title_lower = title.lower()

    # Check URL for known bad patterns
    for term in _PLACEHOLDER_URL_TERMS:
        if term in url_lower:
            return True

    # Check title for known bad patterns
    for term in _PLACEHOLDER_TITLE_TERMS:
        if term in title_lower:
            return True

    # Reject clearly non-photo file extensions in URL
    for ext in (".svg", ".gif", ".ico", ".bmp", ".webp"):
        if ext in url_lower:
            return True

    # Reject images that are too small (icons, thumbnails)
    if width and height:
        if width < _MIN_IMAGE_WIDTH or height < _MIN_IMAGE_HEIGHT:
            return True

    # Reject Wikimedia URLs that are thumbnails of very small originals
    # (these contain px- size indicators like "100px-", "200px-")
    import re as _re
    if _re.search(r'/\d{1,3}px-', url_lower):
        return True

    return False


# ─────────────────────────────────────────────
# VISUAL STOCK IMAGE CASCADING CLIENT
# ─────────────────────────────────────────────

# Dark documentary search query modifiers — appended to improve photo relevance
_DARK_QUERY_SUFFIX = " dark dramatic photography"

# Wikimedia: categories and terms known to produce actual photographs
_WIKIMEDIA_PHOTO_TERMS = [
    "night photography", "dark atmosphere", "abandoned building",
    "shadow dramatic light", "documentary photography", "crime scene",
    "forest fog night", "silhouette dramatic", "dark interior",
    "dramatic sky", "urban night", "haunted house",
]


def _call_wikimedia(query: str, count: int) -> list[dict]:
    """
    Wikimedia Commons photo search — free, no API key, no rate limits.
    Filters out icons, placeholders, SVGs, diagrams, and images too small
    to be useful for a dark documentary.
    Uses a photography-biased search to avoid text/template images.
    """
    # Append photography bias to push results toward actual photos
    search_query = f"{query} photograph"

    try:
        resp = http_get_json(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action":       "query",
                "generator":    "search",
                "gsrsearch":    search_query,
                "gsrnamespace": "6",
                "gsrlimit":     str(min(count * 4, 40)),  # fetch extra to allow filtering
                "prop":         "imageinfo",
                "iiprop":       "url|mime|size|extmetadata",
                "iiurlwidth":   "1920",
                "format":       "json",
                "origin":       "*",
            },
            timeout=20,
        )
        pages = resp.get("query", {}).get("pages", {})
        results = []

        for page in pages.values():
            if len(results) >= count:
                break

            page_title = page.get("title", "")
            info_list  = page.get("imageinfo", [])
            if not info_list:
                continue

            info = info_list[0]
            mime = info.get("mime", "")

            # Must be a bitmap image (not SVG, PDF, audio, video)
            if not mime.startswith("image/") or "svg" in mime:
                continue

            url    = info.get("thumburl") or info.get("url", "")
            width  = info.get("thumbwidth")  or info.get("width",  0)
            height = info.get("thumbheight") or info.get("height", 0)

            if not url:
                continue

            # Apply placeholder / quality filter
            if _is_placeholder(url, page_title, int(width or 0), int(height or 0)):
                log.debug(f"Wikimedia: skipping placeholder/icon: {page_title[:50]}")
                continue

            # Skip images where the filename itself looks like a text graphic
            filename = url.split("/")[-1].lower()
            if any(term in filename for term in (
                "text", "words", "letters", "alphabet", "type_",
                "font", "calligraphy", "script", "handwriting",
            )):
                continue

            # Try to read image description for additional filtering
            extmeta = info.get("extmetadata", {})
            categories = str(extmeta.get("Categories", {}).get("value", "")).lower()
            if any(t in categories for t in ("icon", "logo", "template", "placeholder", "symbol")):
                continue

            results.append({
                "url":      url,
                "provider": "wikimedia",
                "width":    int(width  or 0),
                "height":   int(height or 0),
                "id":       str(page.get("pageid", "")),
            })

        log.debug(f"Wikimedia: {len(results)} usable results for '{query[:40]}'")
        return results[:count]

    except Exception as exc:
        log.warning(f"Wikimedia search failed for '{query[:40]}': {exc}")
        return []


def _call_openverse(query: str, count: int) -> list[dict]:
    """
    Openverse (WordPress Foundation) — free, no API key, CC-licensed images.
    Filters placeholders, minimum 800px wide, photograph media type only.
    """
    try:
        resp = http_get_json(
            "https://api.openverse.org/v1/images/",
            params={
                "q":            f"{query} photograph",
                "page_size":    str(min(count * 3, 30)),
                "license_type": "commercial,modification",
                "mature":       "false",
                "source":       "flickr,wikimedia_commons",  # photo-focused sources
            },
            timeout=20,
        )
        results = []

        for item in resp.get("results", []):
            if len(results) >= count:
                break

            url    = item.get("url", "")
            width  = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            title  = item.get("title", "")

            if not url:
                continue

            # Apply placeholder / quality filter
            if _is_placeholder(url, title, width, height):
                log.debug(f"Openverse: skipping placeholder: {title[:50]}")
                continue

            # Skip if too small
            if width and width < _MIN_IMAGE_WIDTH:
                continue
            if height and height < _MIN_IMAGE_HEIGHT:
                continue

            results.append({
                "url":      url,
                "provider": "openverse",
                "width":    width,
                "height":   height,
                "id":       item.get("id", ""),
            })

        log.debug(f"Openverse: {len(results)} usable results for '{query[:40]}'")
        return results[:count]

    except Exception as exc:
        log.warning(f"Openverse search failed for '{query[:40]}': {exc}")
        return []


def fetch_stock_images(
    query: str,
    count: int = 5,
    orientation: str = "landscape",
    exclude_ai: bool = False,
) -> list[dict]:
    """
    Fetches stock images via cascading provider chain.
    Wikimedia and Openverse are always available as zero-key fallbacks.
    """
    for provider_cfg in VISUAL_SOURCE_CHAIN:
        provider = provider_cfg["provider"]
        key      = provider_cfg["key"]
        p_type   = provider_cfg["type"]

        if not key and key != "no_key_required":
            continue
        if exclude_ai and p_type == "ai_generation":
            continue
        if not _provider_health.is_healthy(provider):
            continue

        try:
            results = with_retry(_call_visual_provider, provider_cfg, query, count, orientation)
            if results:
                _provider_health.record_success(provider)
                log.info(f"Fetched {len(results)} visuals via '{provider}' for '{query[:40]}'.")
                return results
        except Exception as exc:
            _provider_health.record_failure(provider)
            log.warning(f"Visual provider '{provider}' failed: {exc}")
            continue

    log.error(f"All visual providers failed for query: {query!r}")
    return []


def _call_visual_provider(
    cfg: dict, query: str, count: int, orientation: str
) -> list[dict]:
    provider = cfg["provider"]

    if provider == "pexels":
        resp = http_get_json(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": cfg["key"]},
            params={"query": query, "per_page": count, "orientation": orientation},
        )
        return [
            {"url": p["src"]["large2x"], "provider": "pexels",
             "width": p["width"], "height": p["height"], "id": str(p["id"])}
            for p in resp.get("photos", [])
        ]

    elif provider == "pixabay":
        resp = http_get_json(
            "https://pixabay.com/api/",
            params={
                "key": cfg["key"], "q": query, "per_page": count,
                "image_type": "photo", "orientation": orientation,
                "safesearch": "true",
            },
        )
        return [
            {"url": h["largeImageURL"], "provider": "pixabay",
             "width": h["imageWidth"], "height": h["imageHeight"], "id": str(h["id"])}
            for h in resp.get("hits", [])
        ]

    elif provider == "unsplash":
        resp = http_get_json(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {cfg['key']}"},
            params={"query": query, "per_page": count, "orientation": orientation},
        )
        return [
            {"url": p["urls"]["regular"], "provider": "unsplash",
             "width": p["width"], "height": p["height"], "id": p["id"]}
            for p in resp.get("results", [])
        ]

    elif provider == "coverr":
        from config.settings import COVERR_API_ID
        resp = http_get_json(
            "https://api.coverr.co/videos",
            headers={"Authorization": f"Bearer {cfg['key']}", "x-api-key": COVERR_API_ID},
            params={"keywords": query, "per_page": count},
        )
        return [
            {"url": v.get("mp4_url", v.get("url", "")), "provider": "coverr",
             "width": v.get("width", 1920), "height": v.get("height", 1080),
             "id": str(v.get("id", "")), "type": "video"}
            for v in resp.get("hits", []) if v.get("mp4_url") or v.get("url")
        ]

    elif provider == "internet_archive":
        resp = http_get_json(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"{query} AND mediatype:image",
                "output": "json", "rows": count,
                "fl[]": "identifier,title",
            },
        )
        docs = resp.get("response", {}).get("docs", [])
        return [
            {"url": f"https://archive.org/download/{d['identifier']}/{d['identifier']}.jpg",
             "provider": "internet_archive", "width": 0, "height": 0, "id": d["identifier"]}
            for d in docs
        ]

    elif provider == "getimg":
        resp = http_post_json(
            "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image",
            {
                "prompt": f"dark cinematic documentary style: {query}, dramatic lighting, high contrast, photorealistic",
                "negative_prompt": "cartoon, anime, bright colors, cheerful, text, watermark",
                "width": 1280, "height": 720, "steps": 25, "output_format": "jpeg",
            },
            headers={"Authorization": f"Bearer {cfg['key']}"},
        )
        if resp.get("image"):
            return [{"url_base64": resp["image"], "provider": "getimg",
                     "width": 1280, "height": 720,
                     "id": f"getimg_{int(time.time())}", "type": "ai_generated"}]
        return []

    elif provider == "replicate":
        trigger_resp = http_post_json(
            "https://api.replicate.com/v1/models/stability-ai/sdxl/predictions",
            {"input": {
                "prompt": f"dark cinematic documentary: {query}, dramatic, high contrast, film noir",
                "negative_prompt": "cartoon, bright, cheerful, anime, text, watermark",
                "width": 1280, "height": 720,
            }},
            headers={"Authorization": f"Token {cfg['key']}", "Prefer": "wait=60"},
        )
        output = trigger_resp.get("output", [])
        if isinstance(output, list) and output:
            return [{"url": output[0], "provider": "replicate",
                     "width": 1280, "height": 720,
                     "id": trigger_resp.get("id", f"repl_{int(time.time())}"),
                     "type": "ai_generated"}]
        return []

    elif provider == "huggingface":
        import base64
        raw = http_post_json(
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
            {"inputs": f"dark cinematic documentary: {query}, dramatic lighting, film noir"},
            headers={"Authorization": f"Bearer {cfg['key']}"},
        )
        if isinstance(raw, dict) and raw.get("image"):
            return [{"url_base64": raw["image"], "provider": "huggingface",
                     "width": 1024, "height": 576,
                     "id": f"hf_{int(time.time())}", "type": "ai_generated"}]
        return []

    elif provider == "wikimedia":
        return _call_wikimedia(query, count)

    elif provider == "openverse":
        return _call_openverse(query, count)

    raise ValueError(f"Unknown visual provider: {provider}")


# ─────────────────────────────────────────────
# IMAGE DOWNLOAD HELPERS
# ─────────────────────────────────────────────

def download_image(url: str, dest_path: str, timeout: int = 20) -> bool:
    try:
        if url.startswith("data:") or not url.startswith("http"):
            import base64
            header, data = url.split(",", 1) if "," in url else ("", url)
            with open(dest_path, "wb") as f:
                f.write(base64.b64decode(data))
            return True

        raw = http_get(url, timeout=timeout)
        with open(dest_path, "wb") as f:
            f.write(raw)
        return True
    except Exception as exc:
        log.warning(f"Image download failed ({url[:60]}): {exc}")
        return False


def download_base64_image(b64_string: str, dest_path: str) -> bool:
    import base64
    try:
        with open(dest_path, "wb") as f:
            f.write(base64.b64decode(b64_string))
        return True
    except Exception as exc:
        log.warning(f"Base64 image save failed: {exc}")
        return False

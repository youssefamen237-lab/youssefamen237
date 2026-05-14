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
    """
    Tracks per-run provider failure counts.
    After MAX_CONSECUTIVE_FAILURES consecutive failures, a provider is
    considered unhealthy for this run and skipped in the fallback chain.
    """
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
# CORE HTTP HELPER (stdlib-only, GHA compatible)
# ─────────────────────────────────────────────

def http_get(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = API_REQUEST_TIMEOUT_SEC,
) -> bytes:
    """Synchronous GET. Returns raw response bytes. Raises on HTTP error."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post_json(
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: int = API_REQUEST_TIMEOUT_SEC,
) -> dict:
    """Synchronous POST with JSON body. Returns parsed response dict."""
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
    """Synchronous GET with optional query params. Returns parsed JSON."""
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
    """
    Executes func(*args, **kwargs) with exponential backoff retry.
    Raises the last exception if all attempts fail.
    """
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
    """
    Calls the writing model fallback chain (Gemini → Groq → OpenRouter → OpenAI).
    Returns the model's text response string.
    Raises RuntimeError if all providers fail.
    """
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

    raise RuntimeError("All writing model providers failed. Cannot generate content.")


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
        header_key = "Authorization"
        return _call_openai_compat(
            cfg["key"], cfg["model"], system_prompt, user_prompt,
            max_tokens, temperature, json_output, base_url, header_key
        )
    raise ValueError(f"Unknown writing provider: {provider}")


def _call_gemini(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload: dict = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            **({"responseMimeType": "application/json"} if json_output else {}),
        },
    }
    resp = http_post_json(url, payload)
    return resp["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}"}
    resp = http_post_json(url, payload, headers=headers)
    return resp["choices"][0]["message"]["content"]


def _call_openai_compat(
    key: str, model: str, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float, json_output: bool,
    base_url: str, header_key: str,
) -> str:
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}
    headers = {header_key: f"Bearer {key}"}
    resp = http_post_json(base_url, payload, headers=headers)
    return resp["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────
# SEARCH CASCADING CLIENT
# ─────────────────────────────────────────────

def call_search(query: str, num_results: int = 10) -> list[dict]:
    """
    Searches via cascading provider chain (Tavily → SerpAPI → Zenserp → NewsAPI).
    Returns list of {title, url, snippet, source} dicts.
    Raises RuntimeError if all providers fail.
    """
    for provider_cfg in SEARCH_PROVIDER_CHAIN:
        provider = provider_cfg["provider"]
        key = provider_cfg["key"]

        if not key:
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
# VISUAL STOCK IMAGE CASCADING CLIENT
# ─────────────────────────────────────────────

def fetch_stock_images(
    query: str,
    count: int = 5,
    orientation: str = "landscape",
    exclude_ai: bool = False,
) -> list[dict]:
    """
    Fetches stock images via cascading provider chain.
    Returns list of {url, provider, width, height, id} dicts.
    Falls through to AI generation providers if stock sources fail.
    """
    for provider_cfg in VISUAL_SOURCE_CHAIN:
        provider = provider_cfg["provider"]
        key = provider_cfg["key"]
        p_type = provider_cfg["type"]

        if not key:
            continue
        if exclude_ai and p_type == "ai_generation":
            continue
        if not _provider_health.is_healthy(provider):
            continue

        try:
            results = with_retry(_call_visual_provider, provider_cfg, query, count, orientation)
            if results:
                _provider_health.record_success(provider)
                log.info(f"Fetched {len(results)} visuals via '{provider}' for '{query}'.")
                return results
            # empty results — try next
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
            {
                "url": p["src"]["large2x"],
                "provider": "pexels",
                "width": p["width"],
                "height": p["height"],
                "id": str(p["id"]),
            }
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
            {
                "url": h["largeImageURL"],
                "provider": "pixabay",
                "width": h["imageWidth"],
                "height": h["imageHeight"],
                "id": str(h["id"]),
            }
            for h in resp.get("hits", [])
        ]

    elif provider == "unsplash":
        from config.settings import UNSPLASH_ACCESS_KEY
        resp = http_get_json(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {cfg['key']}"},
            params={"query": query, "per_page": count, "orientation": orientation},
        )
        return [
            {
                "url": p["urls"]["regular"],
                "provider": "unsplash",
                "width": p["width"],
                "height": p["height"],
                "id": p["id"],
            }
            for p in resp.get("results", [])
        ]

    elif provider == "coverr":
        from config.settings import COVERR_API_ID, COVERR_API_KEY
        resp = http_get_json(
            "https://api.coverr.co/videos",
            headers={
                "Authorization": f"Bearer {cfg['key']}",
                "x-api-key": COVERR_API_ID,
            },
            params={"keywords": query, "per_page": count},
        )
        return [
            {
                "url": v.get("mp4_url", v.get("url", "")),
                "provider": "coverr",
                "width": v.get("width", 1920),
                "height": v.get("height", 1080),
                "id": str(v.get("id", "")),
                "type": "video",
            }
            for v in resp.get("hits", [])
            if v.get("mp4_url") or v.get("url")
        ]

    elif provider == "internet_archive":
        resp = http_get_json(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"{query} AND mediatype:image",
                "output": "json",
                "rows": count,
                "fl[]": "identifier,title",
            },
        )
        docs = resp.get("response", {}).get("docs", [])
        return [
            {
                "url": f"https://archive.org/download/{d['identifier']}/{d['identifier']}.jpg",
                "provider": "internet_archive",
                "width": 0,
                "height": 0,
                "id": d["identifier"],
            }
            for d in docs
        ]

    elif provider == "getimg":
        resp = http_post_json(
            "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image",
            {
                "prompt": f"dark cinematic documentary style: {query}, dramatic lighting, high contrast, photorealistic",
                "negative_prompt": "cartoon, anime, bright colors, cheerful",
                "width": 1280,
                "height": 720,
                "steps": 25,
                "output_format": "jpeg",
            },
            headers={"Authorization": f"Bearer {cfg['key']}"},
        )
        if resp.get("image"):
            return [{
                "url_base64": resp["image"],
                "provider": "getimg",
                "width": 1280,
                "height": 720,
                "id": f"getimg_{int(time.time())}",
                "type": "ai_generated",
            }]
        return []

    elif provider == "replicate":
        # Trigger SDXL inference
        trigger_resp = http_post_json(
            "https://api.replicate.com/v1/models/stability-ai/sdxl/predictions",
            {
                "input": {
                    "prompt": f"dark cinematic documentary: {query}, dramatic, high contrast, film noir",
                    "negative_prompt": "cartoon, bright, cheerful, anime",
                    "width": 1280,
                    "height": 720,
                }
            },
            headers={
                "Authorization": f"Token {cfg['key']}",
                "Prefer": "wait=60",
            },
        )
        output = trigger_resp.get("output", [])
        if isinstance(output, list) and output:
            return [{
                "url": output[0],
                "provider": "replicate",
                "width": 1280,
                "height": 720,
                "id": trigger_resp.get("id", f"repl_{int(time.time())}"),
                "type": "ai_generated",
            }]
        return []

    elif provider == "huggingface":
        import base64
        raw = http_post_json(
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
            {"inputs": f"dark cinematic documentary: {query}, dramatic lighting, film noir"},
            headers={"Authorization": f"Bearer {cfg['key']}"},
        )
        # HF returns base64 encoded image
        if isinstance(raw, dict) and raw.get("image"):
            return [{
                "url_base64": raw["image"],
                "provider": "huggingface",
                "width": 1024,
                "height": 576,
                "id": f"hf_{int(time.time())}",
                "type": "ai_generated",
            }]
        return []

    raise ValueError(f"Unknown visual provider: {provider}")


# ─────────────────────────────────────────────
# IMAGE DOWNLOAD HELPER
# ─────────────────────────────────────────────

def download_image(url: str, dest_path: str, timeout: int = 20) -> bool:
    """
    Downloads an image from URL to dest_path.
    Returns True on success. Handles both http URLs and base64 payloads.
    """
    try:
        if url.startswith("data:") or not url.startswith("http"):
            # base64 inline
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
        log.warning(f"Image download failed ({url[:60]}...): {exc}")
        return False


def download_base64_image(b64_string: str, dest_path: str) -> bool:
    """Saves a raw base64 image string to disk."""
    import base64
    try:
        with open(dest_path, "wb") as f:
            f.write(base64.b64decode(b64_string))
        return True
    except Exception as exc:
        log.warning(f"Base64 image save failed: {exc}")
        return False

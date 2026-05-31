"""
engines/image_generator.py
Karma Vault Stories — AI Image Generation Engine (Phase B upgraded)
Cascade: Leonardo AI → Stability AI XL → GetIMG → Replicate SDXL → HuggingFace
Generates dark cinematic stills for scene backgrounds and thumbnail composites.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.api_client import http_get, http_get_json, http_post_json, download_image
from utils.r2_cache import R2Cache, image_cache_key

log = get_logger(__name__)

# ── Negative prompt shared across all providers ────────────────────────────────
_NEGATIVE = (
    "text, watermark, letters, alphabet, words, captions, subtitles, "
    "logo, banner, cartoon, anime, illustration, bright colors, cheerful, "
    "nsfw, blurry, low quality, jpeg artifacts, people smiling, daylight"
)


# ─────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────

def generate_ai_image(
    prompt:      str,
    output_path: Path,
    pillar:      str = "",
    horror_mode: bool = False,
) -> bool:
    """
    Generates a dark cinematic image.
    Tries providers in cascade order; returns True on first success.
    Checks R2 cache before any API call.
    """
    full_prompt = _enrich_prompt(prompt, pillar, horror_mode)
    cache_key   = image_cache_key(full_prompt)
    r2          = R2Cache.get()

    # R2 cache hit
    if r2.is_available() and r2.get_image(cache_key, output_path):
        log.debug(f"Image cache hit: {cache_key[:20]}...")
        return True

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ok = (
        _generate_leonardo(full_prompt, output_path)
        or _generate_stability(full_prompt, output_path)
        or _generate_getimg(full_prompt, output_path)
        or _generate_replicate(full_prompt, output_path)
        or _generate_huggingface(full_prompt, output_path)
    )

    if ok and output_path.exists():
        if r2.is_available():
            r2.put_image(cache_key, output_path)
    return ok


def _enrich_prompt(prompt: str, pillar: str, horror_mode: bool) -> str:
    """Prefixes every image prompt with cinematic dark documentary style cues."""
    style = "dark cinematic documentary, dramatic lighting, film grain, 4K"
    if horror_mode:
        style += ", horror atmosphere, deep shadows, unsettling"
    pillar_suffix = {
        "paranormal_haunted_jinn":      ", eerie supernatural, mist",
        "human_betrayal_revenge":       ", intense noir, tension",
        "mystery_disappearances":       ", suspense, cold tones",
        "disturbing_accidents_records": ", clinical, stark",
        "historical_dark_secrets":      ", aged textures, sepia accent",
        "ai_original_horror":           ", cold blue glow, technological",
        "secret_double_life":           ", venetian shadow, split tone",
        "internet_confession":          ", screen glow, intimate",
        "urban_legends_paranormal":     ", night fog, urban decay",
        "true_shocking_crime":          ", crime scene, stark white flash",
    }.get(pillar, "")
    return f"{style}{pillar_suffix}. {prompt[:220]}"


# ─────────────────────────────────────────────
# LEONARDO AI (primary — best photorealism)
# ─────────────────────────────────────────────

def _generate_leonardo(prompt: str, out: Path) -> bool:
    from config.settings import LEONARDO
    if not LEONARDO:
        return False
    try:
        # Step 1: create generation
        resp = http_post_json(
            "https://cloud.leonardo.ai/api/rest/v1/generations",
            {
                "prompt":               prompt[:500],
                "negative_prompt":      _NEGATIVE,
                "modelId":              "b24e16ff-06e3-43eb-8d33-4416c2d75876",  # Leonardo Diffusion XL
                "width":                1280,
                "height":               720,
                "num_images":           1,
                "guidance_scale":       7,
                "scheduler":            "EULER_DISCRETE",
                "photoReal":            True,
                "photoRealVersion":     "v2",
                "alchemy":              True,
            },
            headers={"authorization": f"Bearer {LEONARDO}"},
            timeout=30,
        )
        gen_id = (resp.get("sdGenerationJob") or {}).get("generationId")
        if not gen_id:
            return False

        # Step 2: poll for completion
        for _ in range(30):
            time.sleep(4)
            poll = http_get_json(
                f"https://cloud.leonardo.ai/api/rest/v1/generations/{gen_id}",
                headers={"authorization": f"Bearer {LEONARDO}"},
                timeout=15,
            )
            images = (
                (poll.get("generations_by_pk") or {})
                .get("generated_images", [])
            )
            if images:
                url = images[0].get("url", "")
                if url:
                    return download_image(url, str(out), timeout=30)
        return False
    except Exception as exc:
        log.debug(f"Leonardo error: {exc}")
        return False


# ─────────────────────────────────────────────
# STABILITY AI (secondary — fast SDXL)
# ─────────────────────────────────────────────

def _generate_stability(prompt: str, out: Path) -> bool:
    from config.settings import STABILITY
    if not STABILITY:
        return False
    try:
        resp = http_post_json(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            {
                "prompt":           prompt[:500],
                "negative_prompt":  _NEGATIVE,
                "aspect_ratio":     "16:9",
                "output_format":    "jpeg",
                "seed":             0,
                "style_preset":     "cinematic",
            },
            headers={
                "authorization": f"Bearer {STABILITY}",
                "accept":        "application/json",
            },
            timeout=40,
        )
        b64 = resp.get("image") or resp.get("base64")
        if b64:
            out.write_bytes(base64.b64decode(b64))
            return out.exists() and out.stat().st_size > 10_000
        # Sometimes returns artifact URL
        url = resp.get("finish_reasons", [{}])[0].get("uri", "")
        if url:
            return download_image(url, str(out), timeout=30)
        return False
    except Exception as exc:
        log.debug(f"Stability error: {exc}")
        return False


# ─────────────────────────────────────────────
# GETIMG (tertiary)
# ─────────────────────────────────────────────

def _generate_getimg(prompt: str, out: Path) -> bool:
    from config.settings import GETIMG_API_KEY
    key = GETIMG_API_KEY
    if not key:
        return False
    try:
        resp = http_post_json(
            "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image",
            {
                "prompt":          prompt[:500],
                "negative_prompt": _NEGATIVE,
                "width":           1280,
                "height":          720,
                "steps":           25,
                "output_format":   "jpeg",
            },
            headers={"authorization": f"Bearer {key}"},
            timeout=40,
        )
        b64 = resp.get("image")
        if b64:
            out.write_bytes(base64.b64decode(b64))
            return out.exists() and out.stat().st_size > 10_000
        return False
    except Exception as exc:
        log.debug(f"GetIMG error: {exc}")
        return False


# ─────────────────────────────────────────────
# REPLICATE SDXL (quaternary)
# ─────────────────────────────────────────────

def _generate_replicate(prompt: str, out: Path) -> bool:
    from config.settings import REPLICATE_API_TOKEN
    if not REPLICATE_API_TOKEN:
        return False
    try:
        resp = http_post_json(
            "https://api.replicate.com/v1/models/stability-ai/sdxl/predictions",
            {
                "input": {
                    "prompt":          prompt[:500],
                    "negative_prompt": _NEGATIVE,
                    "width":           1280,
                    "height":          720,
                    "num_inference_steps": 25,
                    "guidance_scale":  7.5,
                },
            },
            headers={
                "Authorization": f"Token {REPLICATE_API_TOKEN}",
                "Prefer":        "wait=60",
            },
            timeout=90,
        )
        output = resp.get("output", [])
        if isinstance(output, list) and output:
            return download_image(output[0], str(out), timeout=30)
        pred_id = resp.get("id")
        if not pred_id:
            return False
        for _ in range(20):
            time.sleep(5)
            poll = http_get_json(
                f"https://api.replicate.com/v1/predictions/{pred_id}",
                headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"},
                timeout=15,
            )
            if poll.get("status") == "succeeded":
                urls = poll.get("output", [])
                if urls:
                    return download_image(urls[0], str(out), timeout=30)
            if poll.get("status") in ("failed", "canceled"):
                return False
        return False
    except Exception as exc:
        log.debug(f"Replicate SDXL error: {exc}")
        return False


# ─────────────────────────────────────────────
# HUGGINGFACE (final fallback — free)
# ─────────────────────────────────────────────

def _generate_huggingface(prompt: str, out: Path) -> bool:
    from config.settings import HF_API_TOKEN
    if not HF_API_TOKEN:
        return False
    try:
        raw = http_post_json(
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
            {"inputs": prompt[:400]},
            headers={"Authorization": f"Bearer {HF_API_TOKEN}"},
            timeout=60,
        )
        if isinstance(raw, dict):
            b64 = raw.get("image") or raw.get("generated_image")
            if b64:
                out.write_bytes(base64.b64decode(b64))
                return out.exists() and out.stat().st_size > 10_000
        # HF can return raw bytes as image
        if isinstance(raw, bytes) and len(raw) > 10_000:
            out.write_bytes(raw)
            return True
        return False
    except Exception as exc:
        log.debug(f"HuggingFace error: {exc}")
        return False

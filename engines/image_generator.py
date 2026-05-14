"""
engines/image_generator.py
Karma Vault Stories — AI Image Generation Fallback Engine
Cascades through GetImg → Replicate → HuggingFace when all stock
sources return insufficient results. Wraps every call in dark cinematic
prompt engineering to ensure outputs match the channel's visual identity.
"""

import time
import base64
import json
import random
from pathlib import Path
from typing import Optional

from config.settings import (
    GETIMG_API_KEY, REPLICATE_API_TOKEN, HF_API_TOKEN,
    VIDEO_WIDTH, VIDEO_HEIGHT, SHORT_WIDTH, SHORT_HEIGHT,
    API_REQUEST_TIMEOUT_SEC,
)
from config.constants import ContentPillar
from utils.logger import get_logger
from utils.api_client import http_post_json, http_get_json, http_get, with_retry

log = get_logger(__name__)

# Hard negative prompt applied to every AI generation call
_NEGATIVE_PROMPT = (
    # Aesthetic quality
    "cartoon, anime, illustration, drawing, painting, watercolor, sketch, 3d render, "
    "cgi, digital art style, low quality, blurry, out of focus, jpeg artifacts, "
    "oversaturated, overexposed, underexposed, grainy, noisy, pixelated, "
    # Text and branding — STRICTLY FORBIDDEN
    "text, letters, words, english text, any text, typography, font, caption, "
    "subtitles, label, title, headline, quote, speech bubble, dialogue, "
    "watermark, signature, logo, brand, url, website, social media handle, "
    # Mockups and staged elements — STRICTLY FORBIDDEN
    "mockup, product placement, advertisement, poster on wall, framed picture, "
    "screen mockup, phone mockup, device mockup, background mockup, "
    # Decorative and artificial elements — STRICTLY FORBIDDEN
    "curtains, drapes, fabric backdrop, paper texture backdrop, "
    "studio backdrop, colored background, gradient background, "
    "decorative border, ornamental frame, vignette overlay, "
    "artificial shadows, drop shadow, fake bokeh, lens flare overlay, "
    # Content restrictions
    "bright colors, cheerful, happy, optimistic, daylight sun, white background, "
    "nsfw, nude, explicit, gore, disturbing realistic violence"
)

# Dark cinematic style prefix injected into every prompt
_STYLE_PREFIX = (
    "dark cinematic documentary photography, dramatic chiaroscuro lighting, "
    "high contrast, deep shadows, film noir aesthetic, photorealistic, "
    "8k resolution, cinematic color grade: "
)

# Pillar-specific mood modifiers appended to prompts
_PILLAR_MOOD_SUFFIX: dict[str, str] = {
    ContentPillar.PARANORMAL.value:
        "eerie paranormal atmosphere, supernatural dread, haunted location",
    ContentPillar.HUMAN_BETRAYAL.value:
        "noir mystery, human tension, psychological thriller atmosphere",
    ContentPillar.MYSTERY_DISAPPEARANCE.value:
        "cold case investigation, forensic darkness, missing person dread",
    ContentPillar.DISTURBING_ACCIDENTS.value:
        "tragedy aftermath, grim reality, dark incident documentation",
    ContentPillar.HISTORICAL_DARK.value:
        "historical darkness, archival sepia grunge, forgotten era menace",
    ContentPillar.AI_HORROR.value:
        "dystopian technology horror, cold machine aesthetic, digital dread",
    ContentPillar.SECRET_DOUBLE_LIFE.value:
        "hidden identity, noir shadow play, psychological suspense",
    ContentPillar.INTERNET_CONFESSION.value:
        "digital darkness, screen glow horror, anonymous confession atmosphere",
    ContentPillar.URBAN_LEGENDS.value:
        "urban decay, legend-haunted location, creepypasta atmosphere",
    ContentPillar.TRUE_SHOCKING.value:
        "dark crime scene adjacent, investigative documentary, grim truth",
}


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def generate_ai_image(
    scene_prompt:  str,
    output_path:   Path,
    pillar:        str  = ContentPillar.TRUE_SHOCKING.value,
    for_short:     bool = False,
    horror_mode:   bool = False,
) -> bool:
    """
    Generates a single AI image for the given scene prompt.
    Tries GetImg → Replicate → HuggingFace in order.
    Returns True on success, False if all providers fail.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    full_prompt = _build_full_prompt(scene_prompt, pillar, horror_mode)
    width  = SHORT_WIDTH  if for_short else VIDEO_WIDTH
    height = SHORT_HEIGHT if for_short else VIDEO_HEIGHT

    # ── 1. GetImg ─────────────────────────────────────────────────
    if GETIMG_API_KEY:
        try:
            if _generate_getimg(full_prompt, output_path, width, height):
                log.debug(f"AI image via GetImg: {output_path.name}")
                return True
        except Exception as exc:
            log.warning(f"GetImg failed: {exc}")

    # ── 2. Replicate (SDXL / FLUX) ───────────────────────────────
    if REPLICATE_API_TOKEN:
        try:
            if _generate_replicate(full_prompt, output_path, width, height):
                log.debug(f"AI image via Replicate: {output_path.name}")
                return True
        except Exception as exc:
            log.warning(f"Replicate failed: {exc}")

    # ── 3. HuggingFace Inference API ─────────────────────────────
    if HF_API_TOKEN:
        try:
            if _generate_huggingface(full_prompt, output_path):
                log.debug(f"AI image via HuggingFace: {output_path.name}")
                return True
        except Exception as exc:
            log.warning(f"HuggingFace failed: {exc}")

    log.warning(f"All AI image providers failed for: {scene_prompt[:60]}")
    return False


def generate_ai_image_batch(
    prompts:    list[str],
    output_dir: Path,
    pillar:     str  = ContentPillar.TRUE_SHOCKING.value,
    prefix:     str  = "ai_img",
) -> list[Path]:
    """
    Generates multiple AI images. Returns list of successful output paths.
    Stops early if all providers are exhausted.
    """
    results: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for idx, prompt in enumerate(prompts):
        out = output_dir / f"{prefix}_{idx:03d}.jpg"
        if generate_ai_image(prompt, out, pillar=pillar):
            results.append(out)
        time.sleep(0.5)   # avoid hammering APIs
    return results


# ─────────────────────────────────────────────
# PROMPT ENGINEERING
# ─────────────────────────────────────────────

def _build_full_prompt(
    scene_prompt: str,
    pillar:       str,
    horror_mode:  bool,
) -> str:
    mood = _PILLAR_MOOD_SUFFIX.get(pillar, "dark cinematic documentary")
    if horror_mode:
        mood += ", blood red tint, extreme horror"
    return f"{_STYLE_PREFIX}{scene_prompt.strip().rstrip('.')}. {mood}"


# ─────────────────────────────────────────────
# PROVIDER IMPLEMENTATIONS
# ─────────────────────────────────────────────

def _generate_getimg(
    prompt:      str,
    output_path: Path,
    width:       int,
    height:      int,
) -> bool:
    """
    GetImg Stable Diffusion XL text-to-image.
    Returns base64 JPEG; decoded and saved to output_path.
    """
    # GetImg requires dimensions divisible by 64
    w = _snap_to_64(min(width, 1344))
    h = _snap_to_64(min(height, 768))

    resp = with_retry(
        http_post_json,
        "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image",
        {
            "prompt":          prompt[:1500],
            "negative_prompt": _NEGATIVE_PROMPT,
            "width":           w,
            "height":          h,
            "steps":           25,
            "guidance":        7.5,
            "output_format":   "jpeg",
        },
        headers={"Authorization": f"Bearer {GETIMG_API_KEY}"},
        timeout=90,
    )
    b64 = resp.get("image")
    if not b64:
        return False
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return output_path.stat().st_size > 5000


def _generate_replicate(
    prompt:      str,
    output_path: Path,
    width:       int,
    height:      int,
) -> bool:
    """
    Replicate SDXL with synchronous wait.
    Falls back to FLUX Schnell if SDXL is unavailable.
    """
    w = _snap_to_64(min(width, 1280))
    h = _snap_to_64(min(height, 720))

    headers = {
        "Authorization": f"Token {REPLICATE_API_TOKEN}",
        "Content-Type":  "application/json",
        "Prefer":        "wait=60",
    }

    # Try SDXL first
    for model_path, payload in [
        (
            "stability-ai/sdxl",
            {
                "input": {
                    "prompt":          prompt[:1500],
                    "negative_prompt": _NEGATIVE_PROMPT,
                    "width":           w,
                    "height":          h,
                    "num_outputs":     1,
                    "num_inference_steps": 25,
                    "guidance_scale":  7.5,
                }
            },
        ),
        (
            "black-forest-labs/flux-schnell",
            {
                "input": {
                    "prompt":          prompt[:1500],
                    "width":           w,
                    "height":          h,
                    "num_outputs":     1,
                    "num_inference_steps": 4,
                    "go_fast":         True,
                }
            },
        ),
    ]:
        try:
            resp = with_retry(
                http_post_json,
                f"https://api.replicate.com/v1/models/{model_path}/predictions",
                payload,
                headers=headers,
                timeout=90,
            )
            # Replicate may need polling if not complete in wait window
            pred_id  = resp.get("id")
            output   = resp.get("output")
            status   = resp.get("status", "")

            if not output and pred_id and status not in ("failed", "canceled"):
                output = _poll_replicate(pred_id)

            if isinstance(output, list) and output:
                img_url = output[0]
            elif isinstance(output, str) and output.startswith("http"):
                img_url = output
            else:
                continue

            raw = with_retry(http_get, img_url, timeout=30)
            with open(output_path, "wb") as f:
                f.write(raw)
            if output_path.stat().st_size > 5000:
                return True
        except Exception as exc:
            log.debug(f"Replicate model {model_path} failed: {exc}")
            continue

    return False


def _poll_replicate(prediction_id: str, max_wait_sec: int = 90) -> Optional[list]:
    """Polls Replicate prediction until SUCCESS or timeout."""
    headers  = {"Authorization": f"Token {REPLICATE_API_TOKEN}"}
    url      = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    deadline = time.time() + max_wait_sec

    while time.time() < deadline:
        time.sleep(3)
        try:
            resp   = with_retry(http_get_json, url, headers=headers, timeout=15)
            status = resp.get("status", "")
            if status == "succeeded":
                return resp.get("output")
            if status in ("failed", "canceled"):
                return None
        except Exception:
            break
    return None


def _generate_huggingface(
    prompt:      str,
    output_path: Path,
) -> bool:
    """
    HuggingFace Inference API — SDXL base model.
    Returns raw JPEG bytes.
    """
    try:
        raw = with_retry(
            http_post_json,
            "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
            {"inputs": prompt[:1000]},
            headers={"Authorization": f"Bearer {HF_API_TOKEN}"},
            timeout=90,
        )
        # HF sometimes returns {"error": "..."} as JSON
        if isinstance(raw, dict):
            log.warning(f"HuggingFace returned JSON error: {raw}")
            return False
    except Exception:
        # HF inference API returns raw bytes, not JSON — try direct GET
        try:
            import urllib.request, urllib.error
            import urllib.parse as up
            body = json.dumps({"inputs": prompt[:1000]}).encode()
            req  = urllib.request.Request(
                "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
                data=body,
                headers={
                    "Authorization":  f"Bearer {HF_API_TOKEN}",
                    "Content-Type":   "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "image" in content_type:
                    raw = resp.read()
                    with open(output_path, "wb") as f:
                        f.write(raw)
                    return output_path.stat().st_size > 5000
        except Exception as exc:
            log.warning(f"HuggingFace raw request failed: {exc}")
        return False

    if isinstance(raw, (bytes, bytearray)):
        with open(output_path, "wb") as f:
            f.write(raw)
        return output_path.stat().st_size > 5000
    return False


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _snap_to_64(value: int) -> int:
    """Rounds down to nearest multiple of 64 (required by most diffusion models)."""
    return max(64, (value // 64) * 64)

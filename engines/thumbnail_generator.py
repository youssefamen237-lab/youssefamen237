"""
engines/thumbnail_generator.py
Karma Vault Stories — Thumbnail Generator Engine
Composites production-ready YouTube thumbnails at 1280×720.
Pipeline: background selection → heavy cinematic grading → template
gradient → +18 badge → stroke headline text → channel tag.
All AI generation calls use strict negative prompts forbidding
any text, lettering, mockups, curtains, shadows, or decorative elements.
"""

import random
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

from config.settings import (
    GETIMG_API_KEY, REPLICATE_API_TOKEN, HF_API_TOKEN,
    FONTS_DIR, VIDEO_WIDTH, VIDEO_HEIGHT,
)
from config.constants import (
    THUMBNAIL_TEMPLATES, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT,
    THUMBNAIL_BADGE_TEXT, THUMBNAIL_MAX_WORDS,
    VISUAL_COLORS, ContentPillar, AssetCategory,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import thumbnail_path, ensure_run_workspace
from engines.scene_builder import _apply_cinematic_grading, _load_font

log = get_logger(__name__)

TW = THUMBNAIL_WIDTH    # 1280
TH = THUMBNAIL_HEIGHT   # 720

# Thumbnail grading is more aggressive than video grading
_THUMB_CONTRAST   = 1.25
_THUMB_BRIGHTNESS = 0.78
_THUMB_SATURATION = 0.72
_THUMB_VIGNETTE   = 0.55   # stronger vignette for thumbnail

# Badge geometry
_BADGE_RADIUS = 52
_BADGE_X      = 52   # center x from left
_BADGE_Y      = 52   # center y from top
_BADGE_COLOR  = (180, 0, 0)      # deep red
_BADGE_TEXT   = "#FFFFFF"

# Strict negative prompt for thumbnail AI background generation
_THUMB_NEGATIVE_PROMPT = (
    # Text — absolutely forbidden (we add text ourselves in post)
    "text, letters, words, english text, any text, typography, font, caption, "
    "subtitles, label, title, headline, watermark, signature, logo, "
    "speech bubble, dialogue, number, digit, "
    # Mockups and staged compositions — forbidden
    "mockup, product placement, poster on wall, framed picture, "
    "screen mockup, phone mockup, device mockup, background mockup, "
    "studio setup, advertising layout, "
    # Decorative and artificial elements — forbidden
    "curtains, drapes, fabric backdrop, paper texture backdrop, "
    "studio backdrop, colored background, gradient background, "
    "decorative border, ornamental frame, ornament, decoration, "
    "artificial shadows, drop shadow, lens flare overlay, "
    # Quality and style restrictions
    "cartoon, anime, illustration, drawing, painting, watercolor, "
    "cgi, 3d render, oversaturated, overexposed, blurry, low quality, "
    "jpeg artifacts, noisy, pixelated, cheerful, happy, bright, daylight, "
    "nsfw, gore"
)

_THUMB_STYLE_PREFIX = (
    "dark cinematic still photography, dramatic professional lighting, "
    "deep shadows, high contrast, photorealistic, award-winning documentary "
    "still frame, no text, no letters, clean background, "
)


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_thumbnail_generator(ctx: DailyRunContext) -> DailyRunContext:
    """
    Generates the YouTube thumbnail and sets ctx.thumbnail_path.
    1. Selects best background image from scene_assets
    2. Falls back to AI generation or procedural dark background
    3. Applies heavy grading + template gradient overlay
    4. Composites +18 badge and headline text
    """
    log.info(f"Thumbnail generator starting. Template={ctx.thumbnail_template_id}")
    ensure_run_workspace(ctx.run_id)

    # Get template config
    template = _get_template(ctx.thumbnail_template_id)
    text     = _prepare_thumb_text(ctx)
    out_path = thumbnail_path(ctx.run_id, "thumbnail.jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Select background ────────────────────────────────
    bg_path = _select_background(ctx, template)
    log.info(f"Thumbnail background: {bg_path.name if bg_path else 'procedural'}")

    # ── Step 2: Load and grade background ────────────────────────
    canvas = _build_thumbnail_canvas(bg_path, template, ctx)

    # ── Step 3: Composite all elements ───────────────────────────
    canvas = _draw_template_gradient(canvas, template)
    canvas = _draw_badge(canvas)
    canvas = _draw_headline(canvas, text, template)
    canvas = _draw_channel_tag(canvas)

    # ── Step 4: Final output ──────────────────────────────────────
    canvas.save(str(out_path), "JPEG", quality=95, optimize=True)
    ctx.thumbnail_path = str(out_path)
    log.info(f"Thumbnail saved: {out_path.name} "
             f"({out_path.stat().st_size // 1024}KB) | Text: '{text}'")

    ctx.mark_stage("thumbnail_generator")
    return ctx


# ─────────────────────────────────────────────
# BACKGROUND SELECTION
# ─────────────────────────────────────────────

def _select_background(ctx: DailyRunContext, template: dict) -> Optional[Path]:
    """
    Selects the most visually impactful scene asset as thumbnail background.
    Priority: horror/climax scenes > hook scenes > any stock photo.
    Falls back to AI generation, then procedural dark background.
    """
    scene_assets = ctx.scene_assets or []

    # Filter to actual image assets (not generated cards)
    usable = [
        s for s in scene_assets
        if s.get("asset_path")
        and s.get("asset_type") in (
            AssetCategory.STOCK_PHOTO.value,
            AssetCategory.AI_DRAMATIC_STILL.value,
            "ai_still",
        )
        and Path(s["asset_path"]).exists()
    ]

    if usable:
        # Priority 1: climax or escalation scenes with horror grading
        horror_scenes = [
            s for s in usable
            if s.get("horror_grading") and s.get("part_id") in ("climax", "escalation")
        ]
        # Priority 2: hook scenes
        hook_scenes = [s for s in usable if s.get("part_id") == "hook"]

        pool = horror_scenes or hook_scenes or usable
        chosen = random.choice(pool)
        return Path(chosen["asset_path"])

    # Fallback: AI generate a thumbnail-specific background
    log.info("No scene assets available — generating AI thumbnail background.")
    ai_path = _generate_ai_thumb_background(ctx)
    if ai_path:
        return ai_path

    # Final fallback: procedural
    return None


def _generate_ai_thumb_background(ctx: DailyRunContext) -> Optional[Path]:
    """Generates an AI image specifically composed for thumbnail backgrounds."""
    from engines.image_generator import generate_ai_image

    pillar  = (ctx.selected_story.pillar if ctx.selected_story
                else ContentPillar.TRUE_SHOCKING.value)
    country = (ctx.selected_story.country if ctx.selected_story else "Unknown")

    # Template-specific prompts — purely visual, no text
    pillar_prompts = {
        ContentPillar.PARANORMAL.value:
            "dark corridor with distant eerie light, mist at floor level, ominous presence implied",
        ContentPillar.HUMAN_BETRAYAL.value:
            "lone silhouette standing in doorway of dark room, dramatic back lighting",
        ContentPillar.MYSTERY_DISAPPEARANCE.value:
            "empty dark road at night, single distant light, fog, deserted scene",
        ContentPillar.TRUE_SHOCKING.value:
            "dramatic dark cinematic landscape, deep shadows, solitary figure silhouette",
        ContentPillar.HISTORICAL_DARK.value:
            "dark archive room with single overhead light, dust in air, deep shadows",
        ContentPillar.AI_HORROR.value:
            "dark server room with blue glow, cables, ominous machinery in shadows",
    }
    prompt = pillar_prompts.get(
        pillar,
        "dark dramatic environment, deep shadows, cinematic composition, no subjects"
    )
    full_prompt = (
        f"{_THUMB_STYLE_PREFIX} {prompt}, "
        f"no text, no letters, no words, clean composition"
    )

    ai_path = thumbnail_path(ctx.run_id, "thumb_bg_ai.jpg")
    try:
        from utils.api_client import http_post_json, http_get, with_retry
        import base64, json as _json, time

        if GETIMG_API_KEY:
            resp = with_retry(
                http_post_json,
                "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image",
                {
                    "prompt":          full_prompt[:1200],
                    "negative_prompt": _THUMB_NEGATIVE_PROMPT,
                    "width":           1280,
                    "height":          704,   # closest 64-snap to 720
                    "steps":           25,
                    "guidance":        8.0,
                    "output_format":   "jpeg",
                },
                headers={"Authorization": f"Bearer {GETIMG_API_KEY}"},
                timeout=90,
            )
            b64 = resp.get("image")
            if b64:
                with open(ai_path, "wb") as f:
                    f.write(base64.b64decode(b64))
                if ai_path.stat().st_size > 5000:
                    return ai_path
    except Exception as exc:
        log.warning(f"AI thumbnail background failed: {exc}")
    return None


# ─────────────────────────────────────────────
# CANVAS BUILDING
# ─────────────────────────────────────────────

def _build_thumbnail_canvas(
    bg_path:  Optional[Path],
    template: dict,
    ctx:      DailyRunContext,
) -> Image.Image:
    """
    Loads the background and applies thumbnail-specific heavy grading.
    Falls back to procedural dark canvas if bg_path is None or invalid.
    """
    if bg_path and bg_path.exists():
        try:
            img = Image.open(str(bg_path)).convert("RGB")
            img = _resize_crop(img, TW, TH)
            return _apply_thumbnail_grading(img, template)
        except Exception as exc:
            log.warning(f"Could not load background {bg_path}: {exc}")

    return _generate_procedural_background(ctx, template)


def _apply_thumbnail_grading(img: Image.Image, template: dict) -> Image.Image:
    """
    Heavier grading than video: darker, more contrast, stronger vignette.
    Optimized for thumbnail CTR — must be visually striking at small size.
    """
    img = ImageEnhance.Contrast(img).enhance(_THUMB_CONTRAST)
    img = ImageEnhance.Brightness(img).enhance(_THUMB_BRIGHTNESS)
    img = ImageEnhance.Color(img).enhance(_THUMB_SATURATION)

    arr = np.array(img, dtype=np.float32)

    # Strong vignette
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt(((X - w/2)/(w/2))**2 + ((Y - h/2)/(h/2))**2)
    fade = np.clip((dist - 0.30)/0.65, 0, 1) ** 2.0 * _THUMB_VIGNETTE
    arr  = arr * (1 - fade)[:, :, np.newaxis]

    # Template-specific tint
    bg_style = template.get("bg_style", "dark_gradient")
    if bg_style == "blood_red":
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.25, 0, 255)
        arr[:, :, 1] = arr[:, :, 1] * 0.80
        arr[:, :, 2] = arr[:, :, 2] * 0.75
    elif bg_style == "fog_dark":
        # Blue-grey shift
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.15, 0, 255)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _generate_procedural_background(
    ctx:      DailyRunContext,
    template: dict,
) -> Image.Image:
    """
    Generates a dark procedural background when no image is available.
    Uses numpy to create a moody gradient with subtle texture.
    """
    bg_style = template.get("bg_style", "dark_gradient")
    arr = np.zeros((TH, TW, 3), dtype=np.float32)

    pillar = (ctx.selected_story.pillar if ctx.selected_story
              else ContentPillar.TRUE_SHOCKING.value)

    # Base gradient: very dark, varies by template
    if bg_style == "blood_red":
        for y in range(TH):
            fade = (y / TH) ** 1.5
            arr[y, :, 0] = 25 + fade * 55    # red channel
            arr[y, :, 1] = 2  + fade * 5
            arr[y, :, 2] = 2  + fade * 5
    elif bg_style == "paper_aged":
        base = 18
        arr[:, :, 0] = base + 8
        arr[:, :, 1] = base + 4
        arr[:, :, 2] = base
        # Add slight warm noise for paper texture
        noise = np.random.randn(TH, TW) * 6
        arr[:, :, 0] += noise
        arr[:, :, 1] += noise * 0.6
    else:
        # Default: dark gradient
        for y in range(TH):
            fade = (y / TH) * 0.7
            arr[y, :, 0] = 5  + fade * 12
            arr[y, :, 1] = 3  + fade * 8
            arr[y, :, 2] = 8  + fade * 18

    # Subtle noise for organic feel
    arr += np.random.randn(TH, TW, 3) * 3
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


# ─────────────────────────────────────────────
# COMPOSITING ELEMENTS
# ─────────────────────────────────────────────

def _draw_template_gradient(canvas: Image.Image, template: dict) -> Image.Image:
    """
    Adds a template-specific dark gradient overlay to ensure text readability.
    Varies by text position to darken the text region.
    """
    text_pos = template.get("text_position", "top_right")
    arr      = np.array(canvas, dtype=np.float32)

    # Create a directional darkness gradient for the text region
    if text_pos == "top_right":
        # Darken top-right quadrant
        for x in range(TW // 2, TW):
            t = (x - TW // 2) / (TW // 2)
            arr[:TH // 2, x, :] *= max(0.3, 1.0 - t * 0.65)
    elif text_pos == "bottom_center":
        # Darken bottom third
        for y in range(int(TH * 0.60), TH):
            t = (y - TH * 0.60) / (TH * 0.40)
            arr[y, :, :] *= max(0.15, 1.0 - t * 0.80)
    elif text_pos == "center":
        # Dark horizontal band across center
        center_top    = int(TH * 0.35)
        center_bottom = int(TH * 0.65)
        arr[center_top:center_bottom, :, :] *= 0.45
    elif text_pos == "top_center":
        # Darken top third
        for y in range(int(TH * 0.40)):
            t = 1.0 - (y / (TH * 0.40))
            arr[y, :, :] *= max(0.20, 1.0 - t * 0.75)

    # Always darken very bottom strip for badge/tag readability
    arr[int(TH * 0.90):, :, :] *= 0.50

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _draw_badge(canvas: Image.Image) -> Image.Image:
    """
    Draws the +18 red badge in the top-left corner.
    Consistent position and size across all templates.
    """
    draw    = ImageDraw.Draw(canvas)
    cx, cy  = _BADGE_X, _BADGE_Y
    r       = _BADGE_RADIUS

    # Red filled circle
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=_BADGE_COLOR,
    )
    # White ring (inner border for polish)
    draw.ellipse(
        [cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4],
        outline=(255, 255, 255), width=2,
    )

    # "+18" text — two parts: "+" and "18"
    font_plus = _load_font(30)
    font_num  = _load_font(44)

    plus_text = "+"
    num_text  = "18"

    bbox_plus = draw.textbbox((0, 0), plus_text, font=font_plus)
    bbox_num  = draw.textbbox((0, 0), num_text,  font=font_num)
    pw = bbox_plus[2] - bbox_plus[0]
    nw = bbox_num[2]  - bbox_num[0]
    ph = bbox_plus[3] - bbox_plus[1]
    nh = bbox_num[3]  - bbox_num[1]

    # Center both parts together
    total_w = pw + nw - 2
    sx = cx - total_w // 2
    sy = cy - nh // 2

    draw.text((sx, sy + (nh - ph) // 2), plus_text, font=font_plus, fill=(255, 255, 255))
    draw.text((sx + pw - 2, sy), num_text, font=font_num, fill=(255, 255, 255))

    return canvas


def _draw_headline(
    canvas:   Image.Image,
    text:     str,
    template: dict,
) -> Image.Image:
    """
    Renders the 2-4 word headline with thick stroke for maximum CTR impact.
    Font size auto-scales to fill the available text region.
    Text color: white or shock-red depending on template.
    """
    if not text.strip():
        return canvas

    draw     = ImageDraw.Draw(canvas)
    text_pos = template.get("text_position", "top_right")
    words    = text.strip().upper().split()[:THUMBNAIL_MAX_WORDS]
    line1, line2 = _split_headline(words)

    # Auto-scale font to fill the text region width
    target_w = _get_text_region_width(text_pos, len(words))
    font_size = _fit_font_size(draw, line1, target_w, min_size=80, max_size=260)
    font      = _load_font(font_size)

    # Position anchor
    ax, ay = _get_text_anchor(text_pos, font_size, bool(line2))

    # Colors
    fill_color   = (255, 255, 255)
    stroke_color = (0, 0, 0)
    # Use red for specific templates
    if template.get("id") in ("eerie_object", "document_reveal"):
        fill_color = (230, 20, 20)

    # Draw line 1
    _draw_stroked_text(draw, ax, ay, line1, font, fill_color, stroke_color, stroke_width=6)

    # Draw line 2 (if exists)
    if line2:
        bbox2 = draw.textbbox((0, 0), line2, font=font)
        th2   = bbox2[3] - bbox2[1]
        _draw_stroked_text(
            draw, ax, ay + th2 + 8,
            line2, font, fill_color, stroke_color, stroke_width=6
        )

    return canvas


def _draw_stroked_text(
    draw:         ImageDraw.ImageDraw,
    x:            int,
    y:            int,
    text:         str,
    font:         ImageFont.FreeTypeFont,
    fill:         tuple,
    stroke_color: tuple,
    stroke_width: int = 6,
) -> None:
    """Renders text with a thick stroke outline for visibility on any background."""
    # Draw stroke: text at offset positions
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if abs(dx) + abs(dy) <= stroke_width + 1:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    # Draw main fill
    draw.text((x, y), text, font=font, fill=fill)


def _draw_channel_tag(canvas: Image.Image) -> Image.Image:
    """
    Draws a small semi-transparent channel tag at the bottom-right.
    Very subtle — does not compete with headline text.
    """
    draw     = ImageDraw.Draw(canvas)
    font     = _load_font(26)
    tag_text = "KARMA VAULT STORIES"
    bbox     = draw.textbbox((0, 0), tag_text, font=font)
    tw       = bbox[2] - bbox[0]
    # Position: bottom-right with margin
    x = TW - tw - 28
    y = TH - 40

    # Stroke in near-black
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((x + dx, y + dy), tag_text, font=font, fill=(0, 0, 0))
    draw.text((x, y), tag_text, font=font, fill=(160, 160, 160))
    return canvas


# ─────────────────────────────────────────────
# LAYOUT HELPERS
# ─────────────────────────────────────────────

def _split_headline(words: list[str]) -> tuple[str, str]:
    """Splits headline words across two lines for optimal layout."""
    if len(words) <= 2:
        return " ".join(words), ""
    mid = math.ceil(len(words) / 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def _get_text_region_width(text_pos: str, word_count: int) -> int:
    """Returns target text width in pixels based on position."""
    widths = {
        "top_right":    int(TW * 0.42),
        "bottom_center": int(TW * 0.80),
        "center":       int(TW * 0.75),
        "top_center":   int(TW * 0.78),
    }
    return widths.get(text_pos, int(TW * 0.60))


def _fit_font_size(
    draw:     ImageDraw.ImageDraw,
    text:     str,
    target_w: int,
    min_size: int = 80,
    max_size: int = 260,
) -> int:
    """Binary-searches for the largest font size that fits within target_w."""
    lo, hi = min_size, max_size
    while lo < hi - 2:
        mid  = (lo + hi) // 2
        font = _load_font(mid)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        if tw <= target_w:
            lo = mid
        else:
            hi = mid
    return lo


def _get_text_anchor(text_pos: str, font_size: int, has_second_line: bool) -> tuple[int, int]:
    """
    Returns the (x, y) anchor point for the first line of headline text.
    All coordinates are for 1280×720 canvas.
    """
    margin = 30
    line_h = font_size + 12

    if text_pos == "top_right":
        # Text starts right of center, vertically centered in top half
        x = TW // 2 + 20
        y = max(margin, (TH // 2 - line_h * (2 if has_second_line else 1)) // 2 + 20)

    elif text_pos == "bottom_center":
        # Text centered horizontally, sits above bottom
        x = TW // 2
        y = int(TH * 0.65)

    elif text_pos == "center":
        x = TW // 2
        y = int(TH * 0.38)

    elif text_pos == "top_center":
        x = TW // 2
        y = max(margin + 20, 55)

    else:
        x = margin + 30
        y = margin + 30

    # Center text if position is not top_right (which starts at x)
    return x, y


# ─────────────────────────────────────────────
# TEMPLATE & TEXT HELPERS
# ─────────────────────────────────────────────

def _get_template(template_id: str) -> dict:
    """Returns the template config dict, falling back to first template."""
    for t in THUMBNAIL_TEMPLATES:
        if t["id"] == template_id:
            return t
    return THUMBNAIL_TEMPLATES[0]


def _prepare_thumb_text(ctx: DailyRunContext) -> str:
    """
    Gets thumbnail text from SEO metadata, validating max-word constraint.
    Falls back to generating from story title if missing.
    """
    if ctx.seo_metadata:
        raw = ctx.seo_metadata.get("thumbnail_text", "").strip().upper()
        if raw:
            words = raw.split()[:THUMBNAIL_MAX_WORDS]
            return " ".join(words)

    # Fallback: first 3 words of story title uppercased
    if ctx.selected_story:
        words = ctx.selected_story.title.upper().split()[:3]
        return " ".join(words)

    return "DARK FILE"


def _resize_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop to exactly target_w × target_h."""
    src_w, src_h = img.size
    scale  = max(target_w / src_w, target_h / src_h)
    new_w  = int(src_w * scale)
    new_h  = int(src_h * scale)
    img    = img.resize((new_w, new_h), Image.LANCZOS)
    left   = (new_w - target_w) // 2
    top    = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))

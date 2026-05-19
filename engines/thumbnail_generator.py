"""
engines/thumbnail_generator.py
Karma Vault Stories — Thumbnail Generator Engine
Composites production-ready YouTube thumbnails at 1280×720.
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

# Heavy grading for thumbnail — darker and more contrast than video
_THUMB_CONTRAST   = 1.30
_THUMB_BRIGHTNESS = 0.72
_THUMB_SATURATION = 0.65
_THUMB_VIGNETTE   = 0.62

# ── MASSIVE badge geometry ────────────────────────────────────────────────────
_BADGE_RADIUS = 100          # was 52 → now 100px = ~16% of thumbnail height
_BADGE_X      = 108          # center x
_BADGE_Y      = 108          # center y
_BADGE_COLOR  = (210, 0, 0)  # bright red

# ── High-CTR text colors ──────────────────────────────────────────────────────
_TEXT_COLOR_YELLOW = (255, 230, 0)    # bright yellow — highest YouTube CTR
_TEXT_COLOR_WHITE  = (255, 255, 255)
_TEXT_COLOR_RED    = (255, 30, 30)
_STROKE_COLOR      = (0, 0, 0)
_STROKE_WIDTH      = 10               # thick black stroke for any background


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_thumbnail_generator(ctx: DailyRunContext) -> DailyRunContext:
    log.info(f"Thumbnail generator starting. Template={ctx.thumbnail_template_id}")
    ensure_run_workspace(ctx.run_id)

    template = _get_template(ctx.thumbnail_template_id)
    text     = _prepare_thumb_text(ctx)
    out_path = thumbnail_path(ctx.run_id, "thumbnail.jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Background
    bg_path = _select_background(ctx, template)
    log.info(f"Thumbnail background: {bg_path.name if bg_path else 'procedural'}")

    # Build canvas
    canvas = _build_thumbnail_canvas(bg_path, template, ctx)

    # Composite layers
    canvas = _draw_template_gradient(canvas, template)
    canvas = _draw_badge(canvas)
    canvas = _draw_headline(canvas, text, template)
    canvas = _draw_channel_tag(canvas)

    canvas.save(str(out_path), "JPEG", quality=96, optimize=True)
    ctx.thumbnail_path = str(out_path)
    log.info(
        f"Thumbnail saved: {out_path.name} "
        f"({out_path.stat().st_size // 1024}KB) | Text: '{text}'"
    )

    ctx.mark_stage("thumbnail_generator")
    return ctx


# ─────────────────────────────────────────────
# BACKGROUND SELECTION
# ─────────────────────────────────────────────

def _select_background(ctx: DailyRunContext, template: dict) -> Optional[Path]:
    scene_assets = ctx.scene_assets or []
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
        horror_scenes = [
            s for s in usable
            if s.get("horror_grading") and s.get("part_id") in ("climax", "escalation")
        ]
        hook_scenes = [s for s in usable if s.get("part_id") == "hook"]
        pool   = horror_scenes or hook_scenes or usable
        chosen = random.choice(pool)
        return Path(chosen["asset_path"])

    log.info("No scene assets — generating AI thumbnail background.")
    ai_path = _generate_ai_thumb_background(ctx)
    return ai_path


def _generate_ai_thumb_background(ctx: DailyRunContext) -> Optional[Path]:
    from engines.image_generator import generate_ai_image

    pillar  = (ctx.selected_story.pillar if ctx.selected_story
               else ContentPillar.TRUE_SHOCKING.value)
    country = (ctx.selected_story.country if ctx.selected_story else "Unknown")

    pillar_prompts = {
        ContentPillar.PARANORMAL.value:
            "dark corridor with distant eerie light, mist at floor level",
        ContentPillar.HUMAN_BETRAYAL.value:
            "lone silhouette in doorway of dark room, dramatic back lighting",
        ContentPillar.MYSTERY_DISAPPEARANCE.value:
            "empty dark road at night, single distant light, dense fog",
        ContentPillar.TRUE_SHOCKING.value:
            "dramatic dark cinematic landscape, deep shadows, solitary figure",
        ContentPillar.HISTORICAL_DARK.value:
            "dark archive room with single overhead light, dust in air",
        ContentPillar.AI_HORROR.value:
            "dark server room with cold blue glow, ominous machinery in shadows",
    }
    prompt = pillar_prompts.get(
        pillar,
        "dark dramatic environment, deep shadows, cinematic composition"
    )

    ai_path = thumbnail_path(ctx.run_id, "thumb_bg_ai.jpg")
    try:
        if generate_ai_image(prompt, ai_path, pillar=pillar, horror_mode=True):
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
    if bg_path and bg_path.exists():
        try:
            img = Image.open(str(bg_path)).convert("RGB")
            img = _resize_crop(img, TW, TH)
            return _apply_thumbnail_grading(img, template)
        except Exception as exc:
            log.warning(f"Could not load background {bg_path}: {exc}")
    return _generate_procedural_background(ctx, template)


def _apply_thumbnail_grading(img: Image.Image, template: dict) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(_THUMB_CONTRAST)
    img = ImageEnhance.Brightness(img).enhance(_THUMB_BRIGHTNESS)
    img = ImageEnhance.Color(img).enhance(_THUMB_SATURATION)

    arr = np.array(img, dtype=np.float32)

    # Strong radial vignette
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    dist  = np.sqrt(((X - w/2)/(w/2))**2 + ((Y - h/2)/(h/2))**2)
    fade  = np.clip((dist - 0.25)/0.70, 0, 1) ** 2.2 * _THUMB_VIGNETTE
    arr   = arr * (1 - fade)[:, :, np.newaxis]

    # Template tint
    bg_style = template.get("bg_style", "dark_gradient")
    if bg_style == "blood_red":
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.35, 0, 255)
        arr[:, :, 1] = arr[:, :, 1] * 0.72
        arr[:, :, 2] = arr[:, :, 2] * 0.68
    elif bg_style == "fog_dark":
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.18, 0, 255)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _generate_procedural_background(
    ctx:      DailyRunContext,
    template: dict,
) -> Image.Image:
    bg_style = template.get("bg_style", "dark_gradient")
    arr = np.zeros((TH, TW, 3), dtype=np.float32)
    pillar = (ctx.selected_story.pillar if ctx.selected_story
              else ContentPillar.TRUE_SHOCKING.value)

    if bg_style == "blood_red":
        for y in range(TH):
            fade = (y / TH) ** 1.4
            arr[y, :, 0] = 30 + fade * 65
            arr[y, :, 1] = 2  + fade * 6
            arr[y, :, 2] = 2  + fade * 6
    elif bg_style == "paper_aged":
        base = 18
        arr[:, :, 0] = base + 9
        arr[:, :, 1] = base + 5
        arr[:, :, 2] = base
        arr += np.random.randn(TH, TW, 3) * 5
    else:
        for y in range(TH):
            fade = (y / TH) * 0.75
            arr[y, :, 0] = 6  + fade * 14
            arr[y, :, 1] = 3  + fade * 8
            arr[y, :, 2] = 9  + fade * 20

    arr += np.random.randn(TH, TW, 3) * 3
    arr  = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


# ─────────────────────────────────────────────
# COMPOSITING ELEMENTS
# ─────────────────────────────────────────────

def _draw_template_gradient(canvas: Image.Image, template: dict) -> Image.Image:
    """Darkens the text region so headline is always readable."""
    text_pos = template.get("text_position", "top_right")
    arr      = np.array(canvas, dtype=np.float32)

    if text_pos == "top_right":
        for x in range(TW // 2, TW):
            t = (x - TW // 2) / (TW // 2)
            arr[:TH // 2, x, :] *= max(0.20, 1.0 - t * 0.72)
    elif text_pos == "bottom_center":
        for y in range(int(TH * 0.55), TH):
            t = (y - TH * 0.55) / (TH * 0.45)
            arr[y, :, :] *= max(0.10, 1.0 - t * 0.85)
    elif text_pos == "center":
        arr[int(TH*0.30):int(TH*0.70), :, :] *= 0.38
    elif text_pos == "top_center":
        for y in range(int(TH * 0.45)):
            t = 1.0 - (y / (TH * 0.45))
            arr[y, :, :] *= max(0.15, 1.0 - t * 0.80)

    # Always darken the bottom strip for channel tag readability
    arr[int(TH * 0.88):, :, :] *= 0.40

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _draw_badge(canvas: Image.Image) -> Image.Image:
    """
    Draws a MASSIVE +18 badge in the top-left corner.
    Radius 100px on 1280x720 = ~14% of frame height — impossible to miss.
    Outer black ring → red fill → white inner ring → shadow text → white text.
    """
    draw   = ImageDraw.Draw(canvas)
    cx, cy = _BADGE_X, _BADGE_Y
    r      = _BADGE_RADIUS

    # Outer black shadow ring (gives 3D lift effect)
    draw.ellipse(
        [cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7],
        fill=(0, 0, 0),
    )

    # Main red circle
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=_BADGE_COLOR,
    )

    # White inner ring for polish
    draw.ellipse(
        [cx - r + 7, cy - r + 7, cx + r - 7, cy + r - 7],
        outline=(255, 255, 255), width=4,
    )

    font_plus = _load_font(52)
    font_num  = _load_font(76)

    plus_text = "+"
    num_text  = "18"

    bbox_plus = draw.textbbox((0, 0), plus_text, font=font_plus)
    bbox_num  = draw.textbbox((0, 0), num_text,  font=font_num)
    pw = bbox_plus[2] - bbox_plus[0]
    nw = bbox_num[2]  - bbox_num[0]
    ph = bbox_plus[3] - bbox_plus[1]
    nh = bbox_num[3]  - bbox_num[1]

    total_w = pw + nw - 4
    sx = cx - total_w // 2
    sy = cy - nh // 2

    # Black shadow pass (multiple offsets for depth)
    for dx, dy in [(-3, 3), (3, 3), (0, 4), (-3, -1), (3, -1)]:
        draw.text(
            (sx + dx, sy + (nh - ph) // 2 + dy),
            plus_text, font=font_plus, fill=(0, 0, 0),
        )
        draw.text(
            (sx + pw - 4 + dx, sy + dy),
            num_text, font=font_num, fill=(0, 0, 0),
        )

    # White fill
    draw.text(
        (sx, sy + (nh - ph) // 2),
        plus_text, font=font_plus, fill=(255, 255, 255),
    )
    draw.text(
        (sx + pw - 4, sy),
        num_text, font=font_num, fill=(255, 255, 255),
    )

    return canvas


def _draw_headline(
    canvas:   Image.Image,
    text:     str,
    template: dict,
) -> Image.Image:
    """
    Renders the headline with maximum CTR impact:
    - Auto-scales font to fill the text region width
    - Bright yellow primary color (highest CTR on dark backgrounds)
    - 10px black stroke for readability on any background
    - ALL CAPS, max 4 words
    """
    if not text.strip():
        return canvas

    draw     = ImageDraw.Draw(canvas)
    text_pos = template.get("text_position", "top_right")
    words    = text.strip().upper().split()[:THUMBNAIL_MAX_WORDS]
    line1, line2 = _split_headline(words)

    target_w  = _get_text_region_width(text_pos, len(words))
    font_size = _fit_font_size(draw, line1, target_w, min_size=90, max_size=320)
    font      = _load_font(font_size)

    ax, ay = _get_text_anchor(text_pos, font_size, bool(line2))

    # Yellow for most templates, white for silhouette (on very dark backgrounds)
    fill_color = (
        _TEXT_COLOR_WHITE
        if template.get("id") == "silhouette"
        else _TEXT_COLOR_YELLOW
    )

    # Draw line 1
    _draw_stroked_text(draw, ax, ay, line1, font, fill_color, _STROKE_COLOR, _STROKE_WIDTH)

    # Draw line 2 (if exists)
    if line2:
        bbox2 = draw.textbbox((0, 0), line2, font=font)
        line_h = bbox2[3] - bbox2[1]
        _draw_stroked_text(
            draw, ax, ay + line_h + 10,
            line2, font, fill_color, _STROKE_COLOR, _STROKE_WIDTH,
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
    stroke_width: int = 10,
) -> None:
    """Renders text with a thick black stroke for readability on any background."""
    for dx in range(-stroke_width, stroke_width + 1, 2):
        for dy in range(-stroke_width, stroke_width + 1, 2):
            if dx*dx + dy*dy <= stroke_width * stroke_width * 1.2:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_channel_tag(canvas: Image.Image) -> Image.Image:
    """Subtle channel watermark at bottom-right."""
    draw     = ImageDraw.Draw(canvas)
    font     = _load_font(28)
    tag_text = "KARMA VAULT STORIES"
    bbox     = draw.textbbox((0, 0), tag_text, font=font)
    tw       = bbox[2] - bbox[0]
    x = TW - tw - 28
    y = TH - 42
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((x + dx, y + dy), tag_text, font=font, fill=(0, 0, 0))
    draw.text((x, y), tag_text, font=font, fill=(170, 170, 170))
    return canvas


# ─────────────────────────────────────────────
# LAYOUT HELPERS
# ─────────────────────────────────────────────

def _split_headline(words: list[str]) -> tuple[str, str]:
    if len(words) <= 2:
        return " ".join(words), ""
    mid = math.ceil(len(words) / 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def _get_text_region_width(text_pos: str, word_count: int) -> int:
    widths = {
        "top_right":     int(TW * 0.44),
        "bottom_center": int(TW * 0.82),
        "center":        int(TW * 0.78),
        "top_center":    int(TW * 0.80),
    }
    return widths.get(text_pos, int(TW * 0.62))


def _fit_font_size(
    draw:     ImageDraw.ImageDraw,
    text:     str,
    target_w: int,
    min_size: int = 90,
    max_size: int = 320,
) -> int:
    lo, hi = min_size, max_size
    while lo < hi - 2:
        mid  = (lo + hi) // 2
        font = _load_font(mid)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= target_w:
            lo = mid
        else:
            hi = mid
    return lo


def _get_text_anchor(text_pos: str, font_size: int, has_second_line: bool) -> tuple[int, int]:
    margin = 30
    line_h = font_size + 14

    if text_pos == "top_right":
        x = TW // 2 + 15
        y = max(margin, (TH // 2 - line_h * (2 if has_second_line else 1)) // 2 + 25)
    elif text_pos == "bottom_center":
        x = TW // 2
        y = int(TH * 0.62)
    elif text_pos == "center":
        x = TW // 2
        y = int(TH * 0.36)
    elif text_pos == "top_center":
        x = TW // 2
        y = max(margin + 25, 60)
    else:
        x = margin + 35
        y = margin + 35

    return x, y


# ─────────────────────────────────────────────
# TEMPLATE & TEXT HELPERS
# ─────────────────────────────────────────────

def _get_template(template_id: str) -> dict:
    for t in THUMBNAIL_TEMPLATES:
        if t["id"] == template_id:
            return t
    return THUMBNAIL_TEMPLATES[0]


def _prepare_thumb_text(ctx: DailyRunContext) -> str:
    if ctx.seo_metadata:
        raw = ctx.seo_metadata.get("thumbnail_text", "").strip().upper()
        if raw:
            return " ".join(raw.split()[:THUMBNAIL_MAX_WORDS])
    if ctx.selected_story:
        return " ".join(ctx.selected_story.title.upper().split()[:3])
    return "DARK FILE"


def _resize_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    scale  = max(target_w / src_w, target_h / src_h)
    new_w  = int(src_w * scale)
    new_h  = int(src_h * scale)
    img    = img.resize((new_w, new_h), Image.LANCZOS)
    left   = (new_w - target_w) // 2
    top    = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))

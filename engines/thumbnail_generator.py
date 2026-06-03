"""
engines/thumbnail_generator.py
Karma Vault Stories — Thumbnail Generator Engine  (Phase B upgraded)

Changes vs previous version:
  1. _select_background queries Pexels for a REAL dark horror/mystery stock photo
     instead of ever producing the grey gradient placeholder.
     Fallback chain: Pexels → Leonardo → Stability → GetIMG → procedural (last resort)
  2. _generate_ctr_hook_phrase uses the LLM to produce short, psychologically
     optimised hook phrases (e.g. "HE LIED", "THEY WATCHED", "NEVER OPEN IT")
     tuned to the story's pillar and key shock moment.
     Falls back to a curated pillar-specific phrase pool if LLM is unavailable.
"""

from __future__ import annotations

import random
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

from config.settings import (
    PEXELS_API_KEY, GETIMG_API_KEY, FONTS_DIR,
)
from config.constants import (
    THUMBNAIL_TEMPLATES, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT,
    THUMBNAIL_MAX_WORDS, ContentPillar,
    VISUAL_COLORS, AssetCategory,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import thumbnail_path, ensure_run_workspace
from utils.api_client import (
    http_get_json, download_image, call_writing_model,
)

log = get_logger(__name__)

TW = THUMBNAIL_WIDTH    # 1280
TH = THUMBNAIL_HEIGHT   # 720

_THUMB_CONTRAST   = 1.35
_THUMB_BRIGHTNESS = 0.60
_THUMB_SATURATION = 0.58

_BADGE_RADIUS = 100
_BADGE_X      = 108
_BADGE_Y      = 108
_BADGE_COLOR  = (210, 0, 0)

_TEXT_YELLOW  = (255, 230, 0)
_TEXT_WHITE   = (255, 255, 255)
_TEXT_RED     = (255, 30, 30)
_STROKE_COLOR = (0, 0, 0)
_STROKE_WIDTH = 10


# ─────────────────────────────────────────────
# PILLAR-SPECIFIC PEXELS BACKGROUND QUERIES
# ─────────────────────────────────────────────

_PEXELS_THUMB_QUERIES: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "dark abandoned house horror", "eerie foggy cemetery night",
        "dark haunted corridor shadows", "spooky fog forest night",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "silhouette person dark dramatic", "dark noir shadows dramatic",
        "dark rain window alone", "shadows dramatic person",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "dark empty road fog night", "abandoned dark building exterior",
        "misty dark forest path", "dark crime scene atmosphere",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "dark dramatic sky storm", "emergency lights night rain dark",
        "dark wet road night", "dark atmospheric scene night",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "dark vintage library interior", "old abandoned dark building",
        "dark aged interior dramatic", "antique dark room shadows",
    ],
    ContentPillar.AI_HORROR.value: [
        "dark server room blue light", "dramatic dark technology room",
        "dark digital abstract horror", "computer screen dark room",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "dramatic person shadow portrait", "noir dark portrait dramatic",
        "dark window silhouette night", "dark identity mystery portrait",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "dark screen glow room night", "hands typing dark keyboard",
        "dark room screen glow person", "phone dark room night",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "dark alley night horror atmosphere", "dark city street fog night",
        "abandoned urban building night", "horror dark urban environment",
    ],
    ContentPillar.TRUE_SHOCKING.value: [
        "dark dramatic crime investigation", "dark dramatic portrait shadow",
        "dark intense cinematic scene", "dramatic dark atmosphere scene",
    ],
}

_PEXELS_THUMB_DEFAULT = [
    "dark atmospheric horror mystery",
    "dark dramatic cinematic scene",
    "dark shadows horror atmosphere",
    "fog dark night dramatic",
]


# ─────────────────────────────────────────────
# PSYCHOLOGICAL CTR HOOK PHRASE POOLS
# (Used as LLM fallback — battle-tested phrases)
# ─────────────────────────────────────────────

_CTR_PHRASES: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "IT WAS REAL", "THEY SAW IT", "NEVER EXPLAINED",
        "IT CAME BACK", "DON'T WATCH ALONE", "IT FOLLOWED THEM",
        "NO ONE BELIEVED HER", "THE LAST DOOR",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "HE LIED", "SHE KNEW", "THEY ALL KNEW",
        "TRUST NO ONE", "CLOSEST ENEMY", "YEARS OF LIES",
        "THE REAL STORY", "NOBODY TOLD YOU",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "NEVER FOUND", "GONE FOREVER", "NO TRACE LEFT",
        "THEY VANISHED", "CASE UNSOLVED", "WHAT REALLY HAPPENED",
        "HIDDEN FOR YEARS", "THEY KNEW MORE",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "NOT AN ACCIDENT", "THEY COVERED IT UP",
        "THE TRUTH HURTS", "WHAT THEY HID",
        "SOMEONE KNEW", "IT WASN'T RANDOM",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "BURIED FOR DECADES", "THEY ERASED IT",
        "HISTORY LIED", "THE HIDDEN FILE",
        "CLASSIFIED UNTIL NOW", "THEY HID THIS",
    ],
    ContentPillar.AI_HORROR.value: [
        "IT BECAME AWARE", "THE AI SAW YOU",
        "THEY LET IT RUN", "MACHINE GONE WRONG",
        "IT LEARNED TOO FAST", "NO ONE STOPPED IT",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "TWO LIVES ONE FACE", "NOBODY SUSPECTED",
        "DIFFERENT PERSON ENTIRELY", "SHE WAS HIDING THIS",
        "HIS OTHER LIFE", "NEVER SUPPOSED TO SEE",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "HE CONFESSED ONLINE", "SHE POSTED EVERYTHING",
        "THE POST CHANGED EVERYTHING", "INTERNET FOUND HIM",
        "THEY EXPOSED THEMSELVES", "IT WENT VIRAL THEN",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "IT'S ACTUALLY REAL", "NOT JUST A LEGEND",
        "THEY SAW IT TOO", "HAPPENS EVERY YEAR",
        "LOCALS WON'T SAY", "NEVER GO THERE",
    ],
    ContentPillar.TRUE_SHOCKING.value: [
        "18+ TRUE STORY", "CRAZY TRUE STORY",
        "HE WAS WATCHING", "THEY WATCHED",
        "IT NEVER STOPPED", "NEVER OPEN IT",
    ],
}

_CTR_GENERIC = [
    "YOU NEED THIS", "WATCH ALONE", "18+ ONLY",
    "CRAZY TRUE STORY", "THEY HID THIS",
    "THE DARK FILE", "NEVER SUPPOSED TO SEE",
]


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_thumbnail_generator(ctx: DailyRunContext) -> DailyRunContext:
    log.info(f"Thumbnail generator starting. Template={ctx.thumbnail_template_id}")
    ensure_run_workspace(ctx.run_id)

    template = _get_template(ctx.thumbnail_template_id)
    pillar   = ctx.selected_story.pillar if ctx.selected_story else ContentPillar.TRUE_SHOCKING.value

    # Generate psychological CTR hook phrase
    hook_text = _generate_ctr_hook_phrase(ctx)
    log.info(f"CTR hook phrase: '{hook_text}'")

    out_path = thumbnail_path(ctx.run_id, "thumbnail.jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Get background — real stock photo first
    bg_path = _select_background(ctx, template, pillar)
    log.info(f"Thumbnail background: {bg_path.name if bg_path else 'procedural gradient'}")

    # Composite
    canvas = _build_canvas(bg_path, template, ctx)
    canvas = _apply_grading(canvas, template, pillar)
    canvas = _draw_gradient_overlays(canvas, template)
    canvas = _draw_impact_overlay(canvas, template)
    canvas = _draw_badge(canvas)
    canvas = _draw_headline(canvas, hook_text, template)
    canvas = _draw_channel_tag(canvas)

    canvas.save(str(out_path), "JPEG", quality=96, optimize=True)
    ctx.thumbnail_path = str(out_path)
    log.info(f"Thumbnail saved: {out_path.name} ({out_path.stat().st_size // 1024}KB)")

    ctx.mark_stage("thumbnail_generator")
    return ctx


# ─────────────────────────────────────────────
# PSYCHOLOGICAL CTR HOOK PHRASE GENERATOR
# ─────────────────────────────────────────────

def _generate_ctr_hook_phrase(ctx: DailyRunContext) -> str:
    """
    Generates a 2–4 word psychological hook phrase using the LLM.
    Tuned to the story's pillar and key shock moment.
    Falls back to curated pillar-specific pool if LLM unavailable.
    """
    pillar     = ctx.selected_story.pillar if ctx.selected_story else ContentPillar.TRUE_SHOCKING.value
    story_title = ctx.selected_story.title  if ctx.selected_story else ""
    blueprint  = ctx.script_blueprint or {}

    # Get the key shock moment from the blueprint
    shock_captions = blueprint.get("shock_captions", [])
    key_moment = ""
    if shock_captions:
        key_moment = shock_captions[0].get("text", "") if shock_captions else ""
    if not key_moment:
        parts = blueprint.get("parts", [])
        climax_parts = [p for p in parts if p.get("part_id") == "climax"]
        if climax_parts:
            key_moment = climax_parts[0].get("narration", "")[:80]

    system_prompt = (
        "You write 2–4 word YouTube thumbnail hook phrases for a dark documentary channel. "
        "Rules:\n"
        "- Return ONLY the hook phrase. Nothing else. No punctuation at the end.\n"
        "- Maximum 4 words. ALL CAPS.\n"
        "- Must create an irresistible curiosity gap that forces viewers to click.\n"
        "- Use these proven psychological triggers: "
        "REVELATION (HE LIED), FEAR (IT CAME BACK), SECRECY (THEY HID THIS), "
        "SHOCK (NOT AN ACCIDENT), URGENCY (WATCH ALONE).\n"
        "- NEVER use: DARK, SECRET, MYSTERY, STORY, VIDEO, WATCH, THIS, TRUE.\n"
        "- The phrase must feel like a discovery, not a description.\n"
        "- Example good outputs: HE WAS THERE | THEY ALL KNEW | NEVER FOUND | "
        "IT WASN'T RANDOM | SHE KNEW EVERYTHING | BURIED FOR YEARS"
    )
    user_prompt = (
        f"Story title: {story_title[:80]}\n"
        f"Genre: dark documentary, {pillar.replace('_', ' ')}\n"
        f"Key moment: {key_moment[:100]}\n\n"
        f"Generate the perfect 2-4 word thumbnail hook phrase:"
    )

    try:
        raw = call_writing_model(
            system_prompt, user_prompt,
            max_tokens=20, temperature=0.9, json_output=False,
        )
        phrase = raw.strip().upper()[:30]
        # Validate: 2–4 words, no junk
        words = phrase.split()
        if 2 <= len(words) <= 5:
            log.debug(f"LLM CTR phrase: '{phrase}'")
            return phrase
        log.debug(f"LLM phrase '{phrase}' outside word range — using fallback pool.")
    except Exception as exc:
        log.debug(f"CTR phrase LLM call failed: {exc}")

    # Fallback: curated pillar-specific pool
    phrases = _CTR_PHRASES.get(pillar, _CTR_GENERIC)
    chosen  = random.choice(phrases)
    log.debug(f"Fallback CTR phrase: '{chosen}'")
    return chosen


# ─────────────────────────────────────────────
# BACKGROUND SELECTION — Pexels-first
# ─────────────────────────────────────────────

def _select_background(
    ctx:      DailyRunContext,
    template: dict,
    pillar:   str,
) -> Optional[Path]:
    """
    Background selection priority:
    1. Pexels stock photo (dark cinematic, pillar-matched query)
    2. Scene assets (if a horror-graded stock photo exists from this run)
    3. AI generation (Leonardo → Stability → GetIMG)
    4. Procedural gradient (absolute last resort — should almost never reach here)
    """
    # ── 1. Pexels stock photo ─────────────────────────────────────
    pexels_bg = _fetch_pexels_background(ctx, pillar)
    if pexels_bg:
        return pexels_bg

    # ── 2. Existing scene asset ───────────────────────────────────
    for scene in (ctx.scene_assets or []):
        ap = scene.get("asset_path", "")
        if (ap and Path(ap).exists()
                and scene.get("asset_type") in (
                    AssetCategory.STOCK_PHOTO.value, "stock_photo", "ai_still"
                )
                and scene.get("horror_grading")
                and scene.get("part_id") in ("climax", "escalation")):
            return Path(ap)

    # ── 3. AI generation ──────────────────────────────────────────
    return _generate_ai_background(ctx, pillar)


def _fetch_pexels_background(ctx: DailyRunContext, pillar: str) -> Optional[Path]:
    """
    Downloads a dark cinematic stock photo from Pexels for the thumbnail background.
    Picks a query from the pillar-specific list, slightly randomised each run
    to avoid identical thumbnails on consecutive days.
    """
    if not PEXELS_API_KEY:
        return None

    queries = list(_PEXELS_THUMB_QUERIES.get(pillar, _PEXELS_THUMB_DEFAULT))
    random.shuffle(queries)

    for query in queries[:3]:
        try:
            resp = http_get_json(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={
                    "query":       query,
                    "per_page":    5,
                    "orientation": "landscape",
                    "size":        "large",
                },
                timeout=15,
            )
            photos = resp.get("photos", [])
            if not photos:
                continue

            # Prefer wide photos with dark/moody content
            for photo in photos[:3]:
                src  = photo.get("src", {})
                url  = src.get("large2x") or src.get("large") or src.get("original")
                if not url:
                    continue
                w = photo.get("width", 0)
                h = photo.get("height", 0)
                if w < 1200 or h < 600:
                    continue

                dest = thumbnail_path(ctx.run_id, f"thumb_pexels_{photo.get('id','0')}.jpg")
                dest.parent.mkdir(parents=True, exist_ok=True)
                ok = download_image(url, str(dest), timeout=20)
                if ok and dest.exists() and dest.stat().st_size > 50_000:
                    log.info(f"Pexels background: '{query}' → {dest.name}")
                    return dest

        except Exception as exc:
            log.debug(f"Pexels background fetch failed for '{query[:40]}': {exc}")

    return None


def _generate_ai_background(ctx: DailyRunContext, pillar: str) -> Optional[Path]:
    """AI-generated background fallback (Leonardo → Stability → GetIMG)."""
    try:
        from engines.image_generator import generate_ai_image
        prompts = _PEXELS_THUMB_QUERIES.get(pillar, _PEXELS_THUMB_DEFAULT)
        prompt  = random.choice(prompts) + ", cinematic, no people, ultra HD"
        out     = thumbnail_path(ctx.run_id, "thumb_bg_ai.jpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        if generate_ai_image(prompt, out, pillar=pillar, horror_mode=True):
            log.info(f"AI thumbnail background generated: {out.name}")
            return out
    except Exception as exc:
        log.warning(f"AI thumbnail background failed: {exc}")
    return None


# ─────────────────────────────────────────────
# CANVAS BUILDING
# ─────────────────────────────────────────────

def _build_canvas(
    bg_path:  Optional[Path],
    template: dict,
    ctx:      DailyRunContext,
) -> Image.Image:
    if bg_path and bg_path.exists():
        try:
            img = Image.open(str(bg_path)).convert("RGB")
            return _resize_crop(img, TW, TH)
        except Exception as exc:
            log.warning(f"Background load failed ({bg_path}): {exc}")
    return _procedural_gradient(ctx, template)


def _procedural_gradient(ctx: DailyRunContext, template: dict) -> Image.Image:
    """Deep dark gradient — only reached if ALL image sources fail."""
    arr   = np.zeros((TH, TW, 3), dtype=np.float32)
    style = template.get("bg_style", "dark_gradient")
    for y in range(TH):
        fade = (y / TH) ** 1.6
        if style == "blood_red":
            arr[y, :, 0] = 12 + fade * 60
            arr[y, :, 1] = 0  + fade * 4
            arr[y, :, 2] = 0  + fade * 4
        else:
            arr[y, :, 0] = 4  + fade * 16
            arr[y, :, 1] = 2  + fade * 8
            arr[y, :, 2] = 8  + fade * 24
    arr += np.random.randn(TH, TW, 3) * 3
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _apply_grading(
    canvas:   Image.Image,
    template: dict,
    pillar:   str,
) -> Image.Image:
    canvas = ImageEnhance.Contrast(canvas).enhance(_THUMB_CONTRAST)
    canvas = ImageEnhance.Brightness(canvas).enhance(_THUMB_BRIGHTNESS)
    canvas = ImageEnhance.Color(canvas).enhance(_THUMB_SATURATION)

    arr = np.array(canvas, dtype=np.float32)

    # Radial vignette
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt(((X - w/2)/(w/2))**2 + ((Y - h/2)/(h/2))**2)
    fade = np.clip((dist - 0.22) / 0.64, 0, 1) ** 2.4 * 0.70
    arr  = arr * (1 - fade)[:, :, np.newaxis]

    # Cool shadow grade (teal in darks = cinematic Netflix look)
    lum   = arr.mean(axis=2, keepdims=True) / 255.0
    shad  = (1.0 - lum) ** 2
    arr[:, :, 2] = np.clip(arr[:, :, 2] + shad[:, :, 0] * 20, 0, 255)
    arr[:, :, 0] = np.clip(arr[:, :, 0] + shad[:, :, 0] * 8,  0, 255)

    # Pillar-specific tint
    bg_style = template.get("bg_style", "")
    if bg_style == "blood_red" or pillar in (
        ContentPillar.TRUE_SHOCKING.value,
        ContentPillar.DISTURBING_ACCIDENTS.value,
    ):
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.35, 0, 255)
        arr[:, :, 1] = arr[:, :, 1] * 0.72
        arr[:, :, 2] = arr[:, :, 2] * 0.68

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ─────────────────────────────────────────────
# OVERLAY ELEMENTS
# ─────────────────────────────────────────────

def _draw_gradient_overlays(canvas: Image.Image, template: dict) -> Image.Image:
    """Dark gradient on text region so headline pops regardless of bg content."""
    arr  = np.array(canvas, dtype=np.float32)
    h, w = arr.shape[:2]
    pos  = template.get("text_position", "top_right")

    if pos == "top_right":
        for x in range(w // 2, w):
            t = (x - w // 2) / (w // 2)
            arr[:int(h * 0.65), x, :] *= max(0.18, 1.0 - t * 0.75)
    elif pos == "bottom_center":
        for y in range(int(h * 0.52), h):
            t = (y - h * 0.52) / (h * 0.48)
            arr[y, :, :] *= max(0.08, 1.0 - t * 0.88)
    elif pos == "center":
        arr[int(h*0.28):int(h*0.72), :, :] *= 0.32
    elif pos == "top_center":
        for y in range(int(h * 0.50)):
            t = 1.0 - (y / (h * 0.50))
            arr[y, :, :] *= max(0.12, 1.0 - t * 0.84)

    arr[int(h * 0.86):, :, :] *= 0.35
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _draw_impact_overlay(canvas: Image.Image, template: dict) -> Image.Image:
    """Diagonal red accent + bottom bar — adds urgency and visual energy."""
    arr  = np.array(canvas, dtype=np.float32)
    h, w = arr.shape[:2]

    # Bottom-of-frame darkness bar
    bar_h = int(h * 0.38)
    for y in range(h - bar_h, h):
        t = ((y - (h - bar_h)) / bar_h) ** 1.5
        arr[y, :, :] *= (1.0 - t * 0.84)

    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    draw   = ImageDraw.Draw(canvas)
    pos    = template.get("text_position", "top_right")

    # Red corner triangle accent
    if pos == "top_right":
        draw.polygon([(0, 0), (22, 0), (0, h // 3)], fill=(185, 0, 0))
    else:
        draw.polygon([(0, 0), (64, 0), (0, 88)], fill=(185, 0, 0))

    # Thin red horizontal rule above text zone
    if pos == "bottom_center":
        y_rule = int(h * 0.58)
        draw.line([(int(w * 0.04), y_rule), (int(w * 0.96), y_rule)],
                  fill=(195, 0, 0), width=3)

    return canvas


def _draw_badge(canvas: Image.Image) -> Image.Image:
    """Massive +18 badge — radius 100px, impossible to miss on any feed."""
    draw   = ImageDraw.Draw(canvas)
    cx, cy = _BADGE_X, _BADGE_Y
    r      = _BADGE_RADIUS

    draw.ellipse([cx-r-7, cy-r-7, cx+r+7, cy+r+7], fill=(0, 0, 0))
    draw.ellipse([cx-r,   cy-r,   cx+r,   cy+r],   fill=_BADGE_COLOR)
    draw.ellipse([cx-r+7, cy-r+7, cx+r-7, cy+r-7], outline=(255, 255, 255), width=4)

    font_plus = _load_font(52)
    font_num  = _load_font(76)
    plus_text = "+"
    num_text  = "18"

    bp  = draw.textbbox((0, 0), plus_text, font=font_plus)
    bn  = draw.textbbox((0, 0), num_text,  font=font_num)
    pw  = bp[2] - bp[0];  ph = bp[3] - bp[1]
    nw  = bn[2] - bn[0];  nh = bn[3] - bn[1]
    sx  = cx - (pw + nw - 4) // 2
    sy  = cy - nh // 2

    for dx, dy in [(-3, 3), (3, 3), (0, 4), (0, -1)]:
        draw.text((sx + dx,        sy + (nh - ph) // 2 + dy), plus_text, font=font_plus, fill=(0, 0, 0))
        draw.text((sx + pw - 4 + dx, sy + dy),                num_text,  font=font_num,  fill=(0, 0, 0))
    draw.text((sx,            sy + (nh - ph) // 2), plus_text, font=font_plus, fill=(255, 255, 255))
    draw.text((sx + pw - 4,   sy),                  num_text,  font=font_num,  fill=(255, 255, 255))

    return canvas


def _draw_headline(
    canvas:   Image.Image,
    text:     str,
    template: dict,
) -> Image.Image:
    """
    Renders the psychological CTR hook phrase.
    - Auto-fits font to fill 45–82% of frame width (depending on template)
    - Bright yellow fill with 10px black stroke (maximum contrast on any background)
    - ALL CAPS, max 4 words, asymmetric positioning per template
    """
    if not text.strip():
        return canvas

    draw    = ImageDraw.Draw(canvas)
    words   = text.strip().upper().split()[:THUMBNAIL_MAX_WORDS]
    line1, line2 = _split_headline(words)
    pos     = template.get("text_position", "top_right")
    fill    = _TEXT_WHITE if template.get("id") == "silhouette" else _TEXT_YELLOW

    target_w = _region_width(pos)
    fsize    = _fit_font(draw, line1, target_w)
    font     = _load_font(fsize)
    ax, ay   = _anchor(pos, fsize, bool(line2))

    _stroked_text(draw, ax, ay, line1, font, fill, _STROKE_COLOR, _STROKE_WIDTH)
    if line2:
        b2 = draw.textbbox((0, 0), line2, font=font)
        lh = b2[3] - b2[1]
        _stroked_text(draw, ax, ay + lh + 10, line2, font, fill, _STROKE_COLOR, _STROKE_WIDTH)

    return canvas


def _stroked_text(
    draw:  ImageDraw.ImageDraw,
    x: int, y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    stroke: tuple,
    width: int,
) -> None:
    for dx in range(-width, width + 1, 2):
        for dy in range(-width, width + 1, 2):
            if dx*dx + dy*dy <= width * width * 1.2:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_channel_tag(canvas: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(canvas)
    font = _load_font(26)
    tag  = "KARMA VAULT STORIES"
    bbox = draw.textbbox((0, 0), tag, font=font)
    tw   = bbox[2] - bbox[0]
    x, y = TW - tw - 24, TH - 40
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((x + dx, y + dy), tag, font=font, fill=(0, 0, 0))
    draw.text((x, y), tag, font=font, fill=(165, 165, 165))
    return canvas


# ─────────────────────────────────────────────
# LAYOUT HELPERS
# ─────────────────────────────────────────────

def _split_headline(words: list[str]) -> tuple[str, str]:
    if len(words) <= 2:
        return " ".join(words), ""
    mid = math.ceil(len(words) / 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def _region_width(pos: str) -> int:
    return {
        "top_right":     int(TW * 0.44),
        "bottom_center": int(TW * 0.82),
        "center":        int(TW * 0.80),
        "top_center":    int(TW * 0.82),
    }.get(pos, int(TW * 0.60))


def _fit_font(
    draw:     ImageDraw.ImageDraw,
    text:     str,
    target_w: int,
    lo:       int = 90,
    hi:       int = 320,
) -> int:
    while lo < hi - 2:
        mid  = (lo + hi) // 2
        bbox = draw.textbbox((0, 0), text, font=_load_font(mid))
        if bbox[2] - bbox[0] <= target_w:
            lo = mid
        else:
            hi = mid
    return lo


def _anchor(pos: str, fsize: int, two_lines: bool) -> tuple[int, int]:
    lh = fsize + 14
    margin = 30
    if pos == "top_right":
        x = TW // 2 + 15
        y = max(margin, (TH // 2 - lh * (2 if two_lines else 1)) // 2 + 30)
    elif pos == "bottom_center":
        x = TW // 2
        y = int(TH * 0.60)
    elif pos == "center":
        x = TW // 2
        y = int(TH * 0.34)
    elif pos == "top_center":
        x = TW // 2
        y = max(margin + 30, 65)
    else:
        x = margin + 30
        y = margin + 30
    return x, y


# ─────────────────────────────────────────────
# TEMPLATE & FONT UTILITIES
# ─────────────────────────────────────────────

def _get_template(tid: str) -> dict:
    for t in THUMBNAIL_TEMPLATES:
        if t["id"] == tid:
            return t
    return THUMBNAIL_TEMPLATES[0]


def _resize_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    sw, sh = img.size
    scale  = max(w / sw, h / sh)
    img    = img.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    nw, nh = img.size
    return img.crop(((nw - w) // 2, (nh - h) // 2,
                     (nw - w) // 2 + w, (nh - h) // 2 + h))


_font_cache: dict[int, ImageFont.FreeTypeFont] = {}

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if size in _font_cache:
        return _font_cache[size]
    candidates = [
        FONTS_DIR / "Anton-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        try:
            f = ImageFont.truetype(str(c), size)
            _font_cache[size] = f
            return f
        except (IOError, OSError):
            continue
    f = ImageFont.load_default()
    _font_cache[size] = f
    return f

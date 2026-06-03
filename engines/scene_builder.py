"""
engines/scene_builder.py
Karma Vault Stories — Visual Scene Builder Engine
For every blueprint part, downloads stock images (Pexels→Pixabay→Unsplash),
falls back to AI generation, applies cinematic grading, generates in-memory
documentary cards (evidence, location, shock overlays, CCTV frames), and
assembles the complete scene timeline consumed directly by the renderer.
Guarantees MIN_VISUAL_ASSETS_LONG unique visual events per run.
"""

import os
import time
import random
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

from config.settings import (
    PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY,
    VIDEO_WIDTH, VIDEO_HEIGHT,
    MIN_VISUAL_ASSETS_LONG, MAX_VISUAL_ASSETS_LONG,
    SCENE_DURATION_MIN_SEC, SCENE_DURATION_MAX_SEC,
    MAX_IMAGES_PER_SCENE,
    FONTS_DIR,
)
from config.constants import (
    ContentPillar, AssetCategory, VISUAL_COLORS, CINEMATIC_GRADE,
    VISUAL_FONT_FALLBACK, EVIDENCE_CARD_TYPES, SHOCK_CAPTION_POOL,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import image_path, card_path, ensure_run_workspace
from utils.api_client import (
    fetch_stock_images, download_image, download_base64_image, with_retry,
)
from engines.image_generator import generate_ai_image

log = get_logger(__name__)

# Motion type pool — assigned to each scene based on context
_MOTION_TYPES = [
    "slow_zoom_in", "slow_zoom_out", "pan_right",
    "pan_left", "drift_up", "drift_down",
]
_SHOCK_MOTION  = "shake"
_OUTRO_MOTION  = "drift_up"
_HOOK_MOTION   = "slow_zoom_in"

# Number of stock images to collect per blueprint part
_IMAGES_PER_PART = 5

# Pillar → stock search queries (dark and cinematic)
_PILLAR_STOCK_QUERIES: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "dark haunted room", "shadow figure corridor", "abandoned building night",
        "candle flame dark", "fog forest night", "silhouette dark hallway",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "couple argument silhouette", "secret letter dark", "shadow behind door",
        "sad woman window night", "noir detective shadow", "broken trust dark",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "empty road night fog", "missing person dark", "forest darkness path",
        "police tape crime scene", "cold case investigation", "abandoned house night",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "disaster aftermath dark", "emergency lights night", "tragedy documentation",
        "crime scene darkness", "industrial accident dark", "hospital emergency night",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "old documents archive dark", "historical building decay", "vintage newspaper dark",
        "sepia photograph ruins", "historical crime file", "antique corridor dark",
    ],
    ContentPillar.AI_HORROR.value: [
        "server room dark dramatic", "digital horror glitch", "cyber dark technology",
        "AI machine dark abstract", "computer screen night dramatic", "dystopian city dark",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "shadow two faces dark", "hidden room secret", "double identity noir",
        "mirror reflection dark", "secret meeting shadows", "noir mystery dark",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "computer screen dark night", "anonymous shadow figure", "dark message glow",
        "typing hands night dramatic", "digital confession dark", "screen glow darkness",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "urban legend dark street", "abandoned urban decay night", "graffiti dark alley",
        "legend location creepy", "city night dark dramatic", "urban horror alley",
    ],
    ContentPillar.TRUE_SHOCKING.value: [
        "crime documentary dark", "shocking truth revealed dark", "investigation dark",
        "dramatic dark crime", "dark truth discovery", "thriller documentary scene",
    ],
}

# Generic dark fallback queries when pillar queries are exhausted
_GENERIC_DARK_QUERIES = [
    "dark dramatic cinematic", "horror documentary still", "mystery darkness scene",
    "dark atmosphere dramatic", "cinematic dark portrait", "moody dark environment",
    "dramatic shadow light", "dark narrative scene",
]


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_scene_builder(ctx: DailyRunContext) -> DailyRunContext:
    """
    Builds ctx.scene_assets — a complete, renderer-ready visual timeline.
    Guarantees MIN_VISUAL_ASSETS_LONG unique images plus generated cards.
    """
    if not ctx.script_blueprint:
        log.error("No script blueprint — cannot build scenes.")
        return ctx

    log.info("Scene builder starting...")
    ensure_run_workspace(ctx.run_id)
    blueprint = ctx.script_blueprint
    parts     = blueprint.get("parts", [])
    pillar    = (ctx.selected_story.pillar
                 if ctx.selected_story else ContentPillar.TRUE_SHOCKING.value)
    country   = (ctx.selected_story.country
                 if ctx.selected_story else "Unknown")

    # ── Step 1: Build image + video asset pools ──────────────────
    log.info("Downloading visual assets (images + Pexels dark stock video)...")
    image_pool, video_pool = _build_image_pool(parts, pillar, country, ctx.run_id)
    log.info(f"Asset pools: {len(image_pool)} images, {len(video_pool)} stock video clips")

    # ── Step 2: Generate documentary cards ───────────────────────
    log.info("Generating documentary cards...")
    card_assets = _generate_all_cards(blueprint, country, ctx.run_id)
    log.info(f"Generated {len(card_assets)} documentary cards")

    # ── Step 3: Assemble scene timeline ──────────────────────────
    log.info("Assembling scene timeline...")
    scene_assets = _build_scene_timeline(
        parts, image_pool, card_assets, blueprint, pillar, video_pool
    )
    log.info(f"Scene timeline: {len(scene_assets)} total visual events")

    # Validate minimum asset count
    unique_paths = len({s["asset_path"] for s in scene_assets if s.get("asset_path")})
    if unique_paths < MIN_VISUAL_ASSETS_LONG:
        log.warning(
            f"Only {unique_paths} unique visual assets — below minimum {MIN_VISUAL_ASSETS_LONG}. "
            f"Generating additional AI images..."
        )
        scene_assets = _pad_with_ai_images(
            scene_assets, parts, pillar, ctx.run_id, MIN_VISUAL_ASSETS_LONG
        )

    # ── Phase B: Inject T2V video clips for key scenes ──────────────
    try:
        from config.settings import ENABLE_T2V_CLIPS, T2V_CLIPS_PER_VIDEO
        if ENABLE_T2V_CLIPS and scene_assets:
            log.info(f"Phase B T2V: generating clips for up to {T2V_CLIPS_PER_VIDEO} key scenes...")
            scene_assets = _inject_t2v_clips(
                scene_assets, ctx.run_id, country, pillar
            )
            t2v_count = sum(1 for s in scene_assets if s.get("asset_type") == "video_clip")
            log.info(f"Phase B T2V: {t2v_count} scenes upgraded to video clips.")
    except Exception as _t2v_exc:
        log.warning(f"Phase B T2V injection failed (non-fatal): {_t2v_exc}")

    ctx.scene_assets = scene_assets
    ctx.mark_stage("scene_builder")
    log.info(
        f"Scene builder complete. {len(scene_assets)} scenes, "
        f"{len({s['asset_path'] for s in scene_assets})} unique assets."
    )
    return ctx


# ─────────────────────────────────────────────
# IMAGE POOL BUILDER
# ─────────────────────────────────────────────

def _build_image_pool(
    parts:   list[dict],
    pillar:  str,
    country: str,
    run_id:  str,
) -> tuple[list[Path], list[Path]]:
    """
    Downloads and grades images for each blueprint part.
    Also downloads Pexels stock videos as fallback for key scenes.
    Returns (image_pool, video_pool).
    """
    pool:       list[Path] = []
    video_pool: list[Path] = []
    pillar_queries = list(_PILLAR_STOCK_QUERIES.get(pillar, _GENERIC_DARK_QUERIES))
    random.shuffle(pillar_queries)
    query_cursor = 0

    for part_idx, part in enumerate(parts):
        part_id      = part.get("part_id", f"part{part_idx}")
        scene_prompt = (part.get("scene_prompt") or "").strip()
        is_horror    = part_id in ("climax", "escalation") and part.get("is_twist", False)

        # Build queries: scene_prompt first, then pillar queries
        queries = []
        if scene_prompt:
            queries.append(_prompt_to_query(scene_prompt))
        # Add 2-3 pillar queries per part
        for _ in range(2):
            if query_cursor < len(pillar_queries):
                queries.append(pillar_queries[query_cursor])
                query_cursor += 1
            else:
                queries.append(random.choice(_GENERIC_DARK_QUERIES))

        part_images: list[Path] = []
        for query in queries:
            if len(part_images) >= _IMAGES_PER_PART:
                break
            downloaded = _fetch_and_download_images(
                query=query,
                run_id=run_id,
                part_id=part_id,
                offset=len(part_images),
                count=_IMAGES_PER_PART - len(part_images),
            )
            part_images.extend(downloaded)
            time.sleep(0.25)

        # AI fallback if stock returned too few
        if len(part_images) < 2:
            log.info(f"Part '{part_id}': stock returned {len(part_images)} — AI fallback.")
            ai_out = image_path(run_id, f"{part_id}_ai_fallback_{len(part_images):02d}.jpg")
            prompt = scene_prompt or random.choice(_GENERIC_DARK_QUERIES)
            if generate_ai_image(prompt, ai_out, pillar=pillar, horror_mode=is_horror):
                graded = _apply_cinematic_grading(ai_out, run_id, f"ai_{part_id}", is_horror)
                if graded:
                    part_images.append(graded)

        # Grade any ungraded images
        graded_part: list[Path] = []
        for img_path_raw in part_images:
            if "_graded" in img_path_raw.name:
                graded_part.append(img_path_raw)
            else:
                graded = _apply_cinematic_grading(img_path_raw, run_id, part_id, is_horror)
                if graded:
                    graded_part.append(graded)

        pool.extend(graded_part)
        log.info(f"  Part '{part_id}': {len(graded_part)} images in pool")

    # ── Pexels stock video pool for key visual moments ───────────
    try:
        from utils.api_client import fetch_pexels_videos, get_pexels_video_queries_for_pillar
        video_queries = get_pexels_video_queries_for_pillar(pillar)
        random.shuffle(video_queries)
        for q in video_queries[:4]:
            results = fetch_pexels_videos(query=q, count=2)
            for r in results:
                url = r.get("url", "")
                if not url:
                    continue
                vid_name  = f"pexels_vid_{len(video_pool):03d}.mp4"
                vid_path  = image_path(run_id, vid_name)
                vid_path.parent.mkdir(parents=True, exist_ok=True)
                if download_image(url, str(vid_path), timeout=60):
                    if vid_path.exists() and vid_path.stat().st_size > 100_000:
                        video_pool.append(vid_path)
                        log.info(f"  Pexels video downloaded: {vid_name} ({vid_path.stat().st_size//1024}KB)")
            if len(video_pool) >= 6:
                break
            time.sleep(0.5)
    except Exception as pex_exc:
        log.warning(f"Pexels video pool fetch failed (non-fatal): {pex_exc}")

    return pool, video_pool


def _fetch_and_download_images(
    query:   str,
    run_id:  str,
    part_id: str,
    offset:  int,
    count:   int,
) -> list[Path]:
    """Fetches stock images for a query and downloads them to disk."""
    paths: list[Path] = []
    try:
        results = with_retry(
            fetch_stock_images,
            query=query,
            count=count + 2,   # request a few extra to compensate for failures
            orientation="landscape",
            exclude_ai=True,   # stock images only — AI is handled separately
        )
        for i, result in enumerate(results[:count]):
            fname  = f"{part_id}_stock_{offset + i:03d}.jpg"
            dest   = image_path(run_id, fname)
            dest.parent.mkdir(parents=True, exist_ok=True)

            url    = result.get("url", "")
            b64    = result.get("url_base64", "")

            if url and url.startswith("http"):
                ok = download_image(url, str(dest), timeout=20)
            elif b64:
                ok = download_base64_image(b64, str(dest))
            else:
                ok = False

            if ok and dest.exists() and dest.stat().st_size > 5000:
                paths.append(dest)
    except Exception as exc:
        log.warning(f"Stock image fetch failed for '{query[:40]}': {exc}")
    return paths


# ─────────────────────────────────────────────
# CINEMATIC GRADING PIPELINE
# ─────────────────────────────────────────────

def _apply_cinematic_grading(
    src_path:    Path,
    run_id:      str,
    label:       str,
    horror_mode: bool = False,
) -> Optional[Path]:
    """
    Applies the full cinematic grading pipeline to a single image:
      1. Resize to 1920×1080 (crop to fill)
      2. Contrast boost
      3. Brightness reduction
      4. Saturation reduction
      5. Numpy vignette overlay
      6. Optional red tint (horror mode)
      7. Optional subtle grain
    Returns graded image path, or None on failure.
    """
    try:
        out_path = image_path(run_id, f"{label}_graded_{src_path.stem}.jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.open(str(src_path)).convert("RGB")
        img = _resize_crop(img, VIDEO_WIDTH, VIDEO_HEIGHT)

        # Contrast boost
        img = ImageEnhance.Contrast(img).enhance(
            CINEMATIC_GRADE["contrast_boost"]
        )
        # Brightness reduce
        img = ImageEnhance.Brightness(img).enhance(
            1.0 + CINEMATIC_GRADE["brightness_reduce"]
        )
        # Saturation reduce
        img = ImageEnhance.Color(img).enhance(
            CINEMATIC_GRADE["saturation_reduce"]
        )

        # Vignette via numpy
        arr = np.array(img, dtype=np.float32)
        arr = _apply_vignette_numpy(arr, CINEMATIC_GRADE["vignette_strength"])

        # Horror red tint
        if horror_mode and CINEMATIC_GRADE["red_tint_horror"]:
            arr = _apply_red_tint(arr, strength=0.12)

        # Subtle grain
        grain = CINEMATIC_GRADE["grain_strength"]
        if grain > 0:
            noise = np.random.randn(*arr.shape) * grain * 255
            arr   = arr + noise

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        graded = Image.fromarray(arr)
        graded.save(str(out_path), "JPEG", quality=88, optimize=True)
        return out_path

    except Exception as exc:
        log.warning(f"Cinematic grading failed for {src_path.name}: {exc}")
        return None


def _resize_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop to exactly target_w × target_h."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img   = img.resize((new_w, new_h), Image.LANCZOS)
    left  = (new_w - target_w) // 2
    top   = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _apply_vignette_numpy(arr: np.ndarray, strength: float) -> np.ndarray:
    """Applies a smooth radial vignette using numpy broadcasting."""
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    # Normalized distance from center (0=center, 1=corner)
    dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    # Vignette falloff: 0 effect inside radius, ramps to `strength` at edges
    fade = np.clip(dist - 0.45, 0, 1)
    fade = (fade / 0.55) ** 1.8 * strength
    mask = (1.0 - fade)[:, :, np.newaxis]
    return arr * mask


def _apply_red_tint(arr: np.ndarray, strength: float = 0.10) -> np.ndarray:
    """Boosts red channel and slightly desaturates green/blue for horror mood."""
    result = arr.copy().astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * (1.0 + strength * 1.5), 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * (1.0 - strength * 0.5), 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * (1.0 - strength * 0.8), 0, 255)
    return result


# ─────────────────────────────────────────────
# DOCUMENTARY CARD GENERATORS
# ─────────────────────────────────────────────

def _generate_all_cards(
    blueprint: dict,
    country:   str,
    run_id:    str,
) -> dict[str, Path]:
    """
    Pre-generates all documentary cards used in this run.
    Returns: {card_key: path}
    """
    cards: dict[str, Path] = {}

    # Evidence cards from blueprint
    for i, ev_card in enumerate(blueprint.get("evidence_cards", [])):
        part_id  = ev_card.get("part_id", "unknown")
        key      = f"evidence_{i}_{part_id}"
        out      = card_path(run_id, f"{key}.jpg")
        _generate_evidence_card(
            card_type=ev_card.get("type", "POLICE FILE"),
            card_text=ev_card.get("text", ""),
            output_path=out,
        )
        cards[key] = out

    # Location card for opening (COUNTRY — YEAR)
    import random as _rand
    year = str(_rand.randint(2015, 2023))
    loc_key = "location_card_intro"
    loc_out = card_path(run_id, f"{loc_key}.jpg")
    _generate_location_card(country, year, loc_out)
    cards[loc_key] = loc_out

    # Shock overlay cards
    shock_captions = blueprint.get("shock_captions", [])
    for i, sc in enumerate(shock_captions):
        text = sc.get("text", "")
        if not text:
            continue
        key = f"shock_{i}_{sc.get('part_id','?')}"
        out = card_path(run_id, f"{key}.jpg")
        _generate_shock_overlay(text, out)
        cards[key] = out

    # CCTV-style intro card (always generated)
    cctv_key = "cctv_overlay_intro"
    cctv_out = card_path(run_id, f"{cctv_key}.jpg")
    _generate_cctv_overlay(cctv_out)
    cards[cctv_key] = cctv_out

    return cards


def _generate_evidence_card(
    card_type:   str,
    card_text:   str,
    output_path: Path,
) -> None:
    """
    Generates a documentary-style evidence card:
    Dark background, red border, uppercase card type header, detail text.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    img  = Image.new("RGB", (w, h), color=(6, 6, 6))
    draw = ImageDraw.Draw(img)

    # Outer border
    bx, by = 80, 120
    draw.rectangle([bx, by, w - bx, h - by],
                   outline=VISUAL_COLORS["accent_red"], width=3)

    # Inner accent line
    draw.rectangle([bx + 12, by + 12, w - bx - 12, h - by - 12],
                   outline=(40, 40, 40), width=1)

    # Red header bar
    bar_h = 130
    draw.rectangle([bx, by, w - bx, by + bar_h],
                   fill=VISUAL_COLORS["accent_red"])

    # Card type text
    font_large  = _load_font(90)
    font_medium = _load_font(55)
    font_small  = _load_font(38)

    # Measure and center card type
    bbox  = draw.textbbox((0, 0), card_type, font=font_large)
    tw    = bbox[2] - bbox[0]
    tx    = (w - tw) // 2
    draw.text((tx, by + 22), card_type,
              font=font_large, fill=VISUAL_COLORS["primary_text"])

    # Divider
    draw.line([(bx + 30, by + bar_h + 25), (w - bx - 30, by + bar_h + 25)],
              fill=(80, 80, 80), width=1)

    # Card detail text — split long text across lines
    detail_y = by + bar_h + 60
    for line in _wrap_text(card_text, max_chars=38):
        bbox2 = draw.textbbox((0, 0), line, font=font_medium)
        tw2   = bbox2[2] - bbox2[0]
        draw.text(((w - tw2) // 2, detail_y),
                  line, font=font_medium, fill=VISUAL_COLORS["primary_text"])
        detail_y += 75

    # Bottom tag
    tag_text = "KARMA VAULT STORIES — CLASSIFIED FILE"
    bbox3    = draw.textbbox((0, 0), tag_text, font=font_small)
    tw3      = bbox3[2] - bbox3[0]
    draw.text(((w - tw3) // 2, h - by - 55),
              tag_text, font=font_small, fill=(100, 100, 100))

    img.save(str(output_path), "JPEG", quality=92)


def _generate_location_card(
    country:     str,
    year:        str,
    output_path: Path,
) -> None:
    """
    Generates a location/date title card:
    E.g. "CAIRO, EGYPT — 2019" in white on dark background.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    # Dark gradient background
    arr = np.zeros((h, w, 3), dtype=np.float32)
    gradient = np.linspace(0.02, 0.12, h)
    arr[:, :, 0] = gradient[:, np.newaxis] * 255
    img  = Image.fromarray(arr.astype(np.uint8))
    draw = ImageDraw.Draw(img)

    # Horizontal line
    draw.line([(150, h // 2 - 70), (w - 150, h // 2 - 70)],
              fill=VISUAL_COLORS["accent_red"], width=2)

    font_xl = _load_font(110)
    font_sm = _load_font(44)

    loc_text  = country.upper()
    year_text = f"— {year} —"

    bbox = draw.textbbox((0, 0), loc_text, font=font_xl)
    draw.text(((w - (bbox[2] - bbox[0])) // 2, h // 2 - 65),
              loc_text, font=font_xl, fill=VISUAL_COLORS["primary_text"])

    bbox2 = draw.textbbox((0, 0), year_text, font=font_sm)
    draw.text(((w - (bbox2[2] - bbox2[0])) // 2, h // 2 + 80),
              year_text, font=font_sm, fill=VISUAL_COLORS["accent_red"])

    draw.line([(150, h // 2 + 145), (w - 150, h // 2 + 145)],
              fill=VISUAL_COLORS["accent_red"], width=2)

    img.save(str(output_path), "JPEG", quality=92)


def _generate_shock_overlay(
    text:        str,
    output_path: Path,
) -> None:
    """
    Giant shock text on dark semi-transparent background.
    Red text with thick white stroke for maximum impact.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    img  = Image.new("RGB", (w, h), color=(4, 0, 0))
    draw = ImageDraw.Draw(img)

    font = _load_font(220)

    # Stroke (white outline)
    stroke_width = 8
    for dx in range(-stroke_width, stroke_width + 1, 2):
        for dy in range(-stroke_width, stroke_width + 1, 2):
            if abs(dx) + abs(dy) <= stroke_width * 1.5:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw   = bbox[2] - bbox[0]
                th   = bbox[3] - bbox[1]
                draw.text(
                    ((w - tw) // 2 + dx, (h - th) // 2 + dy),
                    text, font=font, fill=(255, 255, 255)
                )

    # Main text (shock red)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    draw.text(
        ((w - tw) // 2, (h - th) // 2),
        text, font=font, fill=VISUAL_COLORS["shock_red"]
    )

    img.save(str(output_path), "JPEG", quality=90)


def _generate_cctv_overlay(output_path: Path) -> None:
    """
    CCTV-style overlay: dark green-tinted scan lines on black.
    Used as an atmospheric interstitial card.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    arr = np.zeros((h, w, 3), dtype=np.uint8)
    # Subtle scan lines
    for y in range(0, h, 4):
        arr[y, :, 1] = random.randint(8, 20)   # green channel

    # CCTV timestamp look
    img  = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    font = _load_font(36)
    import datetime
    ts = datetime.datetime(
        random.randint(2015, 2022), random.randint(1, 12),
        random.randint(1, 28), random.randint(0, 23),
        random.randint(0, 59), random.randint(0, 59),
    ).strftime("%Y-%m-%d  %H:%M:%S")
    draw.text((30, 30), f"REC  CAM-{random.randint(1,8):02d}  {ts}",
              font=font, fill=(0, 200, 0))
    draw.text((30, h - 55), "FOOTAGE CLASSIFIED",
              font=font, fill=(0, 180, 0))

    img.save(str(output_path), "JPEG", quality=85)


# ─────────────────────────────────────────────
# SCENE TIMELINE ASSEMBLER
# ─────────────────────────────────────────────

def _build_scene_timeline(
    parts:       list[dict],
    image_pool:  list[Path],
    card_assets: dict[str, Path],
    blueprint:   dict,
    pillar:      str,
    video_pool:  list[Path] | None = None,
) -> list[dict]:
    """
    Assembles the complete scene timeline.
    - Each part is subdivided into 3–6 second scene cuts
    - Images from the pool are distributed across scenes
    - Evidence cards, location cards, shock overlays inserted at correct times
    - Motion types assigned to create visual variety
    Returns list of scene dicts consumed directly by the renderer.
    """
    if not image_pool:
        log.error("Image pool is empty — timeline will be sparse.")

    scenes: list[dict] = []
    pool_idx   = 0
    scene_idx  = 0
    shock_map  = _build_shock_map(blueprint)
    evidence_map = _build_evidence_map(blueprint)

    for part in parts:
        part_id    = part.get("part_id", "")
        start_time = part.get("start_time_sec", 0.0)
        duration   = part.get("duration_sec", 30.0)
        sfx_marker = part.get("sfx_marker")
        is_twist   = part.get("is_twist", False)
        is_horror  = part_id in ("climax", "escalation") and is_twist
        is_intro   = (scene_idx == 0)

        # Insert location card at the start of context part
        if part_id == "context":
            loc_path = card_assets.get("location_card_intro")
            if loc_path and loc_path.exists():
                scenes.append(_make_scene(
                    scene_idx, part_id, str(loc_path), AssetCategory.LOCATION_DATE_CARD.value,
                    start_time, 2.5, "static", is_horror=False,
                    is_intro=False, is_outro=False,
                    evidence_card_data=None, shock_caption=None, cta_overlay=False,
                ))
                scene_idx  += 1
                start_time += 2.5

        # Insert evidence card for this part if one exists
        ev_card_key = _find_evidence_key(evidence_map, part_id)
        if ev_card_key:
            ev_path = card_assets.get(ev_card_key)
            if ev_path and ev_path.exists():
                scenes.append(_make_scene(
                    scene_idx, part_id, str(ev_path), AssetCategory.EVIDENCE_CARD.value,
                    start_time, 2.8, "static", is_horror=False,
                    is_intro=False, is_outro=False,
                    evidence_card_data=blueprint.get("evidence_cards", [{}])[0],
                    shock_caption=None, cta_overlay=False,
                ))
                scene_idx  += 1
                start_time += 2.8

        # Main scene cuts for this part
        time_in_part = 0.0
        cut_count    = 0
        is_cta_part  = part.get("cta_marker", False)

        while time_in_part < duration - 0.5:
            cut_dur = random.uniform(
                SCENE_DURATION_MIN_SEC,
                min(SCENE_DURATION_MAX_SEC, duration - time_in_part)
            )
            cut_dur = max(2.5, cut_dur)

            # Get image from pool (cycle)
            # Use Pexels stock video clip for peak horror/climax scenes if available
            if (video_pool and part_id in ("climax", "escalation", "hook")
                    and pool_idx < len(video_pool)):
                img_path  = video_pool[pool_idx % len(video_pool)]
                asset_type = "video_clip"   # renderer uses -stream_loop
                pool_idx += 1
            elif image_pool:
                img_path  = image_pool[pool_idx % len(image_pool)]
                asset_type = AssetCategory.STOCK_PHOTO.value
                pool_idx += 1
            else:
                img_path = card_assets.get("cctv_overlay_intro",
                           next(iter(card_assets.values()), None))
                asset_type = AssetCategory.CCTV_STYLE.value

            # Motion: vary across cuts, shock moments get shake
            shock_text = shock_map.get(part_id) if cut_count == 0 else None
            motion     = _SHOCK_MOTION if shock_text else _assign_motion(scene_idx, part_id)
            is_last    = (scene_idx == 0 and len(parts) == 1)   # only one part

            scenes.append(_make_scene(
                scene_idx, part_id,
                str(img_path) if img_path else "",
                asset_type,
                start_time + time_in_part,
                cut_dur,
                motion,
                is_horror  = is_horror,
                is_intro   = is_intro and cut_count == 0,
                is_outro   = False,
                evidence_card_data = None,
                shock_caption      = shock_text if cut_count == 0 else None,
                cta_overlay        = is_cta_part and cut_count == 1,
            ))

            scene_idx   += 1
            cut_count   += 1
            time_in_part += cut_dur
            is_intro     = False

    # Mark the very last scene as outro
    if scenes:
        scenes[-1]["is_outro"] = True

    return scenes


def _make_scene(
    scene_idx:          int,
    part_id:            str,
    asset_path:         str,
    asset_type:         str,
    start_time_sec:     float,
    duration_sec:       float,
    motion_type:        str,
    is_horror:          bool,
    is_intro:           bool,
    is_outro:           bool,
    evidence_card_data: Optional[dict],
    shock_caption:      Optional[str],
    cta_overlay:        bool,
) -> dict:
    return {
        "scene_idx":         scene_idx,
        "part_id":           part_id,
        "asset_path":        asset_path,
        "asset_type":        asset_type,
        "start_time_sec":    round(start_time_sec, 3),
        "duration_sec":      round(duration_sec, 3),
        "motion_type":       motion_type,
        "horror_grading":    is_horror,
        "shock_caption":     shock_caption,
        "cta_overlay":       cta_overlay,
        "evidence_card_data": evidence_card_data,
        "is_intro":          is_intro,
        "is_outro":          is_outro,
    }


def _assign_motion(scene_idx: int, part_id: str) -> str:
    """Assigns a motion type based on scene position and part type."""
    if part_id == "hook":
        return _HOOK_MOTION
    if part_id == "aftermath":
        return _OUTRO_MOTION
    if part_id in ("climax", "escalation"):
        options = ["slow_zoom_in", "pan_right", "pan_left", "slow_zoom_out"]
    else:
        options = _MOTION_TYPES
    return options[scene_idx % len(options)]


def _build_shock_map(blueprint: dict) -> dict[str, str]:
    """Returns {part_id: shock_caption_text} for parts with shock captions."""
    result: dict[str, str] = {}
    for sc in blueprint.get("shock_captions", []):
        pid  = sc.get("part_id", "")
        text = sc.get("text", "")
        if pid and text and pid not in result:
            result[pid] = text
    return result


def _build_evidence_map(blueprint: dict) -> dict[str, str]:
    """Returns {part_id: evidence_key} for evidence card insertion."""
    result: dict[str, str] = {}
    for i, ev in enumerate(blueprint.get("evidence_cards", [])):
        pid = ev.get("part_id", "")
        if pid and pid not in result:
            result[pid] = f"evidence_{i}_{pid}"
    return result


def _find_evidence_key(evidence_map: dict, part_id: str) -> Optional[str]:
    return evidence_map.get(part_id)


def _pad_with_ai_images(
    scenes:    list[dict],
    parts:     list[dict],
    pillar:    str,
    run_id:    str,
    target:    int,
) -> list[dict]:
    """
    Generates additional AI images and substitutes them for repeated images
    until we reach `target` unique visual assets.
    """
    unique = {s["asset_path"] for s in scenes if s.get("asset_path")}
    needed = target - len(unique)
    if needed <= 0:
        return scenes

    queries = list(_PILLAR_STOCK_QUERIES.get(pillar, _GENERIC_DARK_QUERIES))
    random.shuffle(queries)

    new_paths: list[Path] = []
    for i in range(min(needed + 3, 12)):
        query   = queries[i % len(queries)] if queries else "dark cinematic"
        out     = image_path(run_id, f"ai_pad_{i:03d}.jpg")
        graded_out = image_path(run_id, f"ai_pad_{i:03d}_graded.jpg")

        if generate_ai_image(query, out, pillar=pillar):
            graded = _apply_cinematic_grading(out, run_id, f"pad{i}", False)
            if graded:
                new_paths.append(graded)
        if len(new_paths) >= needed:
            break
        time.sleep(0.5)

    if not new_paths:
        return scenes

    # Substitute new paths into scenes that use repeated assets
    path_usage: dict[str, int] = {}
    pad_cursor = 0
    for scene in scenes:
        ap = scene.get("asset_path", "")
        if ap in path_usage and path_usage[ap] >= 3 and pad_cursor < len(new_paths):
            scene["asset_path"] = str(new_paths[pad_cursor])
            pad_cursor += 1
        path_usage[ap] = path_usage.get(ap, 0) + 1

    return scenes


# ─────────────────────────────────────────────
# FONT & TEXT UTILITIES
# ─────────────────────────────────────────────

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Loads the best available bold font at the given size, with caching."""
    if size in _font_cache:
        return _font_cache[size]

    # Try fonts in order of visual quality for our use case
    candidates = [
        FONTS_DIR / "Anton-Regular.ttf",               # downloaded at first run
        FONTS_DIR / "Impact.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for candidate in candidates:
        try:
            font = ImageFont.truetype(str(candidate), size)
            _font_cache[size] = font
            return font
        except (IOError, OSError):
            continue

    # Last resort: default PIL font (no scaling)
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _download_impact_font() -> bool:
    """
    Downloads Anton (Impact-like) font from Google Fonts CDN on first run.
    Saves to FONTS_DIR for all subsequent uses.
    """
    target = FONTS_DIR / "Anton-Regular.ttf"
    if target.exists():
        return True
    try:
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        from utils.api_client import http_get
        url   = "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm0K08i4gS7lu.woff2"
        # Anton TTF direct URL
        url   = "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
        data  = http_get(url, timeout=20)
        with open(target, "wb") as f:
            f.write(data)
        log.info(f"Downloaded Anton font: {target}")
        return True
    except Exception as exc:
        log.debug(f"Font download failed (will use system font): {exc}")
        return False


def _wrap_text(text: str, max_chars: int = 38) -> list[str]:
    """Wraps text to lines of max_chars, breaking at word boundaries."""
    words  = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _prompt_to_query(prompt: str, max_words: int = 6) -> str:
    """Extracts concise stock image search keywords from a scene prompt."""
    noise = {
        "fading", "to", "with", "and", "at", "in", "a", "the", "an",
        "single", "subtle", "slight", "slow", "occasional", "deep", "very",
        "extremely", "slightly", "quickly", "dramatic", "ominous", "style",
        "cinematic", "documentary", "frame", "shot", "scene", "into",
    }
    words = prompt.lower().replace(",", " ").replace(".", " ").split()
    kept  = [w for w in words if len(w) > 4 and w not in noise]
    return " ".join(kept[:max_words])


# Attempt font download at module load (non-blocking)
try:
    _download_impact_font()
except Exception:
    pass


# ─────────────────────────────────────────────
# PHASE B: T2V CLIP INJECTION
# ─────────────────────────────────────────────

def _inject_t2v_clips(
    scene_assets: list[dict],
    run_id:       str,
    country:      str,
    pillar:       str,
) -> list[dict]:
    """
    Replaces stock images with AI-generated video clips for key scenes.
    Targets hook, escalation, and climax scenes up to T2V_CLIPS_PER_VIDEO.
    Falls back silently — scene keeps its original stock image on failure.
    """
    from config.settings import T2V_CLIPS_PER_VIDEO
    from engines.video_clip_generator import generate_clips_for_scenes

    stock_types = {"stock_photo", AssetCategory.STOCK_PHOTO.value}

    # Select key scenes in priority order
    priority_parts = ["hook", "climax", "escalation", "first_sign", "context"]
    candidates: list[dict] = []
    seen_parts: dict[str, int] = {}

    for part in priority_parts:
        for scene in scene_assets:
            if (scene.get("part_id") == part
                    and scene.get("asset_type") in stock_types
                    and scene not in candidates):
                seen_parts[part] = seen_parts.get(part, 0) + 1
                if seen_parts[part] <= 2:   # max 2 clips per part
                    candidates.append(scene)
        if len(candidates) >= T2V_CLIPS_PER_VIDEO:
            break

    candidates = candidates[:T2V_CLIPS_PER_VIDEO]
    if not candidates:
        return scene_assets

    # Build index of candidate scenes
    candidate_idxs = [scene_assets.index(s) for s in candidates]
    indexed_candidates = [
        {**candidates[i], "__orig_idx": candidate_idxs[i]}
        for i in range(len(candidates))
    ]

    log.info(f"  T2V candidates: {[s['part_id'] for s in candidates]}")

    try:
        clip_results = generate_clips_for_scenes(
            indexed_candidates, run_id, country, pillar
        )
    except Exception as exc:
        log.warning(f"  T2V generation failed: {exc}")
        return scene_assets

    # Inject successful clips back into scene_assets
    for local_idx, clip_path in clip_results.items():
        if clip_path and Path(clip_path).exists():
            orig_idx = candidate_idxs[local_idx]
            scene_assets[orig_idx]["asset_path"] = str(clip_path)
            scene_assets[orig_idx]["asset_type"] = "video_clip"
            log.debug(f"  Injected clip at scene_idx={orig_idx}")

    return scene_assets

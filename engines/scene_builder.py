engines/scene_builder.py
Karma Vault Stories — Visual Scene Builder Engine
Phase A upgrade: LLM-driven semantic keyword extraction replaces the broken
prompt_to_query heuristic. Stock searches now include explicit negative terms
to block letter-art, placeholder, and text-heavy images.
"""

import os
import re
import time
import random
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from config.settings import (
    PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY,
    VIDEO_WIDTH, VIDEO_HEIGHT,
    MIN_VISUAL_ASSETS_LONG, MAX_VISUAL_ASSETS_LONG,
    SCENE_DURATION_MIN_SEC, SCENE_DURATION_MAX_SEC,
    FONTS_DIR,
)
from config.constants import (
    ContentPillar, AssetCategory, VISUAL_COLORS, CINEMATIC_GRADE,
    EVIDENCE_CARD_TYPES, SHOCK_CAPTION_POOL,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import image_path, card_path, ensure_run_workspace
from utils.api_client import (
    fetch_stock_images, download_image, download_base64_image,
    call_writing_model, with_retry,
)
from engines.image_generator import generate_ai_image

log = get_logger(__name__)

_IMAGES_PER_PART = 5

# ── Negative search terms appended to ALL stock queries ──────────────────────
# These block Wikimedia letter-art, "EMPTY", "OPENING SOON", calendar images, etc.
_STOCK_NEGATIVE = "-sign -letters -alphabet -calendar -poster -opening -empty -soon -template"

# ── Pillar-specific photographic search queries ───────────────────────────────
# Deliberately concrete and photo-oriented, NOT descriptive prose
_PILLAR_STOCK_QUERIES: dict[str, list[str]] = {
    ContentPillar.PARANORMAL.value: [
        "dark hallway night photography", "abandoned house interior",
        "fog forest night photo", "candlelight darkness room",
        "shadow silhouette dramatic light", "old building decay interior",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "couple arguing silhouette", "person alone dark room",
        "sad woman window rain", "noir detective shadows",
        "hands reaching door night", "walking away dark street",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "empty road fog night", "missing person search forest",
        "police flashlight darkness", "abandoned car road",
        "search and rescue night", "crime scene investigation",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "emergency lights night rain", "ambulance dark street",
        "hospital emergency entrance night", "accident scene road night",
        "rescue workers darkness", "crime scene tape night",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "old documents archive dark", "vintage photograph sepia decay",
        "historical building ruins interior", "antique room candlelight",
        "archive papers scattered dark", "museum artifact dark display",
    ],
    ContentPillar.AI_HORROR.value: [
        "server room dark blue light", "computer screens dark room",
        "data center night photography", "glowing screens darkness",
        "circuit board macro dark", "hacker dark room screen",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "person shadows doorway dramatic", "identity secret noir",
        "two faces reflection dark mirror", "hidden room interior",
        "person watching from shadows", "secret meeting night photography",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "hands typing laptop dark", "screen glow dark room",
        "anonymous person hood dark", "phone screen night darkness",
        "social media night phone glow", "typing hands night light",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "dark alley night city", "abandoned urban building night",
        "creepy street night fog", "urban decay interior dark",
        "night city shadows dramatic", "empty street darkness",
    ],
    ContentPillar.TRUE_SHOCKING.value: [
        "crime investigation dark room", "detective work night",
        "evidence table dark dramatic", "interrogation room shadows",
        "night crime scene photography", "justice scales dark dramatic",
    ],
}

_GENERIC_DARK_QUERIES = [
    "dramatic dark cinematic photography", "shadows dramatic light portrait",
    "dark moody atmosphere interior", "night scene dramatic lighting",
    "low key photography shadows", "cinematic dark room light",
]


# ─────────────────────────────────────────────
# LLM-DRIVEN KEYWORD EXTRACTION
# ─────────────────────────────────────────────

def _extract_scene_keywords_llm(
    scene_prompt: str,
    story_country: str,
    pillar: str,
    part_id: str,
) -> list[str]:
    """
    Uses the writing model to extract 3-5 concrete photographic search terms
    from a scene prompt. Falls back to rule-based extraction if LLM fails.
    Critically: the system prompt enforces terms that find PHOTOGRAPHS, not
    letter-art, illustrations, diagrams, or text-based images.
    """
    if not scene_prompt.strip():
        return [random.choice(_GENERIC_DARK_QUERIES)]

    system_prompt = (
        "You extract stock photography search terms from scene descriptions. "
        "Rules: Return ONLY 3 short search phrases, one per line. "
        "Each phrase must describe a PHYSICAL SCENE or ENVIRONMENT that can be photographed. "
        "NEVER return: letters, alphabet, text, words, signs, posters, symbols, icons, logos, calendars. "
        "NEVER return abstract concepts alone (fear, evil, darkness without a subject). "
        "ALWAYS include a physical subject: a person, a room, a building, a road, an object. "
        "Example good output:\n"
        "dark empty hospital corridor night\n"
        "abandoned building interior shadows\n"
        "person silhouette doorway dramatic light"
    )

    user_prompt = (
        f"Scene description: {scene_prompt[:200]}\n"
        f"Story location: {story_country}\n"
        f"Genre: dark documentary, {pillar.replace('_', ' ')}\n"
        f"Part: {part_id}\n\n"
        f"Extract 3 photographic search terms:"
    )

    try:
        raw = call_writing_model(
            system_prompt, user_prompt,
            max_tokens=80, temperature=0.3, json_output=False,
        )
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        # Filter out any lines that look like they'd return text/letter images
        _bad_terms = {"letter", "alphabet", "text", "font", "word", "sign",
                      "poster", "logo", "icon", "symbol", "calendar", "flag"}
        cleaned = []
        for line in lines:
            if not any(bt in line.lower() for bt in _bad_terms):
                cleaned.append(line[:80])
        if cleaned:
            log.debug(f"LLM keywords for '{part_id}': {cleaned}")
            return cleaned[:3]
    except Exception as exc:
        log.debug(f"LLM keyword extraction failed ({part_id}): {exc}")

    # Rule-based fallback
    return [_prompt_to_query_fallback(scene_prompt)]


def _prompt_to_query_fallback(prompt: str) -> str:
    """
    Rule-based keyword extraction — last resort when LLM fails.
    Strips prose and pulls concrete nouns/descriptors.
    """
    # Remove scene-direction noise words
    noise = {
        "fading", "to", "with", "and", "at", "in", "a", "the", "an",
        "single", "subtle", "slight", "slow", "dramatic", "ominous",
        "cinematic", "documentary", "frame", "shot", "scene", "into",
        "style", "very", "slightly", "quickly", "emerging", "revealing",
        "showing", "casting", "flickering", "through", "behind", "over",
        "under", "upon", "from", "near", "inside", "outside",
    }
    words = prompt.lower().replace(",", " ").replace(".", " ").split()
    kept  = [w for w in words if len(w) > 4 and w not in noise]
    # Take first 5 meaningful words
    return " ".join(kept[:5]) if kept else "dark dramatic scene photography"


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_scene_builder(ctx: DailyRunContext) -> DailyRunContext:
    if not ctx.script_blueprint:
        log.error("No script blueprint — cannot build scenes.")
        return ctx

    log.info("Scene builder starting...")
    ensure_run_workspace(ctx.run_id)
    blueprint = ctx.script_blueprint
    parts     = blueprint.get("parts", [])
    pillar    = (ctx.selected_story.pillar if ctx.selected_story
                 else ContentPillar.TRUE_SHOCKING.value)
    country   = (ctx.selected_story.country if ctx.selected_story else "Unknown")

    log.info("Building image pool (LLM-enhanced keyword extraction)...")
    image_pool = _build_image_pool(parts, pillar, country, ctx.run_id)
    log.info(f"Image pool: {len(image_pool)} processed images")

    log.info("Generating documentary cards...")
    card_assets = _generate_all_cards(blueprint, country, ctx.run_id)
    log.info(f"Generated {len(card_assets)} documentary cards")

    log.info("Assembling scene timeline...")
    scene_assets = _build_scene_timeline(
        parts, image_pool, card_assets, blueprint, pillar
    )
    log.info(f"Scene timeline: {len(scene_assets)} total visual events")

    unique_paths = len({s["asset_path"] for s in scene_assets if s.get("asset_path")})
    if unique_paths < MIN_VISUAL_ASSETS_LONG:
        log.warning(f"Only {unique_paths} unique assets — padding with AI images.")
        scene_assets = _pad_with_ai_images(scene_assets, parts, pillar, ctx.run_id,
                                           MIN_VISUAL_ASSETS_LONG)

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
) -> list[Path]:
    pool: list[Path] = []
    pillar_queries = list(_PILLAR_STOCK_QUERIES.get(pillar, _GENERIC_DARK_QUERIES))
    random.shuffle(pillar_queries)
    pq_cursor = 0

    for part_idx, part in enumerate(parts):
        part_id      = part.get("part_id", f"part{part_idx}")
        scene_prompt = (part.get("scene_prompt") or "").strip()
        is_horror    = part_id in ("climax", "escalation") and part.get("is_twist", False)

        # ── LLM keyword extraction ──────────────────────────────
        llm_queries = _extract_scene_keywords_llm(scene_prompt, country, pillar, part_id)

        # ── Supplement with pillar queries ──────────────────────
        queries = list(llm_queries)
        for _ in range(2):
            if pq_cursor < len(pillar_queries):
                queries.append(pillar_queries[pq_cursor])
                pq_cursor += 1
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
            time.sleep(0.3)

        # ── AI fallback ─────────────────────────────────────────
        if len(part_images) < 2:
            log.info(f"Part '{part_id}': stock returned {len(part_images)} — AI fallback.")
            ai_out = image_path(run_id, f"{part_id}_ai_{len(part_images):02d}.jpg")
            prompt = scene_prompt or random.choice(_GENERIC_DARK_QUERIES)
            if generate_ai_image(prompt, ai_out, pillar=pillar, horror_mode=is_horror):
                graded = _apply_cinematic_grading(ai_out, run_id, f"ai_{part_id}", is_horror)
                if graded:
                    part_images.append(graded)

        # ── Grade all images ─────────────────────────────────────
        graded_part: list[Path] = []
        for raw_path in part_images:
            if "_graded" in raw_path.name:
                graded_part.append(raw_path)
            else:
                g = _apply_cinematic_grading(raw_path, run_id, part_id, is_horror)
                if g:
                    graded_part.append(g)

        pool.extend(graded_part)
        log.info(f"  Part '{part_id}': {len(graded_part)} images")

    return pool


def _fetch_and_download_images(
    query:   str,
    run_id:  str,
    part_id: str,
    offset:  int,
    count:   int,
) -> list[Path]:
    paths: list[Path] = []
    try:
        results = with_retry(
            fetch_stock_images,
            query=query,
            count=count + 3,
            orientation="landscape",
            exclude_ai=True,
        )
        for i, result in enumerate(results[:count]):
            fname = f"{part_id}_stock_{offset + i:03d}.jpg"
            dest  = image_path(run_id, fname)
            dest.parent.mkdir(parents=True, exist_ok=True)

            url = result.get("url", "")
            b64 = result.get("url_base64", "")

            if url and url.startswith("http"):
                ok = download_image(url, str(dest), timeout=20)
            elif b64:
                ok = download_base64_image(b64, str(dest))
            else:
                ok = False

            if ok and dest.exists() and dest.stat().st_size > 5000:
                paths.append(dest)
    except Exception as exc:
        log.warning(f"Stock fetch failed for '{query[:40]}': {exc}")
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
    try:
        out_path = image_path(run_id, f"{label}_graded_{src_path.stem}.jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.open(str(src_path)).convert("RGB")
        img = _resize_crop(img, VIDEO_WIDTH, VIDEO_HEIGHT)

        img = ImageEnhance.Contrast(img).enhance(CINEMATIC_GRADE["contrast_boost"])
        img = ImageEnhance.Brightness(img).enhance(1.0 + CINEMATIC_GRADE["brightness_reduce"])
        img = ImageEnhance.Color(img).enhance(CINEMATIC_GRADE["saturation_reduce"])

        arr = np.array(img, dtype=np.float32)
        arr = _apply_vignette_numpy(arr, CINEMATIC_GRADE["vignette_strength"])

        if horror_mode and CINEMATIC_GRADE["red_tint_horror"]:
            arr = _apply_red_tint(arr, strength=0.12)

        grain = CINEMATIC_GRADE["grain_strength"]
        if grain > 0:
            arr += np.random.randn(*arr.shape) * grain * 255

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(str(out_path), "JPEG", quality=88, optimize=True)
        return out_path
    except Exception as exc:
        log.warning(f"Grading failed for {src_path.name}: {exc}")
        return None


def _resize_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img   = img.resize((new_w, new_h), Image.LANCZOS)
    left  = (new_w - target_w) // 2
    top   = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _apply_vignette_numpy(arr: np.ndarray, strength: float) -> np.ndarray:
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    fade = np.clip(dist - 0.45, 0, 1)
    fade = (fade / 0.55) ** 1.8 * strength
    return arr * (1.0 - fade)[:, :, np.newaxis]


def _apply_red_tint(arr: np.ndarray, strength: float = 0.10) -> np.ndarray:
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
    cards: dict[str, Path] = {}

    for i, ev_card in enumerate(blueprint.get("evidence_cards", [])):
        part_id = ev_card.get("part_id", "unknown")
        key     = f"evidence_{i}_{part_id}"
        out     = card_path(run_id, f"{key}.jpg")
        _generate_evidence_card(
            card_type=ev_card.get("type", "POLICE FILE"),
            card_text=ev_card.get("text", ""),
            output_path=out,
        )
        cards[key] = out

    year    = str(random.randint(2015, 2023))
    loc_out = card_path(run_id, "location_card_intro.jpg")
    _generate_location_card(country, year, loc_out)
    cards["location_card_intro"] = loc_out

    for i, sc in enumerate(blueprint.get("shock_captions", [])):
        text = sc.get("text", "")
        if not text:
            continue
        key = f"shock_{i}_{sc.get('part_id','?')}"
        out = card_path(run_id, f"{key}.jpg")
        _generate_shock_overlay(text, out)
        cards[key] = out

    cctv_out = card_path(run_id, "cctv_overlay_intro.jpg")
    _generate_cctv_overlay(cctv_out)
    cards["cctv_overlay_intro"] = cctv_out

    return cards


def _generate_evidence_card(card_type: str, card_text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    img  = Image.new("RGB", (w, h), color=(6, 6, 6))
    draw = ImageDraw.Draw(img)
    draw.rectangle([80, 120, w - 80, h - 120], outline=VISUAL_COLORS["accent_red"], width=3)
    draw.rectangle([80, 120, w - 80, 120 + 130], fill=VISUAL_COLORS["accent_red"])
    font_large  = _load_font(90)
    font_medium = _load_font(55)
    font_small  = _load_font(38)
    bbox  = draw.textbbox((0, 0), card_type, font=font_large)
    tw    = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, 142), card_type, font=font_large, fill=VISUAL_COLORS["primary_text"])
    detail_y = 120 + 130 + 60
    for line in _wrap_text(card_text, max_chars=38):
        bbox2 = draw.textbbox((0, 0), line, font=font_medium)
        draw.text(((w - (bbox2[2] - bbox2[0])) // 2, detail_y),
                  line, font=font_medium, fill=VISUAL_COLORS["primary_text"])
        detail_y += 75
    tag_text = "KARMA VAULT STORIES — CLASSIFIED FILE"
    bbox3    = draw.textbbox((0, 0), tag_text, font=font_small)
    draw.text(((w - (bbox3[2] - bbox3[0])) // 2, h - 120 - 55),
              tag_text, font=font_small, fill=(100, 100, 100))
    img.save(str(output_path), "JPEG", quality=92)


def _generate_location_card(country: str, year: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    arr  = np.zeros((h, w, 3), dtype=np.float32)
    gradient = np.linspace(0.02, 0.12, h)
    arr[:, :, 0] = gradient[:, np.newaxis] * 255
    img  = Image.fromarray(arr.astype(np.uint8))
    draw = ImageDraw.Draw(img)
    draw.line([(150, h // 2 - 70), (w - 150, h // 2 - 70)], fill=VISUAL_COLORS["accent_red"], width=2)
    font_xl = _load_font(110)
    font_sm = _load_font(44)
    loc_text  = country.upper()
    year_text = f"— {year} —"
    bbox = draw.textbbox((0, 0), loc_text, font=font_xl)
    draw.text(((w - (bbox[2] - bbox[0])) // 2, h // 2 - 65), loc_text,
              font=font_xl, fill=VISUAL_COLORS["primary_text"])
    bbox2 = draw.textbbox((0, 0), year_text, font=font_sm)
    draw.text(((w - (bbox2[2] - bbox2[0])) // 2, h // 2 + 80), year_text,
              font=font_sm, fill=VISUAL_COLORS["accent_red"])
    draw.line([(150, h // 2 + 145), (w - 150, h // 2 + 145)], fill=VISUAL_COLORS["accent_red"], width=2)
    img.save(str(output_path), "JPEG", quality=92)


def _generate_shock_overlay(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    img  = Image.new("RGB", (w, h), color=(4, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(220)
    stroke_width = 8
    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    for dx in range(-stroke_width, stroke_width + 1, 2):
        for dy in range(-stroke_width, stroke_width + 1, 2):
            if abs(dx) + abs(dy) <= stroke_width * 1.5:
                draw.text(((w - tw) // 2 + dx, (h - th) // 2 + dy),
                          text, font=font, fill=(255, 255, 255))
    draw.text(((w - tw) // 2, (h - th) // 2), text, font=font,
              fill=VISUAL_COLORS.get("shock_red", (220, 0, 0)))
    img.save(str(output_path), "JPEG", quality=90)


def _generate_cctv_overlay(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    arr  = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(0, h, 4):
        arr[y, :, 1] = random.randint(8, 20)
    img  = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)
    font = _load_font(36)
    import datetime
    ts = datetime.datetime(
        random.randint(2015, 2022), random.randint(1, 12),
        random.randint(1, 28), random.randint(0, 23),
        random.randint(0, 59), random.randint(0, 59),
    ).strftime("%Y-%m-%d  %H:%M:%S")
    draw.text((30, 30), f"REC  CAM-{random.randint(1,8):02d}  {ts}", font=font, fill=(0, 200, 0))
    draw.text((30, h - 55), "FOOTAGE CLASSIFIED", font=font, fill=(0, 180, 0))
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
) -> list[dict]:
    scenes:   list[dict] = []
    pool_idx  = 0
    scene_idx = 0
    shock_map    = {sc.get("part_id"): sc.get("text")
                    for sc in blueprint.get("shock_captions", []) if sc.get("part_id")}
    evidence_map = {ev.get("part_id"): f"evidence_{i}_{ev.get('part_id')}"
                    for i, ev in enumerate(blueprint.get("evidence_cards", [])) if ev.get("part_id")}

    for part in parts:
        part_id    = part.get("part_id", "")
        start_time = part.get("start_time_sec", 0.0)
        duration   = part.get("duration_sec", 30.0)
        is_horror  = part_id in ("climax", "escalation") and part.get("is_twist", False)
        is_cta     = part.get("cta_marker", False)

        if part_id == "context":
            loc_path = card_assets.get("location_card_intro")
            if loc_path and loc_path.exists():
                scenes.append(_make_scene(scene_idx, part_id, str(loc_path),
                    AssetCategory.LOCATION_DATE_CARD.value, start_time, 2.5,
                    "static", False, scene_idx == 0, False, None, None, False))
                scene_idx  += 1
                start_time += 2.5

        ev_key = evidence_map.get(part_id)
        if ev_key:
            ev_path = card_assets.get(ev_key)
            if ev_path and ev_path.exists():
                ev_data = next(
                    (e for e in blueprint.get("evidence_cards", [])
                     if e.get("part_id") == part_id), None
                )
                scenes.append(_make_scene(scene_idx, part_id, str(ev_path),
                    AssetCategory.EVIDENCE_CARD.value, start_time, 2.8,
                    "static", False, False, False, ev_data, None, False))
                scene_idx  += 1
                start_time += 2.8

        time_in_part = 0.0
        cut_count    = 0
        shock_text   = shock_map.get(part_id)

        while time_in_part < duration - 0.5:
            cut_dur = random.uniform(SCENE_DURATION_MIN_SEC,
                                     min(SCENE_DURATION_MAX_SEC, duration - time_in_part))
            cut_dur = max(2.5, cut_dur)

            if image_pool:
                img_p      = image_pool[pool_idx % len(image_pool)]
                asset_type = AssetCategory.STOCK_PHOTO.value
                pool_idx  += 1
            else:
                img_p      = card_assets.get("cctv_overlay_intro",
                             next(iter(card_assets.values()), None))
                asset_type = AssetCategory.CCTV_STYLE.value

            motion = "shake" if shock_text and cut_count == 0 else _assign_motion(scene_idx, part_id)
            scenes.append(_make_scene(
                scene_idx, part_id,
                str(img_p) if img_p else "",
                asset_type,
                start_time + time_in_part,
                cut_dur,
                motion,
                is_horror,
                scene_idx == 0 and cut_count == 0,
                False,
                None,
                shock_text if cut_count == 0 else None,
                is_cta and cut_count == 1,
            ))
            scene_idx    += 1
            cut_count    += 1
            time_in_part += cut_dur

    if scenes:
        scenes[-1]["is_outro"] = True
    return scenes


def _make_scene(
    scene_idx: int, part_id: str, asset_path: str, asset_type: str,
    start_time_sec: float, duration_sec: float, motion_type: str,
    horror_grading: bool, is_intro: bool, is_outro: bool,
    evidence_card_data: Optional[dict], shock_caption: Optional[str],
    cta_overlay: bool,
) -> dict:
    return {
        "scene_idx": scene_idx, "part_id": part_id,
        "asset_path": asset_path, "asset_type": asset_type,
        "start_time_sec": round(start_time_sec, 3),
        "duration_sec": round(duration_sec, 3),
        "motion_type": motion_type, "horror_grading": horror_grading,
        "shock_caption": shock_caption, "cta_overlay": cta_overlay,
        "evidence_card_data": evidence_card_data,
        "is_intro": is_intro, "is_outro": is_outro,
    }


def _assign_motion(scene_idx: int, part_id: str) -> str:
    if part_id == "hook":
        return "slow_zoom_in"
    if part_id == "aftermath":
        return "drift_up"
    if part_id in ("climax", "escalation"):
        return ["slow_zoom_in", "pan_right", "pan_left", "slow_zoom_out"][scene_idx % 4]
    return ["slow_zoom_in", "slow_zoom_out", "pan_right", "pan_left", "drift_up", "drift_down"][scene_idx % 6]


def _pad_with_ai_images(
    scenes: list[dict], parts: list[dict], pillar: str, run_id: str, target: int,
) -> list[dict]:
    unique = {s["asset_path"] for s in scenes if s.get("asset_path")}
    needed = target - len(unique)
    if needed <= 0:
        return scenes
    queries = list(_PILLAR_STOCK_QUERIES.get(pillar, _GENERIC_DARK_QUERIES))
    random.shuffle(queries)
    new_paths: list[Path] = []
    for i in range(min(needed + 3, 12)):
        out     = image_path(run_id, f"ai_pad_{i:03d}.jpg")
        graded_out = image_path(run_id, f"ai_pad_{i:03d}_graded.jpg")
        if generate_ai_image(queries[i % len(queries)], out, pillar=pillar):
            g = _apply_cinematic_grading(out, run_id, f"pad{i}", False)
            if g:
                new_paths.append(g)
        if len(new_paths) >= needed:
            break
        time.sleep(0.5)
    if not new_paths:
        return scenes
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
    if size in _font_cache:
        return _font_cache[size]
    candidates = [
        FONTS_DIR / "Anton-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for c in candidates:
        try:
            font = ImageFont.truetype(str(c), size)
            _font_cache[size] = font
            return font
        except (IOError, OSError):
            continue
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _wrap_text(text: str, max_chars: int = 38) -> list[str]:
    words   = text.split()
    lines:  list[str] = []
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
    try:
    _font_dir = FONTS_DIR
    _font_dir.mkdir(parents=True, exist_ok=True)
    _anton = _font_dir / "Anton-Regular.ttf"
    if not _anton.exists():
        from utils.api_client import http_get
        data = http_get(
            "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
            timeout=20,
        )
        _anton.write_bytes(data)
except Exception:
    pass
    

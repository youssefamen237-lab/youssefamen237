"""
engines/script_writer.py
Karma Vault Stories — Viral Suspense Script Writer Engine
Generates fully original English dark documentary scripts following the
mandatory 7-part viral formula. Output is a structured JSON blueprint
consumed directly by voice, scene builder, renderer, and shorts engines.
No plain-text-only output. Every field is machine-readable.
"""

import json
import random
import re
from datetime import datetime, timezone
from typing import Optional

from config.constants import (
    ContentPillar, SCRIPT_PARTS, SCRIPT_MANDATORY_RULES,
    SCRIPT_BLUEPRINT_KEYS, SFXMarker, SHOCK_CAPTION_POOL,
    EVIDENCE_CARD_TYPES, CHANNEL_NAME,
    LONG_VIDEO_MIN_MINUTES, LONG_VIDEO_MAX_MINUTES,
    SHORT_VIDEO_MIN_SEC, SHORT_VIDEO_MAX_SEC,
)
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import load_heuristics
from utils.api_client import call_writing_model

log = get_logger(__name__)

# Documentary narration pace: ~140 words per minute (measured, deliberate delivery)
_WORDS_PER_MINUTE = 140
_LONG_VIDEO_MIN_WORDS = int(LONG_VIDEO_MIN_MINUTES * _WORDS_PER_MINUTE)   # 1120
_LONG_VIDEO_MAX_WORDS = int(LONG_VIDEO_MAX_MINUTES * _WORDS_PER_MINUTE)  # 1680
_SHORT_CLIP_TARGET_WORDS = 95   # ~40 seconds at 140wpm


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_script_writer(ctx: DailyRunContext) -> DailyRunContext:
    """
    Generates the full script blueprint for ctx.selected_story.
    Populates ctx.script_blueprint and ctx.voice_gender.
    """
    if not ctx.selected_story:
        log.error("No selected story — cannot write script.")
        return ctx

    log.info(f"Script writer starting for: '{ctx.selected_story.title[:70]}'")
    heuristics = load_heuristics()

    # Select voice gender based on analytics performance
    ctx.voice_gender = _select_voice_gender(heuristics)
    log.info(f"Voice gender selected: {ctx.voice_gender}")

    # Attempt full script generation with fallback to simplified generation
    blueprint = None
    for attempt in range(1, 4):
        log.info(f"Script generation attempt {attempt}/3...")
        try:
            raw = _call_script_ai(ctx.selected_story, ctx.voice_gender, attempt)
            blueprint = _parse_script_blueprint(raw)
            if blueprint and _validate_blueprint(blueprint):
                break
            log.warning(f"Attempt {attempt} produced invalid blueprint — retrying.")
            blueprint = None
        except Exception as exc:
            log.warning(f"Script attempt {attempt} failed: {exc}")

    if not blueprint:
        log.warning("All AI attempts failed or produced invalid output. "
                    "Constructing emergency structured blueprint.")
        blueprint = _build_emergency_blueprint(ctx.selected_story, ctx.voice_gender)

    # Post-process: enrich with SFX markers, evidence cards, shock captions
    blueprint = _enrich_blueprint(blueprint, ctx.selected_story)

    # Attach voice gender and timing data
    blueprint["voice_gender"] = ctx.voice_gender
    blueprint["estimated_duration_sec"] = _estimate_duration_sec(blueprint)
    blueprint["run_id"] = ctx.run_id
    blueprint["generated_at"] = datetime.now(timezone.utc).isoformat()

    ctx.script_blueprint = blueprint
    ctx.selected_story.script_blueprint = blueprint

    total_words = sum(
        len((p.get("narration") or "").split())
        for p in blueprint.get("parts", [])
    )
    log.info(
        f"Script complete. Parts={len(blueprint.get('parts', []))}, "
        f"Words={total_words}, "
        f"Est. duration={blueprint['estimated_duration_sec']}s, "
        f"Twists={len([p for p in blueprint.get('parts',[]) if p.get('is_twist')])}"
    )
    ctx.mark_stage("script_writer")
    return ctx


# ─────────────────────────────────────────────
# AI SCRIPT GENERATION CALL
# ─────────────────────────────────────────────

def _call_script_ai(
    story: StoryCandidate,
    voice_gender: str,
    attempt: int,
) -> str:
    system_prompt = _build_system_prompt()
    user_prompt   = _build_user_prompt(story, voice_gender, attempt)

    # Allow more tokens for full script
    return call_writing_model(
        system_prompt,
        user_prompt,
        max_tokens=4000,
        temperature=0.82,
        json_output=True,
    )


def _build_system_prompt() -> str:
    return f"""You are the head script writer for "{CHANNEL_NAME}", a faceless dark documentary YouTube channel.

Your scripts are studied viral content — never generic AI output. Every sentence creates tension. Every paragraph ends wanting more.

MANDATORY SCRIPT ARCHITECTURE (7 parts, in exact order):

PART 1 — hook: The single strongest shock sentence in the entire story. No context yet. Pure hook. Narrator speaks immediately. Must make viewer physically stop scrolling. (Target: 60-90 words)

PART 2 — context: Quick essential setup. Who, where, when. No backstory overload. Just enough to ground the shock. (Target: 100-150 words)

PART 3 — normality: Life before collapse. Make viewer care about the person or situation. Calm before the storm. This is where humans connect. (Target: 150-200 words)

PART 4 — first_sign: The first crack in reality. Something is wrong. Subtle but unmistakable. End this part on a micro-cliffhanger. (Target: 150-200 words)

PART 5 — escalation: The cascade. Each paragraph reveals something worse. Minimum 3 distinct revelations. One micro-cliffhanger every ~30 seconds of narration. This is the engine of the video. (Target: 350-500 words)

PART 6 — climax: The major payoff. The full truth, the karma, the horror, the reveal the viewer was promised. Maximum impact. No holding back. (Target: 200-280 words)

PART 7 — aftermath: What happened next. What it means. End with a haunting closing line. Then the subscribe bait: natural, not forced. Final line: "Tomorrow's file is darker." (Target: 100-150 words)

MANDATORY RULES:
- Minimum 3 twists total across all parts
- Micro-cliffhanger every ~30 seconds (approximately every 70 words)
- Conversational documentary English — the narrator is a trusted investigator
- Emotional human language — viewers should feel dread, sympathy, shock
- ZERO repetitive filler ("as we mentioned", "as stated above", "in conclusion")
- ZERO robotic morals ("and that's why we should always", "the lesson here is")
- ZERO generic AI summaries
- Every part must flow naturally into the next
- The story must feel TRUE and SPECIFIC — real names, real places, real details (or convincingly real)
- Target total word count: {_LONG_VIDEO_MIN_WORDS}–{_LONG_VIDEO_MAX_WORDS} words across all 7 parts

SHORT CLIP EXTRACTION:
Identify the single most viral 35-50 second segment anywhere in the script (usually within escalation or climax). This will become the YouTube Short. Write a condensed standalone version (~{_SHORT_CLIP_TARGET_WORDS} words) that:
- Opens with an immediate shock hook (no context needed)
- Has one major reveal
- Ends with "Watch the full story on the channel."

SCENE PROMPTS:
For each part, write a visual scene prompt (for stock image/video search and AI image generation):
- Dark, cinematic, specific
- Include mood, lighting, subject
- 1-2 sentences
- Example: "Dimly lit hospital corridor at night, flickering fluorescent light, empty wheelchair casting long shadow, fog at floor level."

EVIDENCE CARDS:
Include 2-4 evidence card moments. These are documentary-style title cards that flash on screen:
- POLICE FILE | CAIRO — 2019
- WITNESS STATEMENT | UNVERIFIED
- HOSPITAL RECORD | CLASSIFIED

SHOCK CAPTIONS:
At the 2-3 biggest twist moments, mark a shock caption (giant text overlay):
Must be 1-4 words from: {json.dumps(random.sample(SHOCK_CAPTION_POOL, 8))}
Or invent one that fits the story perfectly.

OUTPUT FORMAT:
Return ONLY a valid JSON object. No markdown. No explanation. No text outside the JSON.
The JSON must exactly match the schema provided in the user message."""


def _build_user_prompt(
    story: StoryCandidate, voice_gender: str, attempt: int
) -> str:
    # On retry attempts, add escalating specificity instructions
    retry_note = ""
    if attempt == 2:
        retry_note = "\n\nIMPORTANT: Previous attempt failed validation. Ensure ALL parts have non-empty narration text and ALL required JSON keys are present."
    elif attempt == 3:
        retry_note = "\n\nFINAL ATTEMPT: Output only valid JSON. Every part must have narration > 50 words. Include all required fields."

    # Determine intro label for this pillar/country
    label = story.story_label.replace("{COUNTRY}", story.country)

    schema = {
        "title": "Primary video title string (compelling, 60-80 chars)",
        "backup_title": "Alternative title string",
        "story_label": label,
        "country": story.country,
        "pillar": story.pillar,
        "intro_label_style": "random choice from: bold_red | stamp_reveal | typewriter",
        "parts": [
            {
                "part_id": "hook|context|normality|first_sign|escalation|climax|aftermath",
                "part_name": "human-readable part name",
                "narration": "FULL narration text for this part (narrator speaks this verbatim)",
                "scene_prompt": "dark cinematic visual description for this part",
                "sfx_marker": "boom_impact|tension_riser|heartbeat_pulse|glitch_texture|whisper_ambient|dark_ambient_bed|null",
                "is_twist": "true if this part contains a major twist",
                "shock_caption": "1-4 word shock text OR null",
                "evidence_card": {"type": "POLICE FILE etc", "text": "card content"} ,
                "cta_marker": "true only for EXACTLY ONE part (after first major twist)"
            }
        ],
        "short_clip": {
            "source_part_id": "which part the short comes from",
            "narration": f"Standalone {_SHORT_CLIP_TARGET_WORDS}-word short clip narration",
            "scene_prompt": "vertical 9:16 visual description for the short",
            "hook_caption": "2-4 word opening text overlay for the short",
            "duration_target_sec": 42
        },
        "shock_captions": [
            {"text": "SHOCK TEXT", "part_id": "which part"}
        ],
        "evidence_cards": [
            {"type": "POLICE FILE", "text": "card detail text", "part_id": "which part"}
        ]
    }

    return f"""Write a complete dark documentary script for Karma Vault Stories.

STORY INPUT:
Title: {story.title}
Country: {story.country}
Pillar: {story.pillar}
Story Label: {label}
Voice: {voice_gender} narrator
Summary / Source Material:
{(story.raw_content or story.summary or story.title)[:1200]}

OUTPUT SCHEMA (return this exact structure as JSON):
{json.dumps(schema, indent=2)}

CRITICAL REQUIREMENTS:
1. parts array must have EXACTLY 7 items in order: hook, context, normality, first_sign, escalation, climax, aftermath
2. Each part's narration must be substantial — hook minimum 60 words, escalation minimum 350 words
3. Total narration word count across all 7 parts: {_LONG_VIDEO_MIN_WORDS} to {_LONG_VIDEO_MAX_WORDS} words
4. short_clip.narration must be self-contained and approximately {_SHORT_CLIP_TARGET_WORDS} words
5. At least 3 parts must have is_twist: true
6. Exactly 1 part must have cta_marker: true (place it after the first twist)
7. Include 2-4 evidence_cards total
8. Include 2-3 shock_captions at major twist moments
9. Make the story SPECIFIC — use specific names, dates, locations (if unknown, create plausible real-feeling ones consistent with the source country)
10. The title must be emotionally compelling and 60-80 characters{retry_note}

Return ONLY the JSON object. Begin with {{ and end with }}."""


# ─────────────────────────────────────────────
# BLUEPRINT PARSING & VALIDATION
# ─────────────────────────────────────────────

def _parse_script_blueprint(raw: str) -> Optional[dict]:
    """
    Robustly extracts and parses the JSON blueprint from the AI response.
    Handles markdown fences, leading text, and trailing garbage.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip markdown code fences
    if "```" in text:
        for fence_content in text.split("```"):
            fence_content = fence_content.strip()
            if fence_content.startswith("json"):
                fence_content = fence_content[4:].strip()
            if fence_content.startswith("{"):
                text = fence_content
                break

    # Find JSON object boundaries
    start = text.find("{")
    if start == -1:
        return None

    # Find matching closing brace
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        # Try parsing the whole remaining string
        text = text[start:]
    else:
        text = text[start:end]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning(f"JSON parse error: {exc}. Attempting repair...")
        return _attempt_json_repair(text)


def _attempt_json_repair(text: str) -> Optional[dict]:
    """Last-resort JSON repair for common AI output issues."""
    # Fix unescaped newlines inside strings
    text = re.sub(r'(?<!\\)\n', ' ', text)
    # Fix trailing commas before closing braces/brackets
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    try:
        return json.loads(text)
    except Exception:
        return None


def _validate_blueprint(blueprint: dict) -> bool:
    """
    Returns True only if the blueprint has all required structure
    with non-trivial content. Returns False if major fields are missing.
    """
    if not blueprint or not isinstance(blueprint, dict):
        return False

    parts = blueprint.get("parts", [])
    if not isinstance(parts, list) or len(parts) < 5:
        log.warning(f"Blueprint invalid: only {len(parts)} parts (need ≥5).")
        return False

    # Each part must have narration
    for i, part in enumerate(parts):
        narration = (part.get("narration") or "").strip()
        if len(narration.split()) < 30:
            log.warning(f"Part {i} ({part.get('part_id','?')}) narration too short: "
                        f"{len(narration.split())} words.")
            return False

    # Must have title
    if not blueprint.get("title", "").strip():
        log.warning("Blueprint invalid: missing title.")
        return False

    # Must have short_clip with narration
    short_clip = blueprint.get("short_clip", {})
    if not short_clip or not (short_clip.get("narration") or "").strip():
        log.warning("Blueprint invalid: missing short_clip narration.")
        return False

    total_words = sum(
        len((p.get("narration") or "").split()) for p in parts
    )
    if total_words < _LONG_VIDEO_MIN_WORDS * 0.7:
        log.warning(f"Blueprint invalid: total words={total_words}, "
                    f"minimum={int(_LONG_VIDEO_MIN_WORDS * 0.7)}.")
        return False

    return True


# ─────────────────────────────────────────────
# BLUEPRINT ENRICHMENT
# ─────────────────────────────────────────────

def _enrich_blueprint(blueprint: dict, story: StoryCandidate) -> dict:
    """
    Post-processes the AI blueprint to ensure:
    - All 7 part IDs are present and correctly ordered
    - SFX markers are set for all parts
    - Exactly one CTA marker exists
    - shock_captions list is populated
    - evidence_cards list is populated
    - short_clip block is well-formed
    - Intro label style is set
    """
    blueprint = _normalize_parts(blueprint)
    blueprint = _ensure_sfx_markers(blueprint)
    blueprint = _ensure_cta_marker(blueprint)
    blueprint = _ensure_shock_captions(blueprint, story)
    blueprint = _ensure_evidence_cards(blueprint, story)
    blueprint = _ensure_short_clip(blueprint)
    blueprint = _set_intro_label(blueprint, story)
    return blueprint


def _normalize_parts(blueprint: dict) -> dict:
    """Ensures exactly 7 parts exist in correct order with correct part_ids."""
    parts = blueprint.get("parts", [])
    existing_ids = {p.get("part_id", ""): p for p in parts}

    ordered_parts = []
    for i, part_id in enumerate(SCRIPT_PARTS):
        if part_id in existing_ids:
            p = dict(existing_ids[part_id])
            p["part_id"] = part_id
            if "word_count" not in p:
                p["word_count"] = len((p.get("narration") or "").split())
        else:
            # This part was missing from AI output — create a minimal stand-in
            # using adjacent narration if available
            log.warning(f"Part '{part_id}' missing from AI blueprint — inserting stub.")
            stub_narration = _generate_stub_narration(
                part_id, blueprint.get("title", ""), blueprint.get("country", "Unknown")
            )
            p = {
                "part_id":     part_id,
                "part_name":   part_id.replace("_", " ").title(),
                "narration":   stub_narration,
                "scene_prompt": "Dark cinematic scene, dramatic lighting, deep shadows.",
                "sfx_marker":  None,
                "is_twist":    part_id in ("escalation", "climax"),
                "shock_caption": None,
                "evidence_card": None,
                "cta_marker":  False,
                "word_count":  len(stub_narration.split()),
            }
        ordered_parts.append(p)

    blueprint["parts"] = ordered_parts
    return blueprint


def _generate_stub_narration(part_id: str, title: str, country: str) -> str:
    """Minimal stub narration when a part is missing from AI output."""
    stubs = {
        "hook":        f"What happened in {country} will stay with you long after this video ends. This is a story that was never supposed to be told.",
        "context":     f"The case began in {country}, in circumstances that seemed ordinary at first. But nothing about this story was ordinary.",
        "normality":   f"For years, life had proceeded without incident. No one who knew the people involved suspected that anything was wrong. That was about to change.",
        "first_sign":  f"The first warning sign was dismissed as coincidence. Looking back, everyone who was there agreed — the signs had been there all along.",
        "escalation":  f"What investigators uncovered next would rewrite everything they thought they knew. Each new piece of evidence pointed to something darker, something more deliberate. The truth was emerging, piece by piece, and it was worse than anyone had imagined. Three separate witnesses confirmed the same detail independently. Nobody could explain how it was possible.",
        "climax":      f"Then came the revelation that broke the case wide open. The full truth, when it finally emerged, silenced everyone in the room. This was not an accident. This was not a coincidence. This had been planned.",
        "aftermath":   f"The case was eventually resolved, but the questions it raised have never fully gone away. For those who were there, nothing was ever the same. Subscribe for daily dark files. Tomorrow's file is darker.",
    }
    return stubs.get(part_id, f"The story continued to unfold in {country}.")


def _ensure_sfx_markers(blueprint: dict) -> dict:
    """Assigns appropriate SFX markers to each part based on its role."""
    sfx_map = {
        "hook":        SFXMarker.INTRO_SLAM.value,
        "context":     SFXMarker.DARK_AMBIENT_BED.value,
        "normality":   SFXMarker.DARK_AMBIENT_BED.value,
        "first_sign":  SFXMarker.TENSION_RISER.value,
        "escalation":  SFXMarker.HEARTBEAT_PULSE.value,
        "climax":      SFXMarker.BOOM_IMPACT.value,
        "aftermath":   SFXMarker.OUTRO_DARK.value,
    }
    for part in blueprint.get("parts", []):
        if not part.get("sfx_marker"):
            part["sfx_marker"] = sfx_map.get(part["part_id"], SFXMarker.DARK_AMBIENT_BED.value)
    return blueprint


def _ensure_cta_marker(blueprint: dict) -> dict:
    """Ensures exactly one CTA marker is set — always after the first twist."""
    parts = blueprint.get("parts", [])
    cta_count = sum(1 for p in parts if p.get("cta_marker"))

    if cta_count == 1:
        return blueprint  # already correct

    # Clear all existing
    for p in parts:
        p["cta_marker"] = False

    # Place CTA at first twist, or default to escalation
    twist_parts = [p for p in parts if p.get("is_twist")]
    if twist_parts:
        twist_parts[0]["cta_marker"] = True
    else:
        # Default: place on escalation
        for p in parts:
            if p["part_id"] == "escalation":
                p["cta_marker"] = True
                break

    return blueprint


def _ensure_shock_captions(blueprint: dict, story: StoryCandidate) -> dict:
    """
    Ensures 2-3 shock captions exist at major twist moments.
    Creates them if the AI didn't produce them or produced too few.
    """
    existing = blueprint.get("shock_captions", [])
    if not isinstance(existing, list):
        existing = []

    # Filter valid captions
    valid = [
        c for c in existing
        if isinstance(c, dict) and c.get("text") and c.get("part_id")
    ]

    if len(valid) >= 2:
        blueprint["shock_captions"] = valid[:4]
        return blueprint

    # Generate captions at twist positions
    twist_parts = [
        p["part_id"] for p in blueprint.get("parts", [])
        if p.get("is_twist")
    ]
    if not twist_parts:
        twist_parts = ["escalation", "climax"]

    # Pick captions from pool that fit the story
    pool = list(SHOCK_CAPTION_POOL)
    random.shuffle(pool)
    for i, part_id in enumerate(twist_parts[:3]):
        if len(valid) >= 3:
            break
        if not any(c.get("part_id") == part_id for c in valid):
            valid.append({
                "text": pool[i % len(pool)],
                "part_id": part_id,
            })

    blueprint["shock_captions"] = valid
    return blueprint


def _ensure_evidence_cards(blueprint: dict, story: StoryCandidate) -> dict:
    """Ensures 2-4 evidence cards exist with contextual content."""
    existing = blueprint.get("evidence_cards", [])
    if not isinstance(existing, list):
        existing = []

    valid = [
        c for c in existing
        if isinstance(c, dict) and c.get("type") and c.get("text")
    ]

    if len(valid) >= 2:
        blueprint["evidence_cards"] = valid[:4]
        return blueprint

    # Generate evidence cards based on pillar and country
    year = str(random.randint(2015, 2023))
    country = story.country if story.country not in ("Unknown", "global") else "UNDISCLOSED LOCATION"

    templates = [
        {"type": "POLICE FILE",      "text": f"{country.upper()} — {year}",                 "part_id": "context"},
        {"type": "WITNESS REPORT",   "text": f"TESTIMONY RECORDED | {year}",                 "part_id": "first_sign"},
        {"type": "INVESTIGATION LOG","text": f"CASE FILED — DETAILS RESTRICTED",             "part_id": "escalation"},
        {"type": "HOSPITAL RECORD",  "text": f"ADMISSION DATE: WITHHELD",                    "part_id": "climax"},
        {"type": "COURT DOCUMENT",   "text": f"PROCEEDING: {country.upper()} | {year}",      "part_id": "aftermath"},
        {"type": "CCTV FOOTAGE",     "text": f"TIMESTAMP: {year} — {random.randint(0,23):02d}:{random.randint(0,59):02d}", "part_id": "escalation"},
    ]

    # Pick card types that match the pillar
    paranormal_types = {"WITNESS REPORT", "INVESTIGATION LOG", "POLICE FILE"}
    crime_types = {"POLICE FILE", "COURT DOCUMENT", "INVESTIGATION LOG", "CCTV FOOTAGE"}

    pool = templates if story.pillar not in (
        ContentPillar.PARANORMAL.value, ContentPillar.URBAN_LEGENDS.value
    ) else [t for t in templates if t["type"] in paranormal_types]

    if not pool:
        pool = templates

    random.shuffle(pool)
    needed = max(0, 2 - len(valid))
    for card in pool[:needed]:
        if not any(c.get("type") == card["type"] for c in valid):
            valid.append(card)

    blueprint["evidence_cards"] = valid[:4]
    return blueprint


def _ensure_short_clip(blueprint: dict) -> dict:
    """
    Validates/repairs the short_clip block.
    If the AI produced a usable short_clip, validate word count.
    If not, extract the most shocking sentences from escalation/climax.
    """
    short_clip = blueprint.get("short_clip")
    if isinstance(short_clip, dict):
        narration = (short_clip.get("narration") or "").strip()
        word_count = len(narration.split())
        if 60 <= word_count <= 150:
            # Valid — ensure all fields exist
            short_clip.setdefault("source_part_id", "escalation")
            short_clip.setdefault("scene_prompt", "Dramatic dark vertical cinematic, close-up, high contrast red and black.")
            short_clip.setdefault("hook_caption", "WATCH THIS")
            short_clip.setdefault("duration_target_sec", 42)
            blueprint["short_clip"] = short_clip
            return blueprint

    # Extract from escalation or climax
    source_part_id = "escalation"
    source_narration = ""
    for part_id in ("climax", "escalation", "first_sign"):
        for part in blueprint.get("parts", []):
            if part["part_id"] == part_id:
                source_narration = (part.get("narration") or "").strip()
                source_part_id = part_id
                break
        if source_narration:
            break

    # Extract first ~95 words + closing line
    words = source_narration.split()
    short_narration_words = words[:_SHORT_CLIP_TARGET_WORDS]
    short_narration = " ".join(short_narration_words)
    if not short_narration.endswith("."):
        # Find last sentence boundary
        last_dot = short_narration.rfind(".")
        if last_dot > len(short_narration) * 0.5:
            short_narration = short_narration[:last_dot + 1]
    short_narration += " Watch the full story on the channel."

    blueprint["short_clip"] = {
        "source_part_id":  source_part_id,
        "narration":       short_narration,
        "scene_prompt":    "Dramatic dark vertical 9:16 scene, intense close-up, high contrast red and black shadows.",
        "hook_caption":    "WAIT FOR IT",
        "duration_target_sec": 42,
    }
    return blueprint


def _set_intro_label(blueprint: dict, story: StoryCandidate) -> dict:
    """Sets the intro_label_style if not already set."""
    if not blueprint.get("intro_label_style"):
        styles = ["bold_red", "stamp_reveal", "typewriter"]
        blueprint["intro_label_style"] = random.choice(styles)
    if not blueprint.get("story_label"):
        blueprint["story_label"] = story.story_label
    return blueprint


# ─────────────────────────────────────────────
# DURATION ESTIMATION
# ─────────────────────────────────────────────

def _estimate_duration_sec(blueprint: dict) -> int:
    """Estimates video duration from total narration word count."""
    total_words = sum(
        len((p.get("narration") or "").split())
        for p in blueprint.get("parts", [])
    )
    # 140 wpm + ~15% for natural pauses between sections
    raw_sec = int((total_words / _WORDS_PER_MINUTE) * 60 * 1.15)
    return max(
        LONG_VIDEO_MIN_MINUTES * 60,
        min(raw_sec, LONG_VIDEO_MAX_MINUTES * 60)
    )


# ─────────────────────────────────────────────
# VOICE GENDER SELECTION
# ─────────────────────────────────────────────

def _select_voice_gender(heuristics: dict) -> str:
    """
    Selects voice gender based on analytics performance data.
    Falls back to weighted random if no performance data exists.
    """
    perf = heuristics.get("voice_performance", {})
    male_score   = perf.get("male",   0.5)
    female_score = perf.get("female", 0.5)
    total = male_score + female_score

    if total == 0:
        return random.choice(["male", "female"])

    # Weighted random: better-performing voice gets selected more often
    # but not exclusively (always some rotation)
    male_prob = 0.3 + 0.4 * (male_score / total)   # range: [0.3, 0.7]

    return "male" if random.random() < male_prob else "female"


# ─────────────────────────────────────────────
# EMERGENCY BLUEPRINT (all AI providers down)
# ─────────────────────────────────────────────

def _build_emergency_blueprint(
    story: StoryCandidate, voice_gender: str
) -> dict:
    """
    Constructs a complete, word-count-compliant blueprint using rule-based templates
    when all AI calls fail. All parts meet the mandatory word-count floor.
    """
    log.warning("Building emergency rule-based script blueprint.")

    title   = story.title[:80]
    country = story.country if story.country not in ("Unknown","global") else "an undisclosed location"
    summary = (story.summary or story.raw_content or story.title)[:400]
    year    = str(random.randint(2018, 2023))

    # ── PART 1: HOOK (~85 words) ──────────────────────────────────
    hook_narration = (
        f"What I am about to tell you happened in {country}, and the people involved "
        f"fought for years to make sure it never became public. They nearly succeeded. "
        f"This is a case that investigators still speak about in lowered voices, "
        f"a file that was buried, reclassified, and buried again. "
        f"But the truth has a way of surfacing no matter how deep it is pushed. "
        f"Tonight, we open this file. "
        f"And once you hear what is inside, you will understand why they tried so hard to close it."
    )

    # ── PART 2: CONTEXT (~130 words) ─────────────────────────────
    context_narration = (
        f"To understand what happened, you need to understand the setting. "
        f"The year was {year}. The location: {country}. "
        f"On the surface, nothing about this case seemed unusual at first. "
        f"The circumstances appeared straightforward, the kind of situation "
        f"that gets filed away without a second look. "
        f"But embedded in the details — the kind of details that only become visible "
        f"in hindsight — was a pattern. "
        f"A pattern that investigators would later describe as deliberate. "
        f"Here is what the official record shows: {summary} "
        f"What the official record does not show is everything that came before, "
        f"and everything that was quietly removed after the fact. "
        f"That is the story we are telling tonight."
    )

    # ── PART 3: NORMALITY (~175 words) ──────────────────────────
    normality_narration = (
        f"Before everything collapsed, life in {country} moved at its ordinary pace. "
        f"The people at the center of this story were not remarkable in any visible way. "
        f"They had routines, obligations, relationships — the architecture of a normal life. "
        f"Neighbors described them as unremarkable. Colleagues said the same. "
        f"There were no obvious warning signs, no confrontations that anyone remembered, "
        f"no moment that stood out in retrospect as clearly wrong. "
        f"This is often how these stories go. The darkness does not announce itself. "
        f"It settles quietly alongside ordinary life and waits. "
        f"For months, possibly longer, everything appeared stable. "
        f"People who were close to the situation have said since that "
        f"they remember this period with a kind of grief — not for what happened, "
        f"but for how normal it all felt, "
        f"how completely ordinary the days were "
        f"right up until the moment they were not. "
        f"That moment was coming. Nobody knew how close."
    )

    # ── PART 4: FIRST SIGN (~160 words) ──────────────────────────
    first_sign_narration = (
        f"The first sign was easy to miss. In fact, almost everyone missed it. "
        f"A single anomaly. A detail that did not quite fit the established version of events. "
        f"At the time, it was noted and then set aside — explained away "
        f"as a clerical error, a misunderstanding, the kind of small inconsistency "
        f"that shows up in any complex situation. "
        f"But it was not a clerical error. "
        f"Investigators who later reviewed the timeline identified this moment "
        f"as the point at which the true sequence of events became detectable — "
        f"not obvious, not undeniable, but detectable. "
        f"If someone had pulled on that thread right then, "
        f"the full picture might have emerged sooner. "
        f"They did not pull on it. "
        f"The reason they did not is itself part of this story. "
        f"Because by the time the first sign was taken seriously, "
        f"the situation had already progressed into something much harder to stop. "
        f"We are just getting started."
    )

    # ── PART 5: ESCALATION (~420 words) ──────────────────────────
    esc_narration = (
        f"What came next arrived in rapid succession, the way these things always do "
        f"once the structure holding them back begins to fail. "
        f"The first development broke within days of the initial anomaly being flagged. "
        f"An independent review of the evidence revealed a contradiction "
        f"so fundamental that it called the entire previous account into question. "
        f"Two sets of documentation. Two entirely different versions of the same events. "
        f"Both appeared authentic. Only one could be true. "
        f"Investigators could not immediately determine which. "
        f"The second development was witnessed directly by multiple people "
        f"who had no prior connection to each other and no reason to coordinate their accounts. "
        f"When each was interviewed separately, the core of their testimony was identical. "
        f"But there was one detail — a single specific detail — "
        f"that each person described differently. "
        f"Not slightly differently. Incompatibly differently. "
        f"This inconsistency should have been impossible given what the official timeline claimed. "
        f"It meant that either the timeline was wrong, or something else had occurred "
        f"that had never been documented. "
        f"Neither option was acceptable. Both demanded explanation. "
        f"Neither received one at the time. "
        f"The third development came from a source no one expected. "
        f"Someone who had been present throughout, who had been silent, "
        f"who had every reason to remain silent, chose to speak. "
        f"What they revealed in a recorded statement that has never been released publicly "
        f"changed the shape of the investigation entirely. "
        f"The investigators who were in the room when it was played back "
        f"have described the experience in almost identical terms: "
        f"a long silence, then the slow recognition of what they were hearing, "
        f"and then the understanding — cold and immediate — "
        f"that everything they had assumed about this case was wrong. "
        f"Not slightly wrong. Fundamentally, structurally wrong. "
        f"The fourth thing — and this is the detail that still has not been fully explained — "
        f"was the discovery of a second location. "
        f"A place that no one had documented. A place that, according to official records, "
        f"did not exist. "
        f"But there it was. And what was found inside it "
        f"confirmed the worst interpretation of every piece of evidence gathered so far. "
        f"By this point, the case had grown beyond what anyone had anticipated. "
        f"What had begun as a single anomaly in a routine file "
        f"had become something no one in {country} was prepared to confront."
    )

    # ── PART 6: CLIMAX (~235 words) ──────────────────────────────
    climax_narration = (
        f"The final revelation came without warning and without mercy. "
        f"It arrived in the form of a document — a single document — "
        f"that had been withheld for reasons that were never officially explained "
        f"but that became obvious once its contents were known. "
        f"What it contained was not a surprise to everyone involved. "
        f"Some people had known, or suspected, for a long time. "
        f"They had made the calculation that exposure was worse than silence. "
        f"That calculation was wrong. "
        f"The truth that emerged was not the worst imaginable version of events. "
        f"It was something more specific, more deliberate, and in some ways more disturbing "
        f"than the worst version — because it was real. "
        f"It had happened. It had been witnessed and then covered. "
        f"It had been kept from the people who deserved to know. "
        f"The response in {country} when the full account became public "
        f"was not what the people who had managed the silence had predicted. "
        f"There was no chaos. There was something quieter and more corrosive: "
        f"the recognition that the systems designed to prevent exactly this kind of thing "
        f"had not only failed, but had, in some cases, been actively turned against the truth. "
        f"Those responsible were ultimately identified. "
        f"What happened to them is part of the public record. "
        f"But the case itself — the full account of what actually occurred in {country} — "
        f"remains only partially understood. "
        f"Because some files are still sealed. "
        f"And some people still will not talk."
    )

    # ── PART 7: AFTERMATH (~140 words) ────────────────────────────
    aftermath_narration = (
        f"In the months and years that followed, {country} processed what had happened "
        f"in the way that places always process things that resist easy explanation: "
        f"slowly, incompletely, and with a great deal left unspoken. "
        f"The case is categorized as resolved. "
        f"The people who were most directly affected by it would dispute that categorization. "
        f"There are questions that were never answered. "
        f"There are documents that were never recovered. "
        f"There are people who know more than they have said, "
        f"and who have decided that what they know should stay with them. "
        f"This is the nature of the darkest files. "
        f"They are never fully closed. "
        f"If this story stayed with you, subscribe — new dark files every single day. "
        f"Tomorrow's file is darker."
    )

    # Short clip from escalation peak (~95 words)
    esc_words  = esc_narration.split()
    short_words = esc_words[80:80 + _SHORT_CLIP_TARGET_WORDS]
    short_narration = " ".join(short_words) + " Watch the full story on the channel."

    parts = [
        {
            "part_id": "hook", "part_name": "Shock Hook",
            "narration": hook_narration,
            "scene_prompt": f"Black screen fading to dark room, single red spotlight, {country} at night, ominous atmosphere.",
            "sfx_marker": SFXMarker.INTRO_SLAM.value, "is_twist": False,
            "shock_caption": None, "evidence_card": None, "cta_marker": False,
            "word_count": len(hook_narration.split()),
        },
        {
            "part_id": "context", "part_name": "Quick Context",
            "narration": context_narration,
            "scene_prompt": f"Documentary establishing shot of {country}, overcast sky, deserted street, deep shadow.",
            "sfx_marker": SFXMarker.DARK_AMBIENT_BED.value, "is_twist": False,
            "shock_caption": None,
            "evidence_card": {"type": "POLICE FILE", "text": f"{country.upper()} — {year}"},
            "cta_marker": False, "word_count": len(context_narration.split()),
        },
        {
            "part_id": "normality", "part_name": "Life Before Collapse",
            "narration": normality_narration,
            "scene_prompt": f"Quiet street in {country}, warm but faintly unsettling color grade, ordinary life in motion.",
            "sfx_marker": SFXMarker.DARK_AMBIENT_BED.value, "is_twist": False,
            "shock_caption": None, "evidence_card": None, "cta_marker": False,
            "word_count": len(normality_narration.split()),
        },
        {
            "part_id": "first_sign", "part_name": "First Disturbing Sign",
            "narration": first_sign_narration,
            "scene_prompt": "Close-up of a door slightly ajar, dark hallway beyond, single flickering light source.",
            "sfx_marker": SFXMarker.TENSION_RISER.value, "is_twist": False,
            "shock_caption": None,
            "evidence_card": {"type": "WITNESS REPORT", "text": "TESTIMONY RECORDED — UNVERIFIED"},
            "cta_marker": True, "word_count": len(first_sign_narration.split()),
        },
        {
            "part_id": "escalation", "part_name": "Escalation Cascade",
            "narration": esc_narration,
            "scene_prompt": "Dark evidence board, scattered documents under red light, investigator silhouette, tension mounting.",
            "sfx_marker": SFXMarker.HEARTBEAT_PULSE.value, "is_twist": True,
            "shock_caption": random.choice(SHOCK_CAPTION_POOL),
            "evidence_card": {"type": "INVESTIGATION LOG", "text": "CASE STATUS: ACTIVE — DETAILS RESTRICTED"},
            "cta_marker": False, "word_count": len(esc_narration.split()),
        },
        {
            "part_id": "climax", "part_name": "Major Payoff",
            "narration": climax_narration,
            "scene_prompt": "Dramatic close-up, crimson ambient light, heavy shadows, revelation moment, shock and silence.",
            "sfx_marker": SFXMarker.BOOM_IMPACT.value, "is_twist": True,
            "shock_caption": random.choice(SHOCK_CAPTION_POOL),
            "evidence_card": None, "cta_marker": False,
            "word_count": len(climax_narration.split()),
        },
        {
            "part_id": "aftermath", "part_name": "Aftermath",
            "narration": aftermath_narration,
            "scene_prompt": "Dark outro fade, slow pan over empty room, text overlay: TOMORROW'S FILE IS DARKER.",
            "sfx_marker": SFXMarker.OUTRO_DARK.value, "is_twist": False,
            "shock_caption": None, "evidence_card": None, "cta_marker": False,
            "word_count": len(aftermath_narration.split()),
        },
    ]

    return {
        "title":             title,
        "backup_title":      f"The Hidden Truth of {story.country}: This File Was Buried",
        "story_label":       story.story_label,
        "country":           story.country,
        "pillar":            story.pillar,
        "intro_label_style": random.choice(["bold_red", "stamp_reveal", "typewriter"]),
        "voice_gender":      voice_gender,
        "parts":             parts,
        "short_clip": {
            "source_part_id":    "escalation",
            "narration":         short_narration,
            "scene_prompt":      "Dark vertical 9:16, intense close-up, high-contrast red and black, fast cuts.",
            "hook_caption":      "NOBODY KNEW",
            "duration_target_sec": 42,
        },
        "shock_captions": [
            {"text": random.choice(SHOCK_CAPTION_POOL), "part_id": "escalation"},
            {"text": random.choice(SHOCK_CAPTION_POOL), "part_id": "climax"},
        ],
        "evidence_cards": [
            {"type": "POLICE FILE",       "text": f"{country.upper()} — {year}",             "part_id": "context"},
            {"type": "WITNESS REPORT",    "text": "TESTIMONY RECORDED — UNVERIFIED",          "part_id": "first_sign"},
            {"type": "INVESTIGATION LOG", "text": "CASE STATUS: ACTIVE — DETAILS RESTRICTED", "part_id": "escalation"},
        ],
    }

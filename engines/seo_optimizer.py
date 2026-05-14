"""
engines/seo_optimizer.py
Karma Vault Stories — SEO Metadata Optimizer Engine
Generates YouTube-optimized title, backup title, description, tags,
hashtags, and thumbnail text. Rotates title formulas and tracks CTR
performance per formula via the analytics/heuristics brain.
All outputs feed directly into YouTube upload metadata.
"""

import json
import random
import re
from datetime import datetime, timezone
from typing import Optional

from config.constants import (
    CHANNEL_NAME, SEO_TITLE_FORMULAS, SEO_DESCRIPTION_TEMPLATE,
    SEO_MAX_TAGS, SEO_DESCRIPTION_MAX_CHARS,
    THUMBNAIL_TEMPLATES, ContentPillar, StoryLabel,
)
from utils.logger import get_logger
from utils.models import StoryCandidate, DailyRunContext
from utils.file_manager import load_heuristics
from utils.api_client import call_writing_model

log = get_logger(__name__)

# YouTube hard limits
_TITLE_MAX_CHARS   = 100
_TITLE_TARGET_CHARS = 75   # sweet spot for CTR
_TAG_MAX_CHARS     = 500   # total tag string length
_DESC_MAX_CHARS    = SEO_DESCRIPTION_MAX_CHARS

# Channel URL placeholder — filled at upload time if not in env
_CHANNEL_URL = "https://www.youtube.com/@KarmaVaultStories"

# Pillar → core SEO keyword clusters (injected into tags + description)
_PILLAR_KEYWORD_CLUSTERS: dict[str, list[str]] = {
    ContentPillar.TRUE_SHOCKING.value: [
        "true shocking story", "real dark incident", "dark documentary",
        "shocking true crime", "dark files", "real horror story",
    ],
    ContentPillar.HUMAN_BETRAYAL.value: [
        "betrayal true story", "secret double life", "dark betrayal",
        "shocking secret revealed", "hidden life exposed", "true betrayal story",
    ],
    ContentPillar.PARANORMAL.value: [
        "paranormal true story", "real haunting", "jinn story real",
        "haunted file", "paranormal documentary", "real ghost encounter",
    ],
    ContentPillar.MYSTERY_DISAPPEARANCE.value: [
        "mysterious disappearance", "missing person true story",
        "unsolved mystery", "cold case solved", "dark mystery documentary",
        "vanished without trace",
    ],
    ContentPillar.DISTURBING_ACCIDENTS.value: [
        "disturbing true story", "real accident dark truth",
        "shocking incident documentary", "dark real events",
        "disturbing documentary", "tragic true story",
    ],
    ContentPillar.HISTORICAL_DARK.value: [
        "dark history true story", "historical dark file",
        "forgotten dark history", "history documentary dark",
        "historical mystery revealed", "dark historical secret",
    ],
    ContentPillar.AI_HORROR.value: [
        "AI horror true story", "technology dark story",
        "digital horror real", "AI dark documentary",
        "tech horror file", "artificial intelligence dark",
    ],
    ContentPillar.SECRET_DOUBLE_LIFE.value: [
        "secret double life real", "hidden identity exposed",
        "two lives dark story", "secret life revealed true",
        "double life documentary", "hidden truth revealed",
    ],
    ContentPillar.INTERNET_CONFESSION.value: [
        "dark confession true story", "anonymous dark secret",
        "internet confession real", "shocking confession documentary",
        "dark secret revealed", "confession dark file",
    ],
    ContentPillar.URBAN_LEGENDS.value: [
        "urban legend real story", "dark legend true",
        "creepy legend documentary", "real urban myth",
        "dark folklore true story", "legend proven real",
    ],
}

# Universal channel tags always included (eats into the 15-tag budget)
_CHANNEL_BASE_TAGS = [
    "Karma Vault Stories", "dark documentary", "true story",
    "dark files", "faceless documentary",
]

# Thumbnail text formula styles — match THUMBNAIL_TEMPLATES IDs
_THUMBNAIL_TEXT_STYLES: dict[str, str] = {
    "shocked_face":    "2 words MAX — create extreme urgency or horror. Example: SHE MOVED",
    "eerie_object":    "2-3 words — describe the dark object or event. Example: THE RITUAL",
    "silhouette":      "2 words — mysterious identity hint. Example: HIS SECRET",
    "document_reveal": "3-4 words — tease the file content. Example: CASE FILE OPENED",
}


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_seo_optimizer(ctx: DailyRunContext) -> DailyRunContext:
    """
    Generates full SEO metadata package for the selected story + script blueprint.
    Populates ctx.seo_metadata and embeds it into ctx.script_blueprint['seo'].
    """
    if not ctx.selected_story:
        log.error("No selected story — cannot generate SEO metadata.")
        return ctx

    log.info(f"SEO optimizer starting for: '{ctx.selected_story.title[:70]}'")
    heuristics = load_heuristics()

    # Select title formula based on CTR performance data
    formula_idx, formula = _select_title_formula(heuristics)
    log.info(f"Title formula selected: #{formula_idx} — {formula[:60]}")

    # Select thumbnail template based on CTR performance data
    thumb_template = _select_thumbnail_template(heuristics)
    ctx.thumbnail_template_id = thumb_template["id"]
    log.info(f"Thumbnail template selected: {thumb_template['id']}")

    # Attempt AI-powered SEO generation
    seo_metadata = None
    for attempt in range(1, 3):
        try:
            raw = _call_seo_ai(ctx.selected_story, ctx.script_blueprint, formula, thumb_template)
            seo_metadata = _parse_seo_response(raw)
            if seo_metadata and _validate_seo(seo_metadata):
                break
            seo_metadata = None
        except Exception as exc:
            log.warning(f"SEO AI attempt {attempt} failed: {exc}")

    if not seo_metadata:
        log.warning("AI SEO generation failed — building rule-based fallback metadata.")
        seo_metadata = _build_fallback_seo(ctx.selected_story, formula_idx, formula, thumb_template)

    # Enforce hard limits and clean up
    seo_metadata = _enforce_limits(seo_metadata)

    # Record which formula and template were used (for analytics tracking)
    seo_metadata["formula_idx"]         = formula_idx
    seo_metadata["thumbnail_template_id"] = thumb_template["id"]
    seo_metadata["generated_at"]        = datetime.now(timezone.utc).isoformat()

    ctx.seo_metadata = seo_metadata

    # Embed into script blueprint so downstream engines have it
    if ctx.script_blueprint:
        ctx.script_blueprint["seo"] = seo_metadata

    log.info(
        f"SEO complete. Title: '{seo_metadata.get('title','')[:70]}' "
        f"({len(seo_metadata.get('title',''))} chars) | "
        f"Tags: {len(seo_metadata.get('tags',[]))} | "
        f"Thumb text: '{seo_metadata.get('thumbnail_text','')}')"
    )
    ctx.mark_stage("seo_optimizer")
    return ctx


# ─────────────────────────────────────────────
# FORMULA & TEMPLATE SELECTION
# ─────────────────────────────────────────────

def _select_title_formula(heuristics: dict) -> tuple[int, str]:
    """
    Selects a title formula weighted by historical CTR performance.
    Uses epsilon-greedy: 80% exploit best performer, 20% explore random.
    """
    formula_ctr: dict = heuristics.get("title_formula_ctr", {})
    n = len(SEO_TITLE_FORMULAS)

    # Epsilon-greedy exploration
    if random.random() < 0.20 or not formula_ctr:
        idx = random.randrange(n)
        return idx, SEO_TITLE_FORMULAS[idx]

    # Exploit: pick highest CTR formula
    best_idx = max(
        range(n),
        key=lambda i: float(formula_ctr.get(str(i), 1.0 / n)),
    )
    return best_idx, SEO_TITLE_FORMULAS[best_idx]


def _select_thumbnail_template(heuristics: dict) -> dict:
    """
    Selects thumbnail template weighted by historical CTR.
    Epsilon-greedy with 20% exploration.
    """
    thumb_ctr: dict = heuristics.get("thumbnail_ctr", {})

    if random.random() < 0.20 or not thumb_ctr:
        return random.choice(THUMBNAIL_TEMPLATES)

    best = max(
        THUMBNAIL_TEMPLATES,
        key=lambda t: float(thumb_ctr.get(t["id"], 0.25)),
    )
    return best


# ─────────────────────────────────────────────
# AI SEO GENERATION
# ─────────────────────────────────────────────

def _call_seo_ai(
    story:          StoryCandidate,
    blueprint:      Optional[dict],
    formula:        str,
    thumb_template: dict,
) -> str:
    system_prompt = _build_seo_system_prompt()
    user_prompt   = _build_seo_user_prompt(story, blueprint, formula, thumb_template)
    return call_writing_model(
        system_prompt,
        user_prompt,
        max_tokens=1200,
        temperature=0.75,
        json_output=True,
    )


def _build_seo_system_prompt() -> str:
    return f"""You are the YouTube SEO and metadata specialist for "{CHANNEL_NAME}", a viral dark documentary channel.

Your job is to generate metadata that maximizes click-through rate (CTR) and watch time for dark, true-story content targeting English-speaking audiences aged 18-45 globally.

TITLE RULES:
- Must create immediate emotional urgency or mystery
- Use specific, concrete language — never vague
- Numbers, locations, and time references increase CTR
- Avoid clickbait that overpromises — must match video content
- Between 50-{_TITLE_TARGET_CHARS} characters is the sweet spot
- Hard maximum: {_TITLE_MAX_CHARS} characters
- Never start with "The Story of" or "A Documentary About"

DESCRIPTION RULES:
- First 2 sentences are the most critical — they appear in search previews
- Must contain the main hook and emotional tension
- Include country, approximate time period, and core dark theme
- 3-5 short paragraphs maximum
- End with channel subscribe prompt and hashtags
- Total under {_DESC_MAX_CHARS} characters

TAGS RULES:
- Maximum {SEO_MAX_TAGS} tags
- Mix: specific story tags + pillar category tags + channel brand tags
- Include country-specific tags
- Include year/era if relevant
- No duplicate concepts across tags

THUMBNAIL TEXT RULES:
- Maximum 4 words
- Must create irresistible visual curiosity
- Works as standalone text without context
- Should pair with a dark/shocking visual

OUTPUT: Valid JSON only. No markdown. No explanation."""


def _build_seo_user_prompt(
    story:          StoryCandidate,
    blueprint:      Optional[dict],
    formula:        str,
    thumb_template: dict,
) -> str:
    # Extract hook sentence from blueprint if available
    hook_sentence = ""
    if blueprint and blueprint.get("parts"):
        for part in blueprint["parts"]:
            if part.get("part_id") == "hook":
                narration = part.get("narration", "")
                # Take first sentence
                first_stop = min(
                    (narration.find(c) for c in ".!?" if narration.find(c) > 20),
                    default=len(narration),
                )
                hook_sentence = narration[:first_stop + 1].strip()
                break

    # Get script title if available (better starting point than raw story title)
    script_title = ""
    if blueprint:
        script_title = blueprint.get("title", "")

    # Pillar keyword cluster
    pillar_keywords = _PILLAR_KEYWORD_CLUSTERS.get(story.pillar, ["dark true story"])

    # Thumbnail text style instruction
    thumb_style_hint = _THUMBNAIL_TEXT_STYLES.get(thumb_template["id"], "2-4 words, dark and urgent")

    schema = {
        "title": f"Primary YouTube title using this formula template as inspiration: {formula}",
        "backup_title": "Alternative title with different emotional angle",
        "description": "Full YouTube description (3-5 paragraphs + hashtags at end)",
        "tags": [f"list of exactly {SEO_MAX_TAGS} YouTube tags as strings"],
        "hashtags": ["list of 6-8 hashtags with # prefix"],
        "thumbnail_text": f"2-4 word thumbnail overlay text. Style: {thumb_style_hint}",
        "title_hook_emotion": "one word: fear|shock|mystery|betrayal|dread|horror|curiosity",
        "seo_keyword_primary": "the single most important search keyword phrase",
    }

    return f"""Generate YouTube SEO metadata for this dark documentary video.

STORY DATA:
Title (script): {script_title or story.title}
Original title: {story.title}
Country: {story.country}
Pillar: {story.pillar}
Story label: {story.story_label}
Hook sentence: {hook_sentence or story.summary[:200]}
Core keywords: {', '.join(pillar_keywords[:4])}

TITLE FORMULA TEMPLATE (use as creative inspiration, not literal):
{formula}

THUMBNAIL TEMPLATE STYLE: {thumb_template['id']}
Thumbnail text requirement: {thumb_style_hint}

CHANNEL: {CHANNEL_NAME}
CHANNEL URL: {_CHANNEL_URL}

OUTPUT SCHEMA:
{json.dumps(schema, indent=2)}

CRITICAL:
1. Title must be {50}-{_TITLE_TARGET_CHARS} characters (max {_TITLE_MAX_CHARS})
2. Description first sentence must be the most emotionally gripping hook
3. Include {story.country} and relevant dark keywords naturally in description
4. Tags must be an array of exactly {SEO_MAX_TAGS} strings
5. thumbnail_text: maximum 4 words, punchy, creates visual urgency
6. Return only the JSON object"""


# ─────────────────────────────────────────────
# RESPONSE PARSING & VALIDATION
# ─────────────────────────────────────────────

def _parse_seo_response(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()

    # Strip markdown fences
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    start = text.find("{")
    end   = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None

    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        # Try fixing trailing commas
        cleaned = re.sub(r',\s*}', '}', text[start:end])
        cleaned = re.sub(r',\s*]', ']', cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None


def _validate_seo(metadata: dict) -> bool:
    if not isinstance(metadata, dict):
        return False
    title = (metadata.get("title") or "").strip()
    if len(title) < 20 or len(title) > _TITLE_MAX_CHARS:
        log.warning(f"SEO invalid: title length={len(title)}")
        return False
    if not metadata.get("description", "").strip():
        log.warning("SEO invalid: missing description")
        return False
    tags = metadata.get("tags", [])
    if not isinstance(tags, list) or len(tags) < 5:
        log.warning(f"SEO invalid: only {len(tags)} tags")
        return False
    if not metadata.get("thumbnail_text", "").strip():
        log.warning("SEO invalid: missing thumbnail_text")
        return False
    return True


# ─────────────────────────────────────────────
# LIMIT ENFORCEMENT
# ─────────────────────────────────────────────

def _enforce_limits(metadata: dict) -> dict:
    """Trims all fields to YouTube hard limits."""

    # Title
    title = (metadata.get("title") or "").strip()
    if len(title) > _TITLE_MAX_CHARS:
        title = title[:_TITLE_MAX_CHARS - 3].rsplit(" ", 1)[0] + "..."
    metadata["title"] = title

    backup = (metadata.get("backup_title") or "").strip()
    if len(backup) > _TITLE_MAX_CHARS:
        backup = backup[:_TITLE_MAX_CHARS - 3].rsplit(" ", 1)[0] + "..."
    metadata["backup_title"] = backup

    # Description
    desc = (metadata.get("description") or "").strip()
    if len(desc) > _DESC_MAX_CHARS:
        desc = desc[:_DESC_MAX_CHARS - 3] + "..."
    metadata["description"] = desc

    # Tags — cap at SEO_MAX_TAGS, ensure strings
    tags = metadata.get("tags", [])
    if isinstance(tags, list):
        tags = [str(t).strip()[:50] for t in tags if t][:SEO_MAX_TAGS]
    else:
        tags = []
    metadata["tags"] = tags

    # Hashtags — ensure # prefix
    hashtags = metadata.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags = [
            h if h.startswith("#") else f"#{h}"
            for h in hashtags if h
        ][:8]
    else:
        hashtags = ["#KarmaVaultStories", "#TrueStory", "#DarkFiles"]
    metadata["hashtags"] = hashtags

    # Thumbnail text — max 4 words
    thumb_text = (metadata.get("thumbnail_text") or "").strip().upper()
    words = thumb_text.split()[:4]
    metadata["thumbnail_text"] = " ".join(words)

    return metadata


# ─────────────────────────────────────────────
# RULE-BASED FALLBACK SEO
# ─────────────────────────────────────────────

def _build_fallback_seo(
    story:          StoryCandidate,
    formula_idx:    int,
    formula:        str,
    thumb_template: dict,
) -> dict:
    """
    Generates SEO metadata using rule-based substitution when AI fails.
    Produces real, usable metadata — not placeholder text.
    """
    country  = story.country if story.country not in ("Unknown", "global") else "An Unknown Location"
    label    = story.story_label.replace("{COUNTRY}", country)
    pillar   = story.pillar
    title_raw = story.title

    # Build title from formula template
    title = _apply_formula_substitutions(formula, story)
    if len(title) > _TITLE_MAX_CHARS or len(title) < 20:
        # Fall back to direct title with dark framing
        title = _frame_title(title_raw, country)

    # Backup title uses a different angle
    backup_formulas = [f for i, f in enumerate(SEO_TITLE_FORMULAS) if i != formula_idx]
    backup_formula = random.choice(backup_formulas)
    backup_title = _apply_formula_substitutions(backup_formula, story)
    if len(backup_title) > _TITLE_MAX_CHARS or len(backup_title) < 20:
        backup_title = f"This Dark File From {country} Was Never Meant to Be Found"

    # Description
    pillar_keywords = _PILLAR_KEYWORD_CLUSTERS.get(pillar, ["dark true story"])
    hook_line = f"This is a case from {country} that investigators tried to bury — and almost succeeded."
    para2 = (
        f"The file you are about to hear is based on real events. "
        f"{story.summary[:300] if story.summary else ''} "
        f"Every detail has been documented and verified to the extent possible."
    ).strip()
    para3 = (
        f"For more dark files, true stories, and unexplained cases "
        f"from around the world, subscribe to {CHANNEL_NAME}. "
        f"New dark files every single day."
    )
    hashtag_str = (
        "#KarmaVaultStories #TrueStory #DarkFiles #DarkDocumentary "
        f"#{country.replace(' ','')} #{pillar.replace('_','').title()}"
    )
    description = (
        f"{hook_line}\n\n{para2}\n\n{para3}\n\n"
        f"⚠️ Mature audiences 18+ only.\n\n"
        f"🔔 Subscribe: {_CHANNEL_URL}\n\n"
        f"{hashtag_str}"
    )

    # Tags
    pillar_tags = _PILLAR_KEYWORD_CLUSTERS.get(pillar, [])
    country_tag = country.lower()
    year_tag    = str(random.randint(2018, 2024))
    tags = list(_CHANNEL_BASE_TAGS) + pillar_tags + [
        country_tag,
        f"{country_tag} true story",
        f"dark story {year_tag}",
        "karma vault stories",
        label.lower(),
    ]
    tags = list(dict.fromkeys(tags))[:SEO_MAX_TAGS]

    # Hashtags
    hashtags = [
        "#KarmaVaultStories", "#TrueStory", "#DarkFiles",
        "#DarkDocumentary", "#TrueCrime",
        f"#{country.replace(' ','')}", "#DailyDarkFiles",
        f"#{pillar.split('_')[0].title()}",
    ]

    # Thumbnail text by template style
    thumb_texts = {
        "shocked_face":    _extract_thumbnail_text_shock(story),
        "eerie_object":    _extract_thumbnail_text_object(story),
        "silhouette":      _extract_thumbnail_text_mystery(story),
        "document_reveal": _extract_thumbnail_text_file(story),
    }
    thumbnail_text = thumb_texts.get(thumb_template["id"], "DARK FILE")

    return {
        "title":                title,
        "backup_title":         backup_title,
        "description":          description,
        "tags":                 tags,
        "hashtags":             hashtags,
        "thumbnail_text":       thumbnail_text,
        "title_hook_emotion":   _classify_hook_emotion(story.pillar),
        "seo_keyword_primary":  (pillar_tags[0] if pillar_tags else "dark true story"),
    }


# ─────────────────────────────────────────────
# TITLE CONSTRUCTION HELPERS
# ─────────────────────────────────────────────

def _apply_formula_substitutions(formula: str, story: StoryCandidate) -> str:
    """
    Fills in formula template placeholders with story-specific values.
    Handles graceful fallback for any unknown placeholder.
    """
    country = story.country if story.country not in ("Unknown", "global") else "an Unknown Location"

    # Map known placeholders to story-derived values
    replacements = {
        "{COUNTRY}":         country,
        "{VERB}":            random.choice(["Vanished", "Disappeared", "Confessed", "Escaped", "Returned"]),
        "{HORROR}":          random.choice(["the Truth", "Something Impossible", "a Dark Secret", "Evidence"]),
        "{PROFESSION}":      random.choice(["Teacher", "Doctor", "Police Officer", "Father", "Mother", "Priest"]),
        "{ACTION}":          random.choice(["Lived a Double Life", "Hid the Truth for Years", "Deceived Everyone"]),
        "{SHOCKING_DETAIL}": random.choice(["Nobody Believed the Witnesses", "The Evidence Was Buried", "They All Knew"]),
        "{NUMBER}":          str(random.choice([24, 48, 72, 168, 3, 7])),
        "{DURATION}":        random.choice(["3 Years", "7 Years", "Decades", "His Entire Life"]),
        "{YEAR}":            str(random.randint(2015, 2023)),
        "{SUBJECT}":         random.choice(["She", "He", "The Family", "The Witness", "The Child"]),
        "{LOCATION}":        random.choice(["House", "Room", "File", "Basement", "Hospital"]),
        "{NAME}":            random.choice(["the Missing Woman", "the Witness", "the Victim", "the Child"]),
    }

    result = formula
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    # Remove any remaining unfilled placeholders
    result = re.sub(r'\{[A-Z_]+\}', '', result).strip()
    return result


def _frame_title(raw_title: str, country: str) -> str:
    """Wraps a raw story title in a dark documentary framing."""
    frames = [
        f"{raw_title[:55]} | Dark File",
        f"The Truth Behind: {raw_title[:50]}",
        f"{raw_title[:50]} — {country} Dark Case",
        f"They Tried to Hide This: {raw_title[:45]}",
        f"Sealed File: {raw_title[:55]}",
    ]
    candidate = random.choice(frames)
    return candidate[:_TITLE_MAX_CHARS]


def _extract_thumbnail_text_shock(story: StoryCandidate) -> str:
    pillar = story.pillar
    mapping = {
        ContentPillar.PARANORMAL.value:         "IT MOVED",
        ContentPillar.HUMAN_BETRAYAL.value:     "HE LIED",
        ContentPillar.MYSTERY_DISAPPEARANCE.value: "SHE VANISHED",
        ContentPillar.DISTURBING_ACCIDENTS.value:  "THEY KNEW",
        ContentPillar.HISTORICAL_DARK.value:    "BURIED FILE",
        ContentPillar.SECRET_DOUBLE_LIFE.value: "TWO LIVES",
        ContentPillar.AI_HORROR.value:          "IT LEARNED",
        ContentPillar.INTERNET_CONFESSION.value:"CONFESSED",
        ContentPillar.URBAN_LEGENDS.value:      "IT'S REAL",
        ContentPillar.TRUE_SHOCKING.value:      "NOBODY KNEW",
    }
    return mapping.get(pillar, "DARK FILE")


def _extract_thumbnail_text_object(story: StoryCandidate) -> str:
    country = story.country if story.country not in ("Unknown","global") else ""
    prefix  = f"{country[:8].upper()} " if country else ""
    options = ["THE RITUAL", "THE ROOM", "THE FILE", "THE BODY", "THE TRUTH"]
    return (prefix + random.choice(options))[:20]


def _extract_thumbnail_text_mystery(story: StoryCandidate) -> str:
    options = ["HIS SECRET", "HER SECRET", "HIDDEN LIFE", "THE TRUTH", "DARK FILE"]
    return random.choice(options)


def _extract_thumbnail_text_file(story: StoryCandidate) -> str:
    country = story.country if story.country not in ("Unknown","global") else "UNKNOWN"
    return f"{country[:10].upper()} FILE"


def _classify_hook_emotion(pillar: str) -> str:
    mapping = {
        ContentPillar.PARANORMAL.value:            "dread",
        ContentPillar.HUMAN_BETRAYAL.value:        "shock",
        ContentPillar.MYSTERY_DISAPPEARANCE.value: "mystery",
        ContentPillar.DISTURBING_ACCIDENTS.value:  "horror",
        ContentPillar.HISTORICAL_DARK.value:       "curiosity",
        ContentPillar.SECRET_DOUBLE_LIFE.value:    "betrayal",
        ContentPillar.AI_HORROR.value:             "fear",
        ContentPillar.INTERNET_CONFESSION.value:   "shock",
        ContentPillar.URBAN_LEGENDS.value:         "dread",
        ContentPillar.TRUE_SHOCKING.value:         "shock",
    }
    return mapping.get(pillar, "shock")

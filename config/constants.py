"""
config/constants.py
Karma Vault Stories — Channel Identity, Content Rules, Visual Specs, SEO Formulas
All values are hardwired from the Master Dossier. Do not use generic defaults.
"""

from enum import Enum
from typing import Final

# ─────────────────────────────────────────────
# CHANNEL IDENTITY
# ─────────────────────────────────────────────
CHANNEL_NAME: Final = "Karma Vault Stories"
CHANNEL_NICHE: Final = "dark documentary storytelling"
TARGET_AUDIENCE_AGE: Final = "18-45"
TARGET_LANGUAGE: Final = "English"
CHANNEL_GOAL_SUBSCRIBERS: Final = 1000
CHANNEL_GOAL_WATCH_HOURS: Final = 4000

# ─────────────────────────────────────────────
# CONTENT PILLARS (10 categories, system rotates by analytics performance)
# ─────────────────────────────────────────────
class ContentPillar(str, Enum):
    TRUE_SHOCKING       = "true_shocking_stories"
    HUMAN_BETRAYAL      = "human_betrayal_revenge"
    PARANORMAL          = "paranormal_haunted_jinn"
    DISTURBING_ACCIDENTS = "disturbing_accidents_incidents"
    HISTORICAL_DARK     = "historical_dark_files"
    MYSTERY_DISAPPEARANCE = "mystery_disappearances"
    AI_HORROR           = "ai_original_horror"
    SECRET_DOUBLE_LIFE  = "secret_double_life"
    INTERNET_CONFESSION = "internet_confession_narrative"
    URBAN_LEGENDS       = "urban_legends"

CONTENT_PILLAR_WEIGHTS_DEFAULT: dict = {
    ContentPillar.TRUE_SHOCKING:          0.18,
    ContentPillar.HUMAN_BETRAYAL:         0.15,
    ContentPillar.PARANORMAL:             0.13,
    ContentPillar.DISTURBING_ACCIDENTS:   0.11,
    ContentPillar.HISTORICAL_DARK:        0.10,
    ContentPillar.MYSTERY_DISAPPEARANCE:  0.10,
    ContentPillar.AI_HORROR:              0.09,
    ContentPillar.SECRET_DOUBLE_LIFE:     0.07,
    ContentPillar.INTERNET_CONFESSION:    0.04,
    ContentPillar.URBAN_LEGENDS:          0.03,
}

# ─────────────────────────────────────────────
# STORY AUTHENTICITY LABELS
# ─────────────────────────────────────────────
class StoryLabel(str, Enum):
    TRUE_STORY      = "TRUE STORY FROM {COUNTRY}"
    REAL_INCIDENT   = "REAL INCIDENT"
    HAUNTED_FILE    = "HAUNTED FILE"
    INSPIRED        = "INSPIRED BY REAL EVENTS"
    PARANORMAL      = "PARANORMAL REPORT"

STORY_LABEL_LIST = [e.value for e in StoryLabel]

# ─────────────────────────────────────────────
# STORY SCORING DIMENSIONS
# ─────────────────────────────────────────────
STORY_SCORE_DIMENSIONS = [
    "curiosity",       # Does the opening hook demand continuation?
    "shock",           # Intensity of disturbing or surprising content
    "retention",       # Pacing quality — will viewers stay for 8+ min?
    "title_potential", # How viral can the YouTube title be?
    "thumb_potential", # How strong is the thumbnail visual concept?
    "uniqueness",      # Not a recycled viral story seen 1000x
    "advertiser_safety", # Avoids demonetizable extremes
]

STORY_SCORE_MAX = 10
STORY_PASS_THRESHOLD = 6.5   # Minimum weighted average to qualify

# ─────────────────────────────────────────────
# SCRIPT STRUCTURE — VIRAL FORMULA (MANDATORY)
# ─────────────────────────────────────────────
SCRIPT_PARTS = [
    "hook",           # Part 1: Shock hook — strongest possible opening sentence
    "context",        # Part 2: Quick context — who, where, when (max 30 sec)
    "normality",      # Part 3: Normal life before collapse
    "first_sign",     # Part 4: First disturbing sign
    "escalation",     # Part 5: Escalation cascade — micro cliffhanger every ~30 sec
    "climax",         # Part 6: Major payoff / reveal / karma / horror climax
    "aftermath",      # Part 7: Aftermath + subscribe bait
]

SCRIPT_MANDATORY_RULES = {
    "min_twists": 3,
    "cliffhanger_interval_sec": 30,
    "style": "conversational documentary English",
    "language_register": "emotional human",
    "forbidden": ["repetitive filler", "robotic morals", "generic AI summaries"],
    "cta_position": "after_first_major_twist",
    "subscribe_line": "SUBSCRIBE FOR DAILY DARK FILES",
    "end_screen_text": "TOMORROW'S FILE IS DARKER",
    "short_extraction_marker": "[SHORT_CLIP_START]",  # injected into script by writer
}

# JSON blueprint keys the script engine must always produce
SCRIPT_BLUEPRINT_KEYS = [
    "title",
    "backup_title",
    "story_label",
    "country",
    "pillar",
    "parts",           # list of {part_id, narration, scene_prompt, sfx_marker, cta_marker}
    "short_start_idx", # index of part to begin short extraction
    "shock_captions",  # list of {text, part_id} for shock overlay injection
    "evidence_cards",  # list of {type, text, part_id}
    "seo",             # {title, description, tags, hashtags, thumbnail_text}
    "voice_gender",    # "male" | "female"
    "estimated_duration_sec",
]

# ─────────────────────────────────────────────
# SEO TITLE FORMULAS (system rotates + tracks CTR)
# ─────────────────────────────────────────────
SEO_TITLE_FORMULAS = [
    "She {VERB} and They Found {HORROR} — True {COUNTRY} Story",
    "The {PROFESSION} Who {ACTION} | {SHOCKING_DETAIL}",
    "Nobody Believed Her Until {TWIST} Happened | Dark File",
    "{NUMBER} Hours Before {DISASTER} — The Full Story",
    "He Lived a Secret Life for {DURATION} | Real Case {YEAR}",
    "The Night {SUBJECT} Disappeared — {COUNTRY} Dark Files",
    "They Opened the {LOCATION} and Found {HORROR} | True Story",
    "What Really Happened to {NAME} | Unsolved Dark File",
    "The {YEAR} {COUNTRY} Case That Shocked the World",
    "She Knew Something Was Wrong — Nobody Listened",
]

SEO_DESCRIPTION_TEMPLATE = """{HOOK_SENTENCE}

{STORY_PARAGRAPH_1}

{STORY_PARAGRAPH_2}

⚠️ This content is intended for mature audiences 18+.

🔔 Subscribe for daily dark files: {CHANNEL_URL}

{HASHTAGS}

#KarmaVaultStories #TrueStory #DarkFiles #MysteryStories #TrueCrime"""

SEO_MAX_TAGS = 15
SEO_DESCRIPTION_MAX_CHARS = 4800

# ─────────────────────────────────────────────
# VISUAL IDENTITY (from Exact Visual Production Spec dossier)
# ─────────────────────────────────────────────
VISUAL_COLORS = {
    "background":   "#000000",
    "primary_text": "#FFFFFF",
    "accent_red":   "#8B0000",    # deep crimson
    "shock_red":    "#CC0000",    # shock overlays
    "warning":      "#FFD700",    # occasional warning yellow
    "overlay_bg":   "#1A0000",    # dark red tint for horror moments
}

VISUAL_FONT_PRIMARY    = "Impact"       # shock captions
VISUAL_FONT_SECONDARY  = "Arial Bold"   # evidence cards, body overlays
VISUAL_FONT_FALLBACK   = "DejaVu Sans Bold"  # CI environment fallback

# Grading filter values (applied via FFmpeg)
CINEMATIC_GRADE = {
    "vignette_strength":    0.35,
    "contrast_boost":       1.15,
    "brightness_reduce":    -0.08,
    "saturation_reduce":    0.88,
    "red_tint_horror":      True,   # applied only on horror climax scenes
    "grain_strength":       0.04,   # very subtle — CI runtime efficient
}

# ─────────────────────────────────────────────
# ASSET CATEGORY TYPES (for visual timeline assembly)
# ─────────────────────────────────────────────
class AssetCategory(str, Enum):
    STOCK_MOTION_CLIP    = "stock_motion_clip"
    AI_DRAMATIC_STILL    = "ai_dramatic_still"
    EVIDENCE_CARD        = "evidence_card"
    FAKE_NEWSPAPER       = "fake_newspaper_card"
    LOCATION_DATE_CARD   = "location_date_card"
    SHOCK_WORD_OVERLAY   = "shock_word_overlay"
    TEXT_MSG_SIMULATION  = "text_message_simulation"
    CCTV_STYLE           = "cctv_style_frame"
    STOCK_PHOTO          = "stock_photo"

# ─────────────────────────────────────────────
# SHOCK CAPTIONS (injected at major twist moments)
# ─────────────────────────────────────────────
SHOCK_CAPTION_POOL = [
    "SHE MOVED", "HE LIED", "THE BODY WAS GONE",
    "THEY HEARD CRYING", "CAMERA CAUGHT THIS",
    "NOBODY EXPECTED THIS", "THE FILE WAS SEALED",
    "HE WAS WATCHING", "IT HAPPENED AGAIN",
    "THE TRUTH CAME OUT", "SHE NEVER CAME BACK",
    "THEY KNEW", "THE DOOR WAS OPEN",
    "HE DID IT TWICE", "NO ONE SURVIVED",
    "IT WAS ALL A LIE", "THE LAST MESSAGE",
]

# ─────────────────────────────────────────────
# EVIDENCE CARD TYPES
# ─────────────────────────────────────────────
EVIDENCE_CARD_TYPES = [
    "POLICE FILE",
    "WITNESS REPORT",
    "CCTV FOOTAGE",
    "HOSPITAL RECORD",
    "FAMILY STATEMENT",
    "COURT DOCUMENT",
    "NEWS ARCHIVE",
    "INVESTIGATION REPORT",
]

# ─────────────────────────────────────────────
# THUMBNAIL TEMPLATES (system rotates, CTR tracked per template)
# ─────────────────────────────────────────────
THUMBNAIL_TEMPLATES = [
    {
        "id": "shocked_face",
        "description": "Dark background, shocked face silhouette, 2-word text top-right, +18 badge top-left",
        "text_position": "top_right",
        "bg_style": "dark_gradient",
    },
    {
        "id": "eerie_object",
        "description": "Eerie symbolic object center, red vignette, 3-word text bottom, +18 badge top-left",
        "text_position": "bottom_center",
        "bg_style": "blood_red",
    },
    {
        "id": "silhouette",
        "description": "Dark silhouette figure, foggy background, 2-word text center, +18 badge top-left",
        "text_position": "center",
        "bg_style": "fog_dark",
    },
    {
        "id": "document_reveal",
        "description": "Fake document/file partially revealed, red stamp overlay, text top, +18 top-left",
        "text_position": "top_center",
        "bg_style": "paper_aged",
    },
]

THUMBNAIL_WIDTH  = 1280
THUMBNAIL_HEIGHT = 720
THUMBNAIL_BADGE_TEXT = "+18"
THUMBNAIL_MAX_WORDS  = 4

# ─────────────────────────────────────────────
# MUSIC & SFX CATALOG KEYS
# ─────────────────────────────────────────────
class SFXMarker(str, Enum):
    BOOM_IMPACT     = "boom_impact"
    HEARTBEAT_PULSE = "heartbeat_pulse"
    TENSION_RISER   = "tension_riser"
    GLITCH          = "glitch_texture"
    WHISPER         = "whisper_ambient"
    DARK_AMBIENT_BED = "dark_ambient_bed"
    INTRO_SLAM      = "intro_slam"
    OUTRO_DARK      = "outro_dark"

MUSIC_MOOD_TAGS = [
    "dark ambient suspense",
    "cinematic tension",
    "horror documentary",
    "mystery investigation",
    "thriller underscore",
]

NARRATION_AUDIO_VOLUME  = 1.0
MUSIC_BED_VOLUME        = 0.12   # narration always dominant
SFX_VOLUME              = 0.55

# ─────────────────────────────────────────────
# ANALYTICS TRACKING KEYS
# ─────────────────────────────────────────────
ANALYTICS_TRACKED_FIELDS = [
    "video_id",
    "upload_timestamp",
    "title",
    "pillar",
    "story_label",
    "country",
    "voice_gender",
    "thumbnail_template_id",
    "title_formula_id",
    "views",
    "impressions",
    "ctr",
    "watch_time_sec",
    "avg_view_duration_sec",
    "subscribers_gained",
    "likes",
    "comments",
    "yt_pack_used",
]

# ─────────────────────────────────────────────
# HEURISTICS KEYS (self-learning brain)
# ─────────────────────────────────────────────
HEURISTICS_FILE = "heuristics/adaptive_weights.json"

HEURISTICS_DEFAULT = {
    "pillar_weights":       {p.value: w for p, w in CONTENT_PILLAR_WEIGHTS_DEFAULT.items()},
    "voice_performance":    {"male": 0.5, "female": 0.5},
    "thumbnail_ctr":        {t["id"]: 0.25 for t in THUMBNAIL_TEMPLATES},
    "title_formula_ctr":    {str(i): 1.0 / len(SEO_TITLE_FORMULAS) for i in range(len(SEO_TITLE_FORMULAS))},
    "country_performance":  {},
    "avg_session_views":    0,
    "total_videos_uploaded": 0,
    "last_updated":         "",
}

# ─────────────────────────────────────────────
# STORY BANK FILE NAMES
# ─────────────────────────────────────────────
STORY_BANK_FILES = {
    "verified_real":    "story_bank/verified_real_cases.json",
    "paranormal":       "story_bank/paranormal_legends.json",
    "confessions":      "story_bank/inspired_confessions.json",
    "historical":       "story_bank/historical_incidents.json",
    "evergreen":        "story_bank/evergreen_dark_stories.json",
    "used_ids":         "story_bank/used_story_ids.json",
}

# ─────────────────────────────────────────────
# PUBLICATION LOG FILE
# ─────────────────────────────────────────────
PUBLICATION_LOG_FILE = "analytics/publication_log.json"


# ─────────────────────────────────────────────
# VIDEO DURATION CONSTANTS (also referenced in settings.py)
# ─────────────────────────────────────────────
LONG_VIDEO_MIN_MINUTES: Final = 8
LONG_VIDEO_MAX_MINUTES: Final = 12
SHORT_VIDEO_MIN_SEC: Final = 35
SHORT_VIDEO_MAX_SEC: Final = 50
# ─────────────────────────────────────────────
# GITHUB ACTIONS RUNTIME CONSTRAINTS
# ─────────────────────────────────────────────
GHA_MAX_JOB_MINUTES     = 340   # 6hr limit with buffer
GHA_ARTIFACT_RETENTION  = 7     # days
GHA_RUNNER_RAM_GB       = 7
GHA_RUNNER_CORES        = 2

# ─────────────────────────────────────────────
# STORY COLLECTION BOUNDS
# ─────────────────────────────────────────────
MIN_STORY_CANDIDATES = 20
MAX_STORY_CANDIDATES = 40

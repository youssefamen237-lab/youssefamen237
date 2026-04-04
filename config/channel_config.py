# Merged into config/settings.py
#
# All channel identity and configuration constants live in config/settings.py:
#
#   CHANNEL_NAME        = "MindCraft Psychology"
#   CHANNEL_NICHE       = os.getenv("CHANNEL_NICHE", "psychology facts")
#   CHANNEL_VOICE       = os.getenv("CHANNEL_VOICE", "en-US-GuyNeural")
#   TARGET_COUNTRIES    = ["US", "GB", "CA", "AU"]
#   YT_CATEGORY_ID      = "27"        # Education
#   YT_DEFAULT_TAGS     = [...]
#   CTA_TEXT            = "Follow for daily psychology secrets"
#   DAILY_SHORTS_COUNT  = 4
#   SCRIPT_SYSTEM_PROMPT = "..."
#   SCRIPT_JSON_SCHEMA  = {...}
#
# Import directly from config.settings wherever channel config is needed:
#
#   from config.settings import CHANNEL_NAME, CTA_TEXT, YT_DEFAULT_TAGS

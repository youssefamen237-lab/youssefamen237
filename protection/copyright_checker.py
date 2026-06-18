"""
protection/copyright_checker.py
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import structlog
from storage.supabase_client import get_db
from storage.r2_client import get_r2

logger = structlog.get_logger(__name__)

_RELIABILITY_SCORES: Dict[str, int] = {
    "pexels": 95, "pixabay": 90, "coverr": 85, "internet_archive": 80,
    "vecteezy": 85, "unsplash": 95, "pexels_photo": 95, "pixabay_photo": 90,
    "freepik": 75,
    "getimg": 70, "stability": 70, "dezgo": 65, "ai_horde": 60,
}
_REAL_PROVIDERS = frozenset({
    "pexels", "pixabay", "coverr", "internet_archive", "vecteezy",
    "unsplash", "pexels_photo", "pixabay_photo", "freepik",
})
_RISK_SAFE_THRESHOLD = 40   # risk_score (100 - reliability) at/below this is "safe"


@dataclass
class CopyrightCheckResult:
    risk_score:   int
    is_safe:      bool
    license_type: str
    reason:       Optional[str] = None


class CopyrightChecker:

    def __init__(self) -> None:
        self._db = get_db()
        self._r2 = get_r2()

    # ── Single item ───────────────────────────────────────────────────────────

    def check_media_item(self, media_item) -> CopyrightCheckResult:
        if media_item is None:
            return CopyrightCheckResult(0, True, "none", "no_media_generated_clip_used")

        provider     = getattr(media_item, "provider", "unknown")
        reliability  = _RELIABILITY_SCORES.get(provider, 30)
        risk_score   = 100 - reliability
        is_ai        = provider not in _REAL_PROVIDERS
        license_type = "generated" if is_ai else "royalty_free"

        # AI-generated content carries no third-party copyright risk by definition
        is_safe = is_ai or risk_score <= _RISK_SAFE_THRESHOLD
        reason  = None if is_safe else f"low_reliability_source:{provider}"

        return CopyrightCheckResult(risk_score, is_safe, license_type, reason)

    # ── Batch ─────────────────────────────────────────────────────────────────

    def check_all(self, media_items: List) -> CopyrightCheckResult:
        if not media_items:
            return CopyrightCheckResult(0, True, "none")

        results = [self.check_media_item(m) for m in media_items]
        avg_risk = sum(r.risk_score for r in results) / len(results)
        unsafe   = [r for r in results if not r.is_safe]
        is_safe  = len(unsafe) == 0
        reason   = unsafe[0].reason if unsafe else None

        return CopyrightCheckResult(int(round(avg_risk)), is_safe, "mixed", reason)

    # ── Asset registration (visual_assets table) ─────────────────────────────

    def register_assets(
        self, media_items: List, queue_id: str, topic_tags: List[str]
    ) -> int:
        """
        Register every successfully-fetched media item in visual_assets.
        Returns the count of assets registered.  Failures on individual
        items are logged and skipped — never raises.
        """
        registered = 0
        for item in media_items:
            if item is None:
                continue
            try:
                file_hash = self._r2.compute_file_hash(item.local_path)
            except Exception as exc:
                logger.debug("asset_hash_failed", queue_id=queue_id[:8], error=str(exc)[:80])
                continue

            check = self.check_media_item(item)
            asset_data = {
                "file_hash":          file_hash,
                "source_provider":    item.provider,
                "source_id":          str(getattr(item, "provider_source_id", "") or "")[:255],
                "asset_type":         item.asset_type,
                "topic_tags":         topic_tags,
                "search_query_used":  getattr(item, "search_query", "")[:500],
                "width":              item.width,
                "height":             item.height,
                "duration_seconds":   getattr(item, "duration_seconds", None),
                "file_size_bytes":    int(getattr(item, "file_size_bytes", 0) or 0),
                "is_ai_generated":    check.license_type == "generated",
                "license_type":       check.license_type,
                "has_watermark":      False,
            }
            try:
                self._db.register_asset(asset_data)
                registered += 1
            except Exception as exc:
                logger.debug("asset_register_skip", queue_id=queue_id[:8], error=str(exc)[:80])

        return registered


_instance: Optional[CopyrightChecker] = None

def get_copyright_checker() -> CopyrightChecker:
    global _instance
    if _instance is None:
        _instance = CopyrightChecker()
    return _instance

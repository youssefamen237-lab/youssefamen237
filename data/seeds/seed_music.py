"""
data/seeds/seed_music.py

Populates the `music_tracks` table by searching Freesound for royalty-free
ambient tracks matching each category/mood pair.  Tracks are stored with
their preview URL only — actual download + R2 caching happens lazily on
first use via intelligence/music_selector.py.

Idempotent — checks existing freesound_id values before inserting.

Required GitHub Secret: FREESOUND_API   (Freesound API token)

Run standalone:
    python -m data.seeds.seed_music
"""
from __future__ import annotations
import os
from typing import Dict, List, Optional, Tuple
import requests, structlog
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
_FIELDS     = "id,name,previews,duration,license,tags"
_RESULTS_PER_QUERY = 2

# (category, mood, search query) — covers every category at least twice,
# plus a 'general' fallback bucket used by music_selector when a specific
# category has no tracks.
_QUERIES: List[Tuple[str, str, str]] = [
    ("ocean",   "mysterious",  "underwater ambient drone"),
    ("ocean",   "calm",        "ocean waves ambient calm"),
    ("space",   "epic",        "space ambient cinematic"),
    ("space",   "mysterious",  "cosmic drone atmosphere"),
    ("animals", "tense",       "tense ambient drone nature"),
    ("animals", "documentary", "nature documentary ambient"),
    ("nature",  "documentary", "nature documentary background ambient"),
    ("nature",  "calm",        "forest ambient calm nature"),
    ("birds",   "calm",        "calm ambient morning birdsong"),
    ("birds",   "uplifting",   "light uplifting ambient acoustic"),
    ("insects", "tense",       "tense dark ambient drone"),
    ("insects", "dark",        "dark ambient mysterious drone"),
    ("general", "documentary", "documentary background ambient music"),
    ("general", "calm",        "calm ambient background music"),
]

_CC0_HINTS = ("zero", "publicdomain", "cc0", "creative commons 0")


def _is_available() -> bool:
    return bool(os.getenv("FREESOUND_API", "").strip())


def _search(query: str, token: str) -> List[Dict]:
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={
                "query": query,
                "token": token,
                "fields": _FIELDS,
                "filter": 'license:"Creative Commons 0"',
                "page_size": _RESULTS_PER_QUERY,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                return results
    except Exception as exc:
        logger.debug("freesound_filtered_search_failed", query=query, error=str(exc)[:80])

    # Fallback: no license filter — accept results whose license string looks CC0
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={
                "query": query,
                "token": token,
                "fields": _FIELDS,
                "page_size": _RESULTS_PER_QUERY,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            cc0 = [r for r in results if _looks_cc0(r.get("license", ""))]
            return cc0 or results[:1]
    except Exception as exc:
        logger.debug("freesound_unfiltered_search_failed", query=query, error=str(exc)[:80])

    return []


def _looks_cc0(license_str: str) -> bool:
    s = (license_str or "").lower()
    return any(hint in s for hint in _CC0_HINTS)


def _extract_preview_url(result: Dict) -> Optional[str]:
    previews = result.get("previews") or {}
    return (
        previews.get("preview-hq-mp3")
        or previews.get("preview-lq-mp3")
        or previews.get("preview-hq-ogg")
    )


def seed_all(force: bool = False) -> Dict[str, int]:
    """
    Search Freesound for each (category, mood, query) tuple and insert
    new tracks into music_tracks.  Returns {"inserted": N, "skipped_existing": M}.
    """
    db = get_db()
    result_counts = {"inserted": 0, "skipped_existing": 0, "queries_run": 0}

    if not _is_available():
        logger.warning("freesound_api_key_missing_skipping_music_seed")
        return result_counts

    token = os.environ["FREESOUND_API"]

    # Load existing freesound_ids to avoid duplicate inserts
    try:
        existing_rows = db.client.table("music_tracks").select("freesound_id").execute().data or []
        existing_ids = {r["freesound_id"] for r in existing_rows if r.get("freesound_id")}
    except Exception as exc:
        logger.warning("music_existing_lookup_failed", error=str(exc)[:100])
        existing_ids = set()

    new_rows: List[Dict] = []

    for category, mood, query in _QUERIES:
        results = _search(query, token)
        result_counts["queries_run"] += 1

        for r in results:
            fs_id = str(r.get("id", ""))
            if not fs_id or fs_id in existing_ids:
                result_counts["skipped_existing"] += 1
                continue

            preview_url = _extract_preview_url(r)
            if not preview_url:
                continue

            new_rows.append({
                "track_name":       str(r.get("name", f"track_{fs_id}"))[:255],
                "source_url":       preview_url,
                "category":         category,
                "mood":             mood,
                "bpm":              None,
                "duration_seconds": int(round(float(r.get("duration", 0) or 0))),
                "license_type":     "CC0" if _looks_cc0(r.get("license", "")) else str(r.get("license", "unknown"))[:100],
                "freesound_id":     fs_id,
                "is_downloaded":    False,
                "is_active":        True,
            })
            existing_ids.add(fs_id)

        logger.info("music_query_done", category=category, mood=mood, query=query, found=len(results))

    if new_rows:
        try:
            db.client.table("music_tracks").insert(new_rows).execute()
            result_counts["inserted"] = len(new_rows)
        except Exception as exc:
            logger.error("music_insert_failed", error=str(exc)[:200])

    logger.info("music_seeding_complete", **result_counts)
    return result_counts


if __name__ == "__main__":
    summary = seed_all()
    print("\n=== Music Seeding Summary ===")
    for k, v in summary.items():
        print(f"  {k:20s}: {v}")

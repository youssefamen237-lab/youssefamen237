"""
engines/assemblyai_sync.py
Karma Vault Stories — Phase B AssemblyAI Word-Level Subtitle Sync

Submits the generated TTS narration audio to AssemblyAI, retrieves
exact word-level timestamps (milliseconds), and writes them to
{run_id}/audio/word_timestamps.json.

The video_renderer reads this file to generate a perfectly-synchronised
SRT file — every subtitle chunk aligns exactly to when the word is spoken,
not approximated from TTS pacing estimates.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)

_AAI_BASE        = "https://api.assemblyai.com/v2"
_UPLOAD_CHUNK    = 5 * 1024 * 1024   # 5 MB upload chunks
_POLL_INTERVAL   = 5                 # seconds
_MAX_POLL        = 60                # 60 × 5s = 300s total


def get_word_timestamps(
    audio_file_path: str,
    api_key:         str,
) -> Optional[list[dict]]:
    """
    Full AssemblyAI pipeline:
      1. Upload audio file
      2. Submit transcription with word_boost=[] for accuracy
      3. Poll until status == "completed"
      4. Return list of {text, start, end} (times in milliseconds)

    Returns None on any failure — caller falls back to approximated timing.
    """
    # ── Step 1: Upload audio ──────────────────────────────────────
    upload_url = _upload_audio(audio_file_path, api_key)
    if not upload_url:
        log.warning("AssemblyAI: audio upload failed.")
        return None
    log.debug(f"AssemblyAI: audio uploaded → {upload_url[:60]}...")

    # ── Step 2: Submit transcript request ────────────────────────
    transcript_id = _submit_transcript(upload_url, api_key)
    if not transcript_id:
        log.warning("AssemblyAI: transcript submission failed.")
        return None
    log.info(f"AssemblyAI: transcript submitted (id={transcript_id}).")

    # ── Step 3: Poll for completion ───────────────────────────────
    return _poll_transcript(transcript_id, api_key)


# ─────────────────────────────────────────────
# STEP 1: UPLOAD
# ─────────────────────────────────────────────

def _upload_audio(audio_path_str: str, api_key: str) -> Optional[str]:
    """Uploads local audio file to AssemblyAI and returns the CDN URL."""
    try:
        audio_bytes = Path(audio_path_str).read_bytes()
        req = urllib.request.Request(
            f"{_AAI_BASE}/upload",
            data=audio_bytes,
            headers={
                "authorization":  api_key,
                "content-type":   "application/octet-stream",
                "transfer-encoding": "chunked",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("upload_url")
    except Exception as exc:
        log.debug(f"AssemblyAI upload error: {exc}")
        return None


# ─────────────────────────────────────────────
# STEP 2: SUBMIT TRANSCRIPT
# ─────────────────────────────────────────────

def _submit_transcript(audio_url: str, api_key: str) -> Optional[str]:
    """Submits a transcription job and returns the transcript ID."""
    try:
        payload = json.dumps({
            "audio_url":     audio_url,
            "language_code": "en",
            "punctuate":     True,
            "format_text":   True,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{_AAI_BASE}/transcript",
            data=payload,
            headers={
                "authorization": api_key,
                "content-type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("id")
    except Exception as exc:
        log.debug(f"AssemblyAI submit error: {exc}")
        return None


# ─────────────────────────────────────────────
# STEP 3: POLL
# ─────────────────────────────────────────────

def _poll_transcript(
    transcript_id: str,
    api_key:       str,
) -> Optional[list[dict]]:
    """Polls the transcript endpoint until complete. Returns word list or None."""
    url = f"{_AAI_BASE}/transcript/{transcript_id}"
    headers = {"authorization": api_key}

    for attempt in range(_MAX_POLL):
        time.sleep(_POLL_INTERVAL)
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            status = data.get("status", "")

            if status == "completed":
                raw_words = data.get("words", [])
                if not raw_words:
                    log.warning("AssemblyAI: transcript completed but no words returned.")
                    return None
                result = [
                    {
                        "text":  w.get("text", "").strip(),
                        "start": int(w.get("start", 0)),   # ms
                        "end":   int(w.get("end",   0)),   # ms
                    }
                    for w in raw_words
                    if w.get("text", "").strip()
                ]
                duration_sec = result[-1]["end"] / 1000 if result else 0
                log.info(
                    f"AssemblyAI: completed — {len(result)} words, "
                    f"duration={duration_sec:.1f}s"
                )
                return result

            if status == "error":
                log.warning(f"AssemblyAI: transcript error — {data.get('error', 'unknown')}")
                return None

            if attempt % 6 == 0:
                log.debug(f"AssemblyAI: polling ({attempt * _POLL_INTERVAL}s) status={status}")

        except Exception as exc:
            log.debug(f"AssemblyAI poll error (attempt {attempt}): {exc}")

    log.warning(f"AssemblyAI: timed out after {_MAX_POLL * _POLL_INTERVAL}s.")
    return None


# ─────────────────────────────────────────────
# SRT GENERATION FROM WORD TIMESTAMPS
# ─────────────────────────────────────────────

def build_srt_from_word_timestamps(
    word_timestamps: list[dict],
    chunk_size:      int = 7,
) -> str:
    """
    Converts word-level timestamps to SRT content.
    Groups words into subtitle lines of chunk_size words.
    Uses exact AssemblyAI millisecond timing — perfectly synchronised.

    chunk_size = 7 is optimal for 1080p dark documentary:
      - Long enough for meaningful context per line
      - Short enough to be readable before the next line appears
    """
    lines: list[str] = []
    idx = 1
    words = [w for w in word_timestamps if w.get("text")]

    for i in range(0, len(words), chunk_size):
        chunk = words[i : i + chunk_size]
        if not chunk:
            continue
        text       = " ".join(w["text"] for w in chunk)
        start_ms   = chunk[0]["start"]
        end_ms     = chunk[-1]["end"]

        # Ensure minimum display duration (1.5s)
        if end_ms - start_ms < 1500:
            end_ms = start_ms + 1500

        lines.append(
            f"{idx}\n"
            f"{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}\n"
            f"{text}"
        )
        idx += 1

    return "\n\n".join(lines) + "\n" if lines else ""


def _ms_to_srt(ms: int) -> str:
    """Converts milliseconds to SRT timestamp HH:MM:SS,mmm"""
    ms   = max(0, ms)
    h    = ms // 3_600_000
    ms  %= 3_600_000
    m    = ms // 60_000
    ms  %= 60_000
    s    = ms // 1_000
    ms  %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_word_timestamps(run_id: str) -> Optional[list[dict]]:
    """
    Loads word timestamps from the run workspace.
    Called by video_renderer._generate_srt_file() to check for
    AssemblyAI data before falling back to approximated timing.
    """
    try:
        from utils.file_manager import audio_path
        ts_file = audio_path(run_id, "word_timestamps.json")
        if ts_file.exists():
            data = json.loads(ts_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
    except Exception as exc:
        log.debug(f"Could not load word_timestamps.json: {exc}")
    return None
  

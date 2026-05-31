"""
engines/voice_generator.py
Karma Vault Stories — Voice Generation Engine
Cascading TTS fallback: ElevenLabs → Camb.AI → edge-tts (always available).
Generates per-part audio files, joins them with cinematic pauses,
measures real durations, and injects timing metadata back into the
script blueprint so Phase 5 (scene builder) and Phase 6 (renderer)
know exactly when each part starts and ends.
"""

import os
import sys
import time
import asyncio
import subprocess
import json
from pathlib import Path
from typing import Optional

from config.settings import (
    ELEVEN_API_KEY, ELEVENLABS_VOICE_ID_MALE, ELEVENLABS_VOICE_ID_FEMALE,
    CAMB_AI_KEY_1, TTS_PROVIDER_CHAIN,
    AUDIO_SAMPLE_RATE, AUDIO_BITRATE,
    API_REQUEST_TIMEOUT_SEC,
)
from config.constants import (
    SFXMarker, LONG_VIDEO_MAX_MINUTES,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import audio_path, ensure_run_workspace
from utils.api_client import http_post_json, http_get_json, http_get, with_retry

log = get_logger(__name__)

# ── Voice identity map ────────────────────────────────────────────────────────
_EDGE_VOICE_MAP = {
    "male":   "en-US-GuyNeural",
    "female": "en-US-AriaNeural",
}

# Slightly slower rate for documentary gravitas (-8%)
_EDGE_RATE = "-8%"
_EDGE_PITCH = {
    "male":   "-3Hz",
    "female": "+0Hz",
}

# ElevenLabs voice settings tuned for documentary narration
_EL_VOICE_SETTINGS = {
    "stability":          0.55,
    "similarity_boost":   0.75,
    "style":              0.20,
    "use_speaker_boost":  True,
}
_EL_MODEL = "eleven_multilingual_v2"

# Camb.AI voice IDs (documentary style): 1=male, 2=female (public defaults)
_CAMB_VOICE_ID = {"male": 1, "female": 2}

# Silence gaps between narration parts (milliseconds)
_PART_GAP_MS = {
    "hook":       200,
    "context":    350,
    "normality":  350,
    "first_sign": 400,
    "escalation": 350,
    "climax":     600,   # dramatic pause before aftermath
    "aftermath":  0,
}
_DEFAULT_GAP_MS = 300

# Minimum valid audio file size in bytes
_MIN_AUDIO_BYTES = 2048


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_voice_generator(ctx: DailyRunContext) -> DailyRunContext:
    """
    Generates all TTS audio for the current run.
    Outputs:
      - Per-part MP3 files (for debug / re-render use)
      - narration_clean.mp3  — joined parts, no music
      - narration_short.mp3  — short clip narration only
    Updates ctx.script_blueprint with per-part start/duration timing.
    Sets ctx.narration_audio_path and ctx.narration_duration_sec.
    """
    if not ctx.script_blueprint:
        log.error("No script blueprint — cannot generate voice.")
        return ctx

    log.info(f"Voice generator starting. Gender={ctx.voice_gender}")
    ensure_run_workspace(ctx.run_id)

    blueprint   = ctx.script_blueprint
    parts       = blueprint.get("parts", [])
    voice_gender = ctx.voice_gender

    # ── Generate per-part audio ───────────────────────────────────
    part_paths:     list[Optional[Path]] = []
    part_durations: list[float]          = []

    for idx, part in enumerate(parts):
        narration = (part.get("narration") or "").strip()
        if not narration:
            log.warning(f"Part {idx} ({part.get('part_id','?')}) has no narration — inserting silence.")
            silence_path = audio_path(ctx.run_id, f"part_{idx:02d}_{part.get('part_id','x')}.mp3")
            _write_silence(silence_path, duration_ms=3000)
            part_paths.append(silence_path)
            part_durations.append(3.0)
            continue

        out_path = audio_path(ctx.run_id, f"part_{idx:02d}_{part.get('part_id','x')}.mp3")
        provider_used = _generate_tts_with_fallback(narration, voice_gender, out_path)

        if not _is_valid_audio(out_path):
            log.warning(f"All TTS providers failed for part {idx} — writing silence fallback.")
            estimated_ms = int(len(narration.split()) / 140 * 60 * 1000)
            _write_silence(out_path, duration_ms=max(estimated_ms, 2000))
            provider_used = "silence_fallback"

        duration = _get_audio_duration_sec(out_path)
        part_paths.append(out_path)
        part_durations.append(duration)

        log.info(f"  Part {idx:02d} {part.get('part_id','?'):<14}: "
                 f"{len(narration.split()):>4}w → {duration:.1f}s via {provider_used}")

        # Respect TTS rate limits
        time.sleep(0.15)

    # Track which provider successfully drove the majority of parts
    ctx.tts_provider_used = _detect_dominant_provider(part_paths, voice_gender)

    # ── Inject timing into blueprint ──────────────────────────────
    _inject_timing_into_blueprint(blueprint, parts, part_durations)

    # ── Join parts into clean narration ──────────────────────────
    clean_path = audio_path(ctx.run_id, "narration_clean.mp3")
    _join_parts_with_pauses(parts, part_paths, part_durations, clean_path)

    total_duration = _get_audio_duration_sec(clean_path)
    ctx.narration_audio_path  = str(clean_path)
    ctx.narration_duration_sec = total_duration

    log.info(f"Clean narration: {total_duration:.1f}s → {clean_path.name}")

    # ── Generate short clip audio ─────────────────────────────────
    short_narration = (blueprint.get("short_clip") or {}).get("narration", "")
    if short_narration.strip():
        short_path = audio_path(ctx.run_id, "narration_short.mp3")
        provider = _generate_tts_with_fallback(short_narration, voice_gender, short_path)
        if _is_valid_audio(short_path):
            short_dur = _get_audio_duration_sec(short_path)
            blueprint["short_clip"]["audio_path"]    = str(short_path)
            blueprint["short_clip"]["duration_sec"]  = short_dur
            log.info(f"Short clip audio: {short_dur:.1f}s via {provider}")
        else:
            log.warning("Short clip TTS failed — short will use silence.")

    # ── Phase B: AssemblyAI word-level timestamp extraction ──────────
    try:
        from config.settings import ENABLE_ASSEMBLYAI_SYNC, ASSEMBLYAI
        from utils.file_manager import audio_path as _apath
        if ENABLE_ASSEMBLYAI_SYNC and ctx.narration_audio_path and ASSEMBLYAI:
            log.info("AssemblyAI: submitting audio for word-level timestamps...")
            from engines.assemblyai_sync import get_word_timestamps
            word_ts = get_word_timestamps(ctx.narration_audio_path, ASSEMBLYAI)
            if word_ts:
                import json as _j
                ts_path = _apath(ctx.run_id, "word_timestamps.json")
                ts_path.parent.mkdir(parents=True, exist_ok=True)
                ts_path.write_text(_j.dumps(word_ts, ensure_ascii=False), encoding="utf-8")
                ctx.word_timestamps = word_ts
                log.info(f"  AssemblyAI: {len(word_ts)} words indexed, saved to word_timestamps.json")
            else:
                log.warning("  AssemblyAI returned no timestamps — approximated SRT will be used.")
    except Exception as _aai_exc:
        log.warning(f"  AssemblyAI extraction failed (non-fatal): {_aai_exc}")

    ctx.mark_stage("voice_generator")
    log.info(f"Voice generator complete. Total={total_duration:.1f}s, "
             f"Provider={ctx.tts_provider_used}")
    return ctx


# ─────────────────────────────────────────────
# CASCADING TTS FALLBACK
# ─────────────────────────────────────────────

def _generate_tts_with_fallback(
    text:         str,
    voice_gender: str,
    output_path:  Path,
) -> str:
    """
    Tries ElevenLabs → Camb.AI → edge-tts in order.
    Returns the name of the provider that succeeded.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. ElevenLabs ────────────────────────────────────────────
    if ELEVEN_API_KEY:
        voice_id = (
            ELEVENLABS_VOICE_ID_MALE
            if voice_gender == "male"
            else ELEVENLABS_VOICE_ID_FEMALE
        )
        if voice_id:
            try:
                if _tts_elevenlabs(text, voice_id, ELEVEN_API_KEY, output_path):
                    if _is_valid_audio(output_path):
                        return "elevenlabs"
            except Exception as exc:
                log.warning(f"ElevenLabs TTS failed: {exc}")

    # ── 2. Camb.AI ───────────────────────────────────────────────
    if CAMB_AI_KEY_1:
        try:
            if _tts_camb_ai(text, CAMB_AI_KEY_1, voice_gender, output_path):
                if _is_valid_audio(output_path):
                    return "camb_ai"
        except Exception as exc:
            log.warning(f"Camb.AI TTS failed: {exc}")

    # ── 3. edge-tts (always available, calls Microsoft neural TTS) ─
    try:
        if _tts_edge(text, voice_gender, output_path):
            if _is_valid_audio(output_path):
                return "edge_tts"
    except Exception as exc:
        log.warning(f"edge-tts failed: {exc}")

    return "failed"


# ─────────────────────────────────────────────
# PROVIDER IMPLEMENTATIONS
# ─────────────────────────────────────────────

def _tts_elevenlabs(
    text:        str,
    voice_id:    str,
    api_key:     str,
    output_path: Path,
) -> bool:
    """
    ElevenLabs streaming TTS.
    Handles texts up to ~5000 chars per call; longer texts are chunked.
    """
    chunks = _chunk_text(text, max_chars=4500)
    audio_chunks: list[bytes] = []

    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        payload = {
            "text":           chunk,
            "model_id":       _EL_MODEL,
            "voice_settings": _EL_VOICE_SETTINGS,
        }
        headers = {
            "xi-api-key":   api_key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }
        import urllib.request, urllib.error
        import json as _json
        body = _json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                audio_chunks.append(resp.read())
        except urllib.error.HTTPError as exc:
            log.warning(f"ElevenLabs HTTP {exc.code}: {exc.read()[:200]}")
            return False
        time.sleep(0.2)

    if not audio_chunks:
        return False

    with open(output_path, "wb") as f:
        for chunk_data in audio_chunks:
            f.write(chunk_data)
    return True


def _tts_camb_ai(
    text:        str,
    api_key:     str,
    gender:      str,
    output_path: Path,
) -> bool:
    """
    Camb.AI async TTS: POST task → poll → download.
    Max wait: 90 seconds.
    """
    voice_id = _CAMB_VOICE_ID.get(gender, 1)
    headers  = {"x-api-key": api_key, "Content-Type": "application/json"}

    # Submit task
    try:
        resp = with_retry(
            http_post_json,
            "https://client.camb.ai/apis/tts",
            {"text": text[:3000], "voice_id": voice_id, "language": "en"},
            headers=headers,
        )
    except Exception as exc:
        log.warning(f"Camb.AI task submit failed: {exc}")
        return False

    task_id = resp.get("task_id") or resp.get("id")
    if not task_id:
        log.warning(f"Camb.AI returned no task_id: {resp}")
        return False

    # Poll for completion
    poll_url = f"https://client.camb.ai/apis/tts/{task_id}"
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(2.5)
        try:
            status_resp = with_retry(
                http_get_json, poll_url, headers=headers, timeout=20
            )
            status = status_resp.get("status", "").upper()
            if status == "SUCCESS":
                file_url = (
                    status_resp.get("file_path")
                    or status_resp.get("audio_url")
                    or status_resp.get("url")
                )
                if not file_url:
                    log.warning("Camb.AI SUCCESS but no audio URL in response.")
                    return False
                audio_bytes = with_retry(http_get, file_url, timeout=30)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                return True
            elif status == "FAILED":
                log.warning(f"Camb.AI task failed: {status_resp}")
                return False
            # else PROCESSING — keep polling
        except Exception as exc:
            log.warning(f"Camb.AI poll error: {exc}")
            break

    log.warning(f"Camb.AI task {task_id} timed out after 90s.")
    return False


def _tts_edge(
    text:        str,
    gender:      str,
    output_path: Path,
) -> bool:
    """
    Microsoft edge-tts — completely free neural TTS.
    Runs async; we bridge via asyncio.run().
    Long texts are chunked, converted individually, then concatenated.
    """
    try:
        import edge_tts  # noqa: F401 — verifies package is installed
    except ImportError:
        log.warning("edge-tts not installed — skipping.")
        return False

    voice    = _EDGE_VOICE_MAP.get(gender, "en-US-GuyNeural")
    rate     = _EDGE_RATE
    pitch    = _EDGE_PITCH.get(gender, "+0Hz")
    chunks   = _chunk_text(text, max_chars=3000)

    chunk_paths: list[Path] = []
    for i, chunk in enumerate(chunks):
        chunk_path = output_path.parent / f"{output_path.stem}_chunk{i}.mp3"
        success = _run_edge_tts_sync(chunk, voice, rate, pitch, chunk_path)
        if not success:
            # Clean up partial files
            for cp in chunk_paths:
                cp.unlink(missing_ok=True)
            return False
        chunk_paths.append(chunk_path)

    if len(chunk_paths) == 1:
        chunk_paths[0].rename(output_path)
    else:
        _concat_mp3_files([str(p) for p in chunk_paths], str(output_path))
        for cp in chunk_paths:
            cp.unlink(missing_ok=True)

    return True


def _run_edge_tts_sync(
    text:        str,
    voice:       str,
    rate:        str,
    pitch:       str,
    output_path: Path,
) -> bool:
    """Runs edge-tts async generate in a synchronous context."""
    import edge_tts

    async def _generate() -> None:
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        await communicate.save(str(output_path))

    try:
        # Handle running inside an existing event loop (e.g. Jupyter)
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _generate())
                future.result(timeout=120)
        except RuntimeError:
            asyncio.run(_generate())
        return output_path.exists() and output_path.stat().st_size > _MIN_AUDIO_BYTES
    except Exception as exc:
        log.warning(f"edge-tts generate error: {exc}")
        return False


# ─────────────────────────────────────────────
# AUDIO UTILITIES
# ─────────────────────────────────────────────

def _get_audio_duration_sec(path: Path) -> float:
    """Returns audio duration in seconds using pydub (ffmpeg backend)."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(path))
        return len(audio) / 1000.0
    except Exception:
        # Fallback: estimate from file size (rough)
        try:
            size_kb = path.stat().st_size / 1024
            return max(1.0, size_kb / 16)   # ~16KB/s for 128kbps MP3
        except Exception:
            return 5.0


def _is_valid_audio(path: Path) -> bool:
    """Returns True if path exists and is a non-trivial audio file."""
    try:
        return path.exists() and path.stat().st_size >= _MIN_AUDIO_BYTES
    except Exception:
        return False


def _write_silence(path: Path, duration_ms: int = 3000) -> None:
    """Writes a silent MP3 file of the given duration using pydub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from pydub import AudioSegment
        silence = AudioSegment.silent(duration=duration_ms, frame_rate=AUDIO_SAMPLE_RATE)
        silence.export(str(path), format="mp3", bitrate=AUDIO_BITRATE)
    except Exception as exc:
        log.warning(f"Could not write silence to {path}: {exc}")
        # Last resort: write empty file so pipeline can continue
        path.touch()


def _join_parts_with_pauses(
    parts:          list[dict],
    part_paths:     list[Optional[Path]],
    part_durations: list[float],
    output_path:    Path,
) -> None:
    """
    Concatenates part audio files with cinematic pauses between sections.
    Uses pydub for sample-accurate joining.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        log.error("pydub not installed — falling back to ffmpeg concat.")
        _ffmpeg_concat_parts(part_paths, output_path)
        return

    combined = AudioSegment.empty()
    for idx, (part, path) in enumerate(zip(parts, part_paths)):
        if path is None or not _is_valid_audio(path):
            continue
        try:
            seg = AudioSegment.from_file(str(path))
            # Normalize to consistent sample rate
            seg = seg.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)
            combined += seg
        except Exception as exc:
            log.warning(f"Could not load part {idx} audio: {exc}")
            continue

        # Add pause after this part (except the last one)
        if idx < len(parts) - 1:
            part_id  = part.get("part_id", "")
            gap_ms   = _PART_GAP_MS.get(part_id, _DEFAULT_GAP_MS)
            combined += AudioSegment.silent(duration=gap_ms, frame_rate=AUDIO_SAMPLE_RATE)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(
        str(output_path),
        format="mp3",
        bitrate=AUDIO_BITRATE,
        parameters=["-ar", str(AUDIO_SAMPLE_RATE)],
    )


def _ffmpeg_concat_parts(part_paths: list, output_path: Path) -> None:
    """Fallback concatenation using ffmpeg concat demuxer."""
    concat_list = output_path.parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for p in part_paths:
            if p and Path(p).exists():
                f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_list), "-c", "copy", str(output_path)],
        check=True, capture_output=True,
    )
    concat_list.unlink(missing_ok=True)


def _concat_mp3_files(paths: list[str], output_path: str) -> None:
    """Concatenates MP3 files via pydub."""
    try:
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        for p in paths:
            combined += AudioSegment.from_mp3(p)
        combined.export(output_path, format="mp3", bitrate=AUDIO_BITRATE)
    except Exception as exc:
        log.warning(f"MP3 concatenation failed: {exc}")


def _inject_timing_into_blueprint(
    blueprint:      dict,
    parts:          list[dict],
    part_durations: list[float],
) -> None:
    """
    Writes start_time_sec and duration_sec into each blueprint part in-place.
    This is consumed by the scene builder (Phase 5) and renderer (Phase 6).
    """
    cumulative = 0.0
    for part, duration in zip(parts, part_durations):
        part["start_time_sec"] = round(cumulative, 3)
        part["duration_sec"]   = round(duration, 3)
        gap_sec = _PART_GAP_MS.get(part.get("part_id", ""), _DEFAULT_GAP_MS) / 1000.0
        cumulative += duration + gap_sec

    blueprint["total_narration_sec"] = round(cumulative, 3)


def _detect_dominant_provider(
    part_paths:   list[Optional[Path]],
    voice_gender: str,
) -> str:
    """
    Heuristic: if all parts are present and valid, the last successful provider
    was whatever edge-tts would have used. In production, returns the provider
    name based on file sizes (ElevenLabs files tend to be larger at equal length).
    Falls back to 'edge_tts' as the safe assumption.
    """
    valid_paths = [p for p in part_paths if p and _is_valid_audio(p)]
    if not valid_paths:
        return "none"
    # ElevenLabs produces ~200+ bytes/second; edge-tts ~120 bytes/second
    avg_size = sum(p.stat().st_size for p in valid_paths) / len(valid_paths)
    try:
        from pydub import AudioSegment
        sample_path = valid_paths[0]
        dur = _get_audio_duration_sec(sample_path)
        if dur > 0:
            bytes_per_sec = sample_path.stat().st_size / dur
            if ELEVEN_API_KEY and bytes_per_sec > 18000:
                return "elevenlabs"
            if CAMB_AI_KEY_1 and 12000 < bytes_per_sec <= 18000:
                return "camb_ai"
    except Exception:
        pass
    return "edge_tts"


def _chunk_text(text: str, max_chars: int = 4500) -> list[str]:
    """
    Splits text into chunks at sentence boundaries, each ≤ max_chars.
    Preserves sentence integrity for natural TTS output.
    """
    if len(text) <= max_chars:
        return [text]

    sentences = []
    current   = text
    while current:
        if len(current) <= max_chars:
            sentences.append(current.strip())
            break
        # Find last sentence boundary within max_chars
        slice_   = current[:max_chars]
        boundary = max(
            slice_.rfind(". "),
            slice_.rfind("! "),
            slice_.rfind("? "),
        )
        if boundary < max_chars * 0.4:
            boundary = max_chars  # force hard cut if no boundary found
        sentences.append(current[:boundary + 1].strip())
        current = current[boundary + 1:].strip()

    return [s for s in sentences if s]

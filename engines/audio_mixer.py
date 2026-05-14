"""
engines/audio_mixer.py
Karma Vault Stories — Music & SFX Selector + Audio Mixing Engine
Selects/generates background music and SFX, then mixes three audio layers:
  Layer 1 — narration (100% volume, dominant)
  Layer 2 — dark ambient music bed (12% volume, loops full duration)
  Layer 3 — cinematic SFX events at timed positions (55% volume)
Produces final_audio_mixed.mp3 consumed by the video renderer.
"""

import os
import time
import math
import random
import struct
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import (
    FREESOUND_API, FREESOUND_ID, FREESOUND_CREDENTIALS,
    AUDIO_SAMPLE_RATE, AUDIO_BITRATE,
    API_REQUEST_TIMEOUT_SEC,
)
from config.constants import (
    SFXMarker, MUSIC_MOOD_TAGS,
    NARRATION_AUDIO_VOLUME, MUSIC_BED_VOLUME, SFX_VOLUME,
    ContentPillar,
)
from utils.logger import get_logger
from utils.models import DailyRunContext
from utils.file_manager import audio_path, ensure_run_workspace
from utils.api_client import http_get_json, http_get, with_retry

log = get_logger(__name__)

# dB adjustments (pydub uses additive dB)
# MUSIC_BED_VOLUME = 0.12 → roughly -18.4 dB relative to narration
_MUSIC_BED_DB   = -18   # reduce music so narration dominates
_SFX_DB         = -5    # SFX are punchy but not louder than narration

# Freesound search parameters
_FS_SEARCH_URL = "https://freesound.org/apiv2/search/text/"

# SFX search queries per marker
_SFX_QUERIES: dict[str, dict] = {
    SFXMarker.INTRO_SLAM.value:      {"query": "cinematic boom impact slam",      "max_dur": 2.5},
    SFXMarker.BOOM_IMPACT.value:     {"query": "horror boom impact cinematic",    "max_dur": 3.0},
    SFXMarker.TENSION_RISER.value:   {"query": "suspense riser tension build",    "max_dur": 4.0},
    SFXMarker.HEARTBEAT_PULSE.value: {"query": "heartbeat pulse dark",             "max_dur": 3.0},
    SFXMarker.GLITCH.value:          {"query": "glitch digital noise horror",     "max_dur": 2.0},
    SFXMarker.WHISPER.value:         {"query": "whisper ambient dark eerie",      "max_dur": 3.0},
    SFXMarker.DARK_AMBIENT_BED.value:{"query": "dark ambient drone sustained",    "max_dur": 30.0},
    SFXMarker.OUTRO_DARK.value:      {"query": "dark cinematic outro fade",       "max_dur": 5.0},
}

# Pillar → music mood query
_PILLAR_MUSIC_QUERIES: dict[str, str] = {
    ContentPillar.PARANORMAL.value:             "dark paranormal ambient horror music",
    ContentPillar.HUMAN_BETRAYAL.value:         "dark suspense tension thriller music",
    ContentPillar.MYSTERY_DISAPPEARANCE.value:  "mystery investigation ambient music",
    ContentPillar.DISTURBING_ACCIDENTS.value:   "dark cinematic tension ambient",
    ContentPillar.HISTORICAL_DARK.value:        "historical dark orchestral ambient",
    ContentPillar.AI_HORROR.value:              "electronic dark ambient horror music",
    ContentPillar.SECRET_DOUBLE_LIFE.value:     "noir suspense ambient dark music",
    ContentPillar.INTERNET_CONFESSION.value:    "dark minimal ambient suspense",
    ContentPillar.URBAN_LEGENDS.value:          "eerie haunting ambient dark drone",
    ContentPillar.TRUE_SHOCKING.value:          "cinematic dark suspense ambient",
}


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def run_audio_mixer(ctx: DailyRunContext) -> DailyRunContext:
    """
    Mixes narration + music + SFX into the final audio track.
    Reads:  ctx.narration_audio_path (clean narration from voice_generator)
    Reads:  ctx.script_blueprint (parts with sfx_markers + timing)
    Writes: ctx.narration_audio_path (updated to mixed path)
    Writes: ctx.narration_duration_sec (measured from final mixed file)
    """
    if not ctx.narration_audio_path:
        log.error("No clean narration audio — cannot mix.")
        return ctx

    clean_path = Path(ctx.narration_audio_path)
    if not clean_path.exists():
        log.error(f"Narration file missing: {clean_path}")
        return ctx

    log.info("Audio mixer starting...")
    blueprint = ctx.script_blueprint or {}
    parts     = blueprint.get("parts", [])
    pillar    = (ctx.selected_story.pillar if ctx.selected_story else
                 ContentPillar.TRUE_SHOCKING.value)
    total_sec = ctx.narration_duration_sec or 600.0

    # ── Step 1: Build SFX cache (download or generate each unique marker) ──
    log.info("Building SFX cache...")
    sfx_cache = _build_sfx_cache(parts, ctx.run_id)
    log.info(f"SFX cache: {len(sfx_cache)} markers ready.")

    # ── Step 2: Select / generate music bed ──────────────────────
    log.info("Selecting music bed...")
    music_path = _get_music_bed(pillar, total_sec, ctx.run_id)
    log.info(f"Music bed: {music_path.name}")

    # ── Step 3: Build SFX event timeline ─────────────────────────
    sfx_timeline = _build_sfx_timeline(parts, sfx_cache, blueprint)
    log.info(f"SFX timeline: {len(sfx_timeline)} events.")

    # ── Step 4: Mix all layers ────────────────────────────────────
    mixed_path = audio_path(ctx.run_id, "final_audio_mixed.mp3")
    _mix_audio_layers(clean_path, music_path, sfx_timeline, mixed_path, total_sec)

    from engines.voice_generator import _get_audio_duration_sec, _is_valid_audio
    if _is_valid_audio(mixed_path):
        final_duration = _get_audio_duration_sec(mixed_path)
        ctx.narration_audio_path   = str(mixed_path)
        ctx.narration_duration_sec = final_duration
        log.info(f"Mixed audio: {final_duration:.1f}s → {mixed_path.name}")
    else:
        log.warning("Mixed audio invalid — keeping clean narration as fallback.")

    # ── Step 5: Mix short clip audio (narration only + light music) ──
    _mix_short_clip_audio(blueprint, pillar, ctx.run_id)

    ctx.mark_stage("audio_mixer")
    return ctx


# ─────────────────────────────────────────────
# SFX CACHE BUILDER
# ─────────────────────────────────────────────

def _build_sfx_cache(parts: list[dict], run_id: str) -> dict[str, Path]:
    """
    For each unique sfx_marker used in the blueprint parts,
    downloads from Freesound or generates programmatically.
    Returns: {marker_value: Path}
    """
    needed_markers = set()
    for part in parts:
        marker = part.get("sfx_marker")
        if marker and marker != SFXMarker.DARK_AMBIENT_BED.value:
            needed_markers.add(marker)
    # Always ensure boom_impact (used for shock captions)
    needed_markers.add(SFXMarker.BOOM_IMPACT.value)
    needed_markers.add(SFXMarker.INTRO_SLAM.value)

    cache: dict[str, Path] = {}
    for marker in needed_markers:
        sfx_path = audio_path(run_id, f"sfx_{marker.replace(' ','_')}.mp3")
        if sfx_path.exists():
            cache[marker] = sfx_path
            continue

        # Try Freesound first, then programmatic
        got_it = False
        if FREESOUND_API:
            got_it = _download_freesound_sfx(marker, sfx_path)
        if not got_it:
            got_it = _generate_sfx_programmatic(marker, sfx_path)
        if got_it:
            cache[marker] = sfx_path
        else:
            log.warning(f"SFX '{marker}' unavailable — will skip in timeline.")

    return cache


# ─────────────────────────────────────────────
# MUSIC BED
# ─────────────────────────────────────────────

def _get_music_bed(pillar: str, total_sec: float, run_id: str) -> Path:
    """
    Gets a music bed matching the story pillar.
    Tries Freesound first, then generates programmatically.
    Returns the path to a valid music file.
    """
    music_path = audio_path(run_id, "music_bed_source.mp3")
    if music_path.exists():
        return music_path

    # Try Freesound
    if FREESOUND_API:
        query = _PILLAR_MUSIC_QUERIES.get(pillar, "dark ambient suspense music")
        if _download_freesound_music(query, music_path):
            return music_path

    # Programmatic dark drone (always works)
    gen_path = audio_path(run_id, "music_bed_generated.mp3")
    _generate_dark_drone(total_sec + 10, gen_path)   # extra 10s for fade
    return gen_path


# ─────────────────────────────────────────────
# SFX TIMELINE BUILDER
# ─────────────────────────────────────────────

def _build_sfx_timeline(
    parts:     list[dict],
    sfx_cache: dict[str, Path],
    blueprint: dict,
) -> list[tuple[float, Path, int]]:
    """
    Returns list of (start_time_sec, sfx_path, db_adjust) for all SFX events.
    Enforces 2-second minimum gap between events.
    dark_ambient_bed is handled by music layer, not SFX events.
    """
    events: list[tuple[float, Path, int]] = []
    last_event_time = -999.0

    for part in parts:
        marker     = part.get("sfx_marker")
        start_time = part.get("start_time_sec", 0.0)

        # dark_ambient_bed is the music layer — skip as discrete event
        if not marker or marker == SFXMarker.DARK_AMBIENT_BED.value:
            continue

        sfx_path = sfx_cache.get(marker)
        if not sfx_path:
            continue

        # Enforce minimum gap
        if start_time - last_event_time < 2.0:
            start_time = last_event_time + 2.0

        events.append((start_time, sfx_path, _SFX_DB))
        last_event_time = start_time

    # Add boom_impact SFX at shock caption positions
    shock_captions = blueprint.get("shock_captions", [])
    boom_path      = sfx_cache.get(SFXMarker.BOOM_IMPACT.value)
    if boom_path:
        for caption in shock_captions:
            caption_part_id = caption.get("part_id", "")
            # Find the part to get its start time
            for part in parts:
                if part.get("part_id") == caption_part_id:
                    t = part.get("start_time_sec", 0.0)
                    # Offset slightly into the part for dramatic effect
                    t += min(part.get("duration_sec", 0) * 0.4, 8.0)
                    if t - last_event_time >= 2.0:
                        events.append((t, boom_path, _SFX_DB + 3))  # louder for shock
                        last_event_time = t
                    break

    # Sort by time
    events.sort(key=lambda e: e[0])
    return events


# ─────────────────────────────────────────────
# AUDIO LAYER MIXER
# ─────────────────────────────────────────────

def _mix_audio_layers(
    narration_path: Path,
    music_path:     Path,
    sfx_timeline:   list[tuple[float, Path, int]],
    output_path:    Path,
    total_sec:      float,
) -> None:
    """
    Three-layer mix using pydub:
      Layer 1 (base):   narration at full volume
      Layer 2 (overlay): music bed at MUSIC_BED_DB, looped, fade in/out
      Layer 3 (overlay): SFX events at timed positions
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        log.error("pydub not installed — cannot mix audio. Copying clean narration.")
        import shutil
        shutil.copy2(str(narration_path), str(output_path))
        return

    total_ms = int(total_sec * 1000)

    # ── Load narration ────────────────────────────────────────────
    try:
        narration = AudioSegment.from_file(str(narration_path))
        narration = narration.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)
        actual_ms = len(narration)
    except Exception as exc:
        log.error(f"Could not load narration: {exc}")
        import shutil
        shutil.copy2(str(narration_path), str(output_path))
        return

    # ── Load and prepare music bed ───────────────────────────────
    try:
        music_raw = AudioSegment.from_file(str(music_path))
        music_raw = music_raw.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)

        # Loop music until it covers the full narration + 5s
        needed_ms = actual_ms + 5000
        while len(music_raw) < needed_ms:
            music_raw = music_raw + music_raw
        music_bed = music_raw[:needed_ms]

        # Apply fade in (3s) and fade out (8s)
        music_bed = music_bed.fade_in(3000).fade_out(8000)
        # Reduce volume to music bed level
        music_bed = music_bed + _MUSIC_BED_DB

    except Exception as exc:
        log.warning(f"Could not load music bed ({exc}) — using narration only.")
        music_bed = AudioSegment.silent(duration=actual_ms, frame_rate=AUDIO_SAMPLE_RATE)

    # ── Base mix: narration + music ───────────────────────────────
    # Overlay music onto narration (narration is base, music is overlay)
    mixed = narration.overlay(music_bed, position=0)

    # ── Overlay SFX events ────────────────────────────────────────
    for (start_sec, sfx_path, db_adjust) in sfx_timeline:
        start_ms = int(start_sec * 1000)
        if start_ms >= actual_ms:
            continue
        try:
            sfx = AudioSegment.from_file(str(sfx_path))
            sfx = sfx.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)
            sfx = sfx + db_adjust
            # Ensure SFX doesn't extend past end
            if start_ms + len(sfx) > actual_ms:
                sfx = sfx[:actual_ms - start_ms]
            mixed = mixed.overlay(sfx, position=start_ms)
        except Exception as exc:
            log.warning(f"SFX overlay failed at {start_sec:.1f}s: {exc}")

    # ── Export ────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mixed.export(
        str(output_path),
        format="mp3",
        bitrate=AUDIO_BITRATE,
        parameters=["-ar", str(AUDIO_SAMPLE_RATE)],
    )


def _mix_short_clip_audio(
    blueprint: dict,
    pillar:    str,
    run_id:    str,
) -> None:
    """
    Mixes the short clip audio: narration_short.mp3 + lighter music bed.
    Shorts get music at 18% volume (slightly louder than long video — more aggressive).
    Writes to short_final_audio.mp3.
    """
    short_clip     = blueprint.get("short_clip", {})
    short_audio_str = short_clip.get("audio_path", "")
    if not short_audio_str or not Path(short_audio_str).exists():
        return

    short_narration_path = Path(short_audio_str)
    short_music_path     = audio_path(run_id, "music_bed_source.mp3")
    if not short_music_path.exists():
        short_music_path = audio_path(run_id, "music_bed_generated.mp3")
    if not short_music_path.exists():
        return

    short_mixed_path = audio_path(run_id, "short_final_audio.mp3")

    try:
        from pydub import AudioSegment

        narr   = AudioSegment.from_file(str(short_narration_path))
        narr   = narr.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)
        dur_ms = len(narr)

        music  = AudioSegment.from_file(str(short_music_path))
        music  = music.set_frame_rate(AUDIO_SAMPLE_RATE).set_channels(1)
        while len(music) < dur_ms + 3000:
            music = music + music
        music  = music[:dur_ms + 3000].fade_in(500).fade_out(2000)
        music  = music + (_MUSIC_BED_DB + 2)   # slightly louder for shorts

        mixed  = narr.overlay(music)
        mixed.export(str(short_mixed_path), format="mp3", bitrate=AUDIO_BITRATE)
        blueprint["short_clip"]["mixed_audio_path"] = str(short_mixed_path)
        log.info(f"Short clip mixed audio: {short_mixed_path.name}")
    except Exception as exc:
        log.warning(f"Short clip audio mix failed: {exc}")


# ─────────────────────────────────────────────
# FREESOUND INTEGRATION
# ─────────────────────────────────────────────

def _download_freesound_sfx(marker: str, output_path: Path) -> bool:
    """Downloads an SFX file from Freesound matching the marker type."""
    query_cfg = _SFX_QUERIES.get(marker)
    if not query_cfg:
        return False

    query   = query_cfg["query"]
    max_dur = query_cfg["max_dur"]

    try:
        resp = with_retry(
            http_get_json,
            _FS_SEARCH_URL,
            params={
                "query":  query,
                "token":  FREESOUND_API,
                "fields": "name,previews,duration,license,id",
                "filter": f"duration:[0.3 TO {max_dur}]",
                "sort":   "downloads_desc",
                "page_size": 6,
            },
            timeout=15,
        )
        results = resp.get("results", [])
        for sound in results:
            preview_url = (sound.get("previews") or {}).get("preview-hq-mp3")
            if not preview_url:
                continue
            try:
                audio_bytes = with_retry(http_get, preview_url, timeout=20)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                if output_path.stat().st_size > 2048:
                    log.debug(f"Freesound SFX '{marker}': {sound.get('name','?')}")
                    return True
            except Exception:
                continue
    except Exception as exc:
        log.warning(f"Freesound SFX query failed for '{marker}': {exc}")
    return False


def _download_freesound_music(query: str, output_path: Path) -> bool:
    """Downloads a music track from Freesound for the music bed."""
    try:
        resp = with_retry(
            http_get_json,
            _FS_SEARCH_URL,
            params={
                "query":  query,
                "token":  FREESOUND_API,
                "fields": "name,previews,duration,license",
                "filter": "duration:[30 TO 300]",
                "sort":   "rating_desc",
                "page_size": 8,
            },
            timeout=15,
        )
        results = resp.get("results", [])
        # Prefer longer tracks to avoid excessive looping
        results = sorted(results, key=lambda r: r.get("duration", 0), reverse=True)
        for sound in results:
            preview_url = (sound.get("previews") or {}).get("preview-hq-mp3")
            if not preview_url:
                continue
            try:
                audio_bytes = with_retry(http_get, preview_url, timeout=30)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                if output_path.stat().st_size > 10000:
                    log.debug(f"Freesound music: {sound.get('name','?')} "
                              f"({sound.get('duration',0):.0f}s)")
                    return True
            except Exception:
                continue
    except Exception as exc:
        log.warning(f"Freesound music query failed: {exc}")
    return False


# ─────────────────────────────────────────────
# PROGRAMMATIC SFX GENERATION (numpy + pydub)
# ─────────────────────────────────────────────

def _generate_sfx_programmatic(marker: str, output_path: Path) -> bool:
    """
    Generates cinematic SFX programmatically using numpy synthesis.
    Always works regardless of network availability.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sr = AUDIO_SAMPLE_RATE

        if marker == SFXMarker.INTRO_SLAM.value:
            samples = _synth_intro_slam(sr)
        elif marker == SFXMarker.BOOM_IMPACT.value:
            samples = _synth_boom_impact(sr)
        elif marker == SFXMarker.TENSION_RISER.value:
            samples = _synth_tension_riser(sr)
        elif marker == SFXMarker.HEARTBEAT_PULSE.value:
            samples = _synth_heartbeat(sr)
        elif marker == SFXMarker.GLITCH.value:
            samples = _synth_glitch(sr)
        elif marker == SFXMarker.WHISPER.value:
            samples = _synth_whisper(sr)
        elif marker == SFXMarker.OUTRO_DARK.value:
            samples = _synth_outro_dark(sr)
        elif marker == SFXMarker.DARK_AMBIENT_BED.value:
            samples = _synth_dark_drone_short(sr, duration_sec=8.0)
        else:
            samples = _synth_boom_impact(sr)

        _save_numpy_as_mp3(samples, sr, output_path)
        return output_path.exists() and output_path.stat().st_size > 1024

    except Exception as exc:
        log.warning(f"Programmatic SFX generation failed for '{marker}': {exc}")
        return False


def _synth_intro_slam(sr: int) -> np.ndarray:
    """Sharp cinematic impact: sub-bass hit + noise burst, 0.8s."""
    dur = 0.8
    t   = np.linspace(0, dur, int(sr * dur))
    # Sub-bass sweep: 120Hz → 30Hz
    freq_env = 120.0 * np.exp(-8.0 * t)
    phase    = 2 * np.pi * np.cumsum(freq_env) / sr
    sub_bass = np.sin(phase) * np.exp(-6.0 * t)
    # Noise burst
    noise    = np.random.randn(len(t)) * np.exp(-25.0 * t) * 0.35
    # High mid transient
    transient = np.sin(2 * np.pi * 800 * t) * np.exp(-40.0 * t) * 0.15
    wave = sub_bass + noise + transient
    return _normalize_audio(wave, peak=0.88)


def _synth_boom_impact(sr: int) -> np.ndarray:
    """Deep cinematic boom: 60Hz fundamental + harmonics + noise, 1.5s."""
    dur = 1.5
    t   = np.linspace(0, dur, int(sr * dur))
    # Fundamental sweep: 60→20Hz
    freq_env = 60.0 * np.exp(-3.5 * t)
    phase    = 2 * np.pi * np.cumsum(freq_env) / sr
    boom     = np.sin(phase) * np.exp(-3.0 * t)
    # Second harmonic
    boom    += 0.4 * np.sin(2 * phase) * np.exp(-5.0 * t)
    # Impact noise (very brief)
    noise    = np.random.randn(len(t)) * np.exp(-30.0 * t) * 0.2
    # Low rumble
    rumble   = np.sin(2 * np.pi * 35 * t) * np.exp(-1.5 * t) * 0.3
    wave     = boom + noise + rumble
    return _normalize_audio(wave, peak=0.90)


def _synth_tension_riser(sr: int) -> np.ndarray:
    """Ascending tension riser: 80→600Hz over 3 seconds, growing intensity."""
    dur = 3.0
    t   = np.linspace(0, dur, int(sr * dur))
    # Exponential frequency sweep
    freq_env = 80.0 * np.exp(t * (np.log(600.0 / 80.0) / dur))
    phase    = 2 * np.pi * np.cumsum(freq_env) / sr
    # Volume ramps up
    envelope = (t / dur) ** 1.8
    riser    = np.sin(phase) * envelope
    # Add overtone
    riser   += 0.35 * np.sin(2 * phase) * envelope
    # Add high-frequency shimmer at peak
    shimmer  = np.sin(2 * np.pi * 3000 * t) * envelope * 0.08
    wave     = riser + shimmer
    # Fade in from silence
    wave[:int(0.05 * sr)] *= np.linspace(0, 1, int(0.05 * sr))
    return _normalize_audio(wave, peak=0.82)


def _synth_heartbeat(sr: int) -> np.ndarray:
    """Two-beat heartbeat pulse: lub-dub pattern, 1.2s total."""
    beat_dur_ms = 75
    beat_samples = int(sr * beat_dur_ms / 1000)
    t_beat = np.linspace(0, beat_dur_ms / 1000, beat_samples)

    def one_beat(freq: float, amplitude: float) -> np.ndarray:
        wave = np.sin(2 * np.pi * freq * t_beat) * np.exp(-60.0 * t_beat) * amplitude
        return wave

    lub  = one_beat(55.0, 0.85)   # lower, deeper
    dub  = one_beat(70.0, 0.65)   # slightly higher

    gap1 = np.zeros(int(sr * 0.10))  # 100ms gap between lub and dub
    gap2 = np.zeros(int(sr * 0.75))  # 750ms before potential next beat

    wave = np.concatenate([lub, gap1, dub, gap2])
    return _normalize_audio(wave, peak=0.80)


def _synth_glitch(sr: int) -> np.ndarray:
    """Digital glitch: bursts of clipped noise + pitched stutter, 0.6s."""
    dur = 0.6
    t   = np.linspace(0, dur, int(sr * dur))
    # White noise with rhythmic gating
    noise = np.random.randn(len(t))
    # Gate: 8 bursts
    n_bursts = 8
    gate = np.zeros(len(t))
    for i in range(n_bursts):
        start = int(i * len(t) / n_bursts)
        end   = start + int(len(t) / (n_bursts * 2))
        gate[start:end] = 1.0
    # Pitched component
    pitch_wave = np.sin(2 * np.pi * random.choice([440, 880, 1760]) * t) * 0.3
    wave = (noise * gate + pitch_wave) * 0.7
    # Hard clip for digital distortion character
    wave = np.clip(wave, -0.6, 0.6)
    return _normalize_audio(wave, peak=0.75)


def _synth_whisper(sr: int) -> np.ndarray:
    """Eerie whisper texture: band-pass filtered noise, 2.5s."""
    dur = 2.5
    n   = int(sr * dur)
    noise = np.random.randn(n)
    # Band-pass filter via two one-pole filters (simple IIR)
    # High-pass at ~200Hz, low-pass at ~2000Hz → voice-band noise
    alpha_hp = np.exp(-2 * np.pi * 200 / sr)
    alpha_lp = np.exp(-2 * np.pi * 2000 / sr)
    hp_out = np.zeros(n)
    lp_out = np.zeros(n)
    prev_hp = 0.0
    prev_lp = 0.0
    prev_in = 0.0
    for i in range(n):
        # High-pass
        hp_out[i] = alpha_hp * (prev_hp + noise[i] - prev_in)
        prev_hp   = hp_out[i]
        prev_in   = noise[i]
        # Low-pass
        lp_out[i] = prev_lp + (1 - alpha_lp) * (hp_out[i] - prev_lp)
        prev_lp   = lp_out[i]
    # Envelope: fade in/out
    env = np.hanning(n) * 0.5 + 0.1
    wave = lp_out * env
    return _normalize_audio(wave, peak=0.55)


def _synth_outro_dark(sr: int) -> np.ndarray:
    """Dark outro: descending tone with long fade, 4s."""
    dur = 4.0
    t   = np.linspace(0, dur, int(sr * dur))
    # Descending frequency
    freq_env = 220.0 * np.exp(-t * 0.5)
    phase    = 2 * np.pi * np.cumsum(freq_env) / sr
    tone     = np.sin(phase) * 0.7
    # Sub rumble that fades
    rumble   = np.sin(2 * np.pi * 40 * t) * 0.3
    wave     = (tone + rumble) * np.exp(-0.6 * t)
    return _normalize_audio(wave, peak=0.70)


def _synth_dark_drone_short(sr: int, duration_sec: float = 8.0) -> np.ndarray:
    """Short dark drone for DARK_AMBIENT_BED marker (as discrete event)."""
    return _generate_dark_drone_array(sr, duration_sec, peak=0.60)


# ─────────────────────────────────────────────
# PROGRAMMATIC MUSIC BED GENERATION
# ─────────────────────────────────────────────

def _generate_dark_drone(duration_sec: float, output_path: Path) -> None:
    """
    Generates a full-length dark ambient drone as the music bed.
    Characteristics: deep bass drone (A1=55Hz), minor dissonance, slow LFO.
    """
    try:
        sr      = AUDIO_SAMPLE_RATE
        samples = _generate_dark_drone_array(sr, duration_sec, peak=0.65)
        _save_numpy_as_mp3(samples, sr, output_path)
        log.info(f"Generated dark drone music bed: {duration_sec:.0f}s → {output_path.name}")
    except Exception as exc:
        log.error(f"Music bed generation failed: {exc}")
        # Write silence so pipeline can continue
        from pydub import AudioSegment
        silence = AudioSegment.silent(
            duration=int(duration_sec * 1000), frame_rate=AUDIO_SAMPLE_RATE
        )
        silence.export(str(output_path), format="mp3", bitrate=AUDIO_BITRATE)


def _generate_dark_drone_array(sr: int, duration_sec: float, peak: float = 0.65) -> np.ndarray:
    """
    Creates a multi-layer dark ambient drone array:
      - 55Hz (A1) fundamental — deep ominous root
      - 82.5Hz (E2) perfect fifth — adds body
      - 65.4Hz (C2) minor third above A1 — harmonic tension
      - 110Hz (A2) octave — harmonic richness
      - 0.05Hz LFO amplitude modulation — slow "breathing"
      - Subtle low-frequency noise — organic texture
    """
    n = int(sr * duration_sec)
    t = np.linspace(0, duration_sec, n)

    # Slow amplitude LFO: 0.05Hz (20-second cycle)
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.05 * t)

    # Drone layers
    drone  = 0.55 * np.sin(2 * np.pi * 55.0   * t)   # A1 fundamental
    drone += 0.25 * np.sin(2 * np.pi * 82.5   * t)   # E2 fifth
    drone += 0.20 * np.sin(2 * np.pi * 65.4   * t)   # C2 minor 3rd
    drone += 0.15 * np.sin(2 * np.pi * 110.0  * t)   # A2 octave
    drone += 0.08 * np.sin(2 * np.pi * 164.8  * t)   # E3 — upper partial

    # Very subtle detuning for organic feel
    detune_lfo = 1.0 + 0.002 * np.sin(2 * np.pi * 0.07 * t)
    drone_detuned = 0.10 * np.sin(2 * np.pi * 55.0 * detune_lfo * t)

    # Low-frequency organic noise texture
    noise = np.random.randn(n) * 0.04
    # Smooth noise with simple moving average
    window = int(sr * 0.01)
    if window > 1:
        noise = np.convolve(noise, np.ones(window) / window, mode='same')

    combined = (drone + drone_detuned + noise) * lfo

    # Fade in (5s) and fade out (8s)
    fade_in_samples  = min(int(5.0 * sr), n // 4)
    fade_out_samples = min(int(8.0 * sr), n // 3)
    combined[:fade_in_samples]  *= np.linspace(0, 1, fade_in_samples)
    combined[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

    return _normalize_audio(combined, peak=peak)


# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def _normalize_audio(samples: np.ndarray, peak: float = 0.85) -> np.ndarray:
    """Normalizes numpy float samples to [-peak, peak]."""
    max_val = np.max(np.abs(samples))
    if max_val < 1e-10:
        return samples
    return samples * (peak / max_val)


def _save_numpy_as_mp3(samples: np.ndarray, sr: int, output_path: Path) -> None:
    """
    Converts float64 numpy array to int16 PCM then exports as MP3 via pydub.
    """
    from pydub import AudioSegment

    # Clip and convert to int16
    samples_clipped = np.clip(samples, -1.0, 1.0)
    pcm             = (samples_clipped * 32767).astype(np.int16)

    audio = AudioSegment(
        data=pcm.tobytes(),
        sample_width=2,
        frame_rate=sr,
        channels=1,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(output_path), format="mp3", bitrate=AUDIO_BITRATE)

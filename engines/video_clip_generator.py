"""
engines/video_clip_generator.py
Karma Vault Stories — Phase B Text-to-Video Clip Generation Engine

Cascade: Runway Gen-4 → Pika Labs → Models Lab → Replicate SVD → None
Parallel job submission: up to _MAX_PARALLEL_JOBS Runway tasks submitted
simultaneously, then polled in batches. Clips cached in Cloudflare R2 to
avoid regenerating identical scene prompts across daily pipeline runs.
"""

from __future__ import annotations

import base64
import hashlib
import time
import json
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.file_manager import video_path, image_path
from utils.r2_cache import R2Cache, clip_cache_key
from utils.api_client import (
    http_get, http_get_json, http_post_json,
    download_image, with_retry,
)

log = get_logger(__name__)

_CLIP_DURATION_SEC = 5
_POLL_INTERVAL_SEC = 8
_MAX_POLL_ATTEMPTS = 30      # 30 × 8s = 240s max per clip
_MAX_PARALLEL_JOBS = 6       # Runway jobs submitted simultaneously

_RUNWAY_BASE    = "https://api.dev.runwayml.com"
_RUNWAY_VERSION = "2024-11-06"
_RUNWAY_MODEL   = "gen4_turbo"

_PIKA_BASE      = "https://api.pika.art"
_MODELSLAB_BASE = "https://modelslab.com/api/v6"


# ─────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────

def generate_clips_for_scenes(
    scenes:  list[dict],
    run_id:  str,
    country: str,
    pillar:  str,
) -> dict[int, Optional[Path]]:
    """
    Generates (or retrieves cached) video clips for every scene.
    Returns {scene_idx: Path_to_clip | None}.
    None means all providers failed — scene_builder falls back to static image.
    """
    from config.settings import RUNWAY_API

    results: dict[int, Optional[Path]] = {}
    r2 = R2Cache.get()

    # ── Phase 1: R2 cache hits ───────────────────────────────────
    uncached: list[tuple[int, dict]] = []
    for i, scene in enumerate(scenes):
        prompt = _build_prompt(scene, country, pillar)
        key    = clip_cache_key(prompt)
        dest   = video_path(run_id, f"clip_{i:04d}.mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)

        if r2.is_available() and r2.get_clip(key, dest):
            results[i] = dest
            log.info(f"  Clip {i:04d}: R2 cache hit")
        else:
            uncached.append((i, scene))

    if not uncached:
        return results

    log.info(f"Generating {len(uncached)} clips via T2V APIs...")

    # ── Phase 2: Parallel Runway if key available ────────────────
    if RUNWAY_API:
        uncached = _runway_batch(uncached, results, run_id, country, pillar, r2)

    # ── Phase 3: Serial fallback for anything Runway missed ──────
    for i, scene in uncached:
        if i in results:
            continue
        clip = _generate_single_fallback(scene, run_id, country, pillar, i, r2)
        results[i] = clip

    succeeded = sum(1 for v in results.values() if v is not None)
    log.info(f"Clip generation complete: {succeeded}/{len(scenes)} succeeded.")
    return results


# ─────────────────────────────────────────────
# RUNWAY PARALLEL BATCH
# ─────────────────────────────────────────────

def _runway_batch(
    uncached: list[tuple[int, dict]],
    results:  dict,
    run_id:   str,
    country:  str,
    pillar:   str,
    r2:       R2Cache,
) -> list[tuple[int, dict]]:
    """
    Submits up to _MAX_PARALLEL_JOBS Runway tasks simultaneously.
    Polls all pending tasks together until done or timeout.
    Returns list of (scene_idx, scene) pairs that still need fallback generation.
    """
    still_need_fallback: list[tuple[int, dict]] = []
    batch_size = _MAX_PARALLEL_JOBS

    for batch_start in range(0, len(uncached), batch_size):
        batch = uncached[batch_start : batch_start + batch_size]

        # Submit all jobs in this batch
        pending: list[tuple[int, str, Path, str]] = []  # (idx, task_id, out_path, prompt)
        for i, scene in batch:
            prompt  = _build_prompt(scene, country, pillar)
            out     = video_path(run_id, f"clip_{i:04d}.mp4")
            ref_b64 = _get_reference_b64(scene, run_id, i)
            task_id = _runway_submit(prompt, ref_b64)
            if task_id:
                pending.append((i, task_id, out, prompt))
                log.info(f"  Runway submitted: scene {i:04d} task={task_id[:16]}...")
            else:
                still_need_fallback.append((i, scene))

        if not pending:
            continue

        # Poll until all done or timeout
        _runway_poll_pending(pending, results, r2)

        # Anything still in pending after polling timed out → fallback
        done_ids = set(results.keys())
        for i, scene in batch:
            if i not in done_ids:
                still_need_fallback.append((i, scene))

        time.sleep(1)

    return still_need_fallback


def _runway_submit(prompt: str, ref_b64: Optional[str]) -> Optional[str]:
    """Submits one Runway job. Returns task_id or None."""
    from config.settings import RUNWAY_API
    if not RUNWAY_API:
        return None
    try:
        payload: dict = {
            "model":       _RUNWAY_MODEL,
            "promptText":  prompt[:400],
            "ratio":       "1280:768",
            "duration":    _CLIP_DURATION_SEC,
        }
        if ref_b64:
            payload["promptImage"] = ref_b64

        resp = http_post_json(
            f"{_RUNWAY_BASE}/v1/image_to_video",
            payload,
            headers={
                "Authorization":    f"Bearer {RUNWAY_API}",
                "X-Runway-Version": _RUNWAY_VERSION,
            },
            timeout=30,
        )
        return resp.get("id")
    except Exception as exc:
        log.warning(f"  Runway submit error: {exc}")
        return None


def _runway_poll_pending(
    pending: list[tuple[int, str, Path, str]],
    results: dict,
    r2:      R2Cache,
) -> None:
    """Polls all pending Runway tasks until all complete or timeout."""
    from config.settings import RUNWAY_API
    remaining = list(pending)

    for attempt in range(_MAX_POLL_ATTEMPTS):
        if not remaining:
            break
        time.sleep(_POLL_INTERVAL_SEC)
        still_running = []

        for (idx, task_id, out_path, prompt) in remaining:
            try:
                resp   = http_get_json(
                    f"{_RUNWAY_BASE}/v1/tasks/{task_id}",
                    headers={
                        "Authorization":    f"Bearer {RUNWAY_API}",
                        "X-Runway-Version": _RUNWAY_VERSION,
                    },
                    timeout=15,
                )
                status  = resp.get("status", "PENDING")
                outputs = resp.get("output", [])

                if status == "SUCCEEDED" and outputs:
                    ok = download_image(outputs[0], str(out_path), timeout=120)
                    if ok and out_path.exists() and out_path.stat().st_size > 20_000:
                        results[idx] = out_path
                        log.info(
                            f"  Clip {idx:04d}: Runway DONE "
                            f"({out_path.stat().st_size // 1024}KB)"
                        )
                        if r2.is_available():
                            r2.put_clip(clip_cache_key(prompt), out_path)
                    else:
                        results[idx] = None
                        log.warning(f"  Clip {idx:04d}: Runway download failed.")
                elif status == "FAILED":
                    results[idx] = None
                    log.warning(f"  Clip {idx:04d}: Runway FAILED.")
                else:
                    still_running.append((idx, task_id, out_path, prompt))
            except Exception as exc:
                log.debug(f"  Runway poll error (task {task_id[:12]}...): {exc}")
                still_running.append((idx, task_id, out_path, prompt))

        remaining = still_running
        if not remaining:
            break

    # Timeout — mark remaining as incomplete (caller handles fallback)
    for (idx, task_id, _, _) in remaining:
        log.warning(
            f"  Clip {idx:04d}: Runway timed out "
            f"after {attempt * _POLL_INTERVAL_SEC}s."
        )


# ─────────────────────────────────────────────
# SERIAL FALLBACK PROVIDERS
# ─────────────────────────────────────────────

def _generate_single_fallback(
    scene:   dict,
    run_id:  str,
    country: str,
    pillar:  str,
    idx:     int,
    r2:      R2Cache,
) -> Optional[Path]:
    """Tries Pika → ModelsLab → Replicate SVD for one scene."""
    prompt  = _build_prompt(scene, country, pillar)
    out     = video_path(run_id, f"clip_{idx:04d}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    if _pika_generate(prompt, out):
        log.info(f"  Clip {idx:04d}: Pika DONE ({out.stat().st_size // 1024}KB)")
        if r2.is_available():
            r2.put_clip(clip_cache_key(prompt), out)
        return out

    if _modelslab_generate(prompt, out):
        log.info(f"  Clip {idx:04d}: ModelsLab DONE ({out.stat().st_size // 1024}KB)")
        if r2.is_available():
            r2.put_clip(clip_cache_key(prompt), out)
        return out

    ref_b64 = _get_reference_b64(scene, run_id, idx)
    if _replicate_svd_generate(prompt, ref_b64, out):
        log.info(f"  Clip {idx:04d}: Replicate SVD DONE ({out.stat().st_size // 1024}KB)")
        if r2.is_available():
            r2.put_clip(clip_cache_key(prompt), out)
        return out

    # ── Pexels stock video — final fallback before giving up ────────
    pexels_clip = _pexels_video_fallback(scene, pillar, out, idx)
    if pexels_clip:
        log.info(f"  Clip {idx:04d}: Pexels stock video ({pexels_clip.stat().st_size // 1024}KB)")
        return pexels_clip

    log.warning(f"  Clip {idx:04d}: all T2V + Pexels providers failed — static image will be used.")
    return None


# ─────────────────────────────────────────────
# PEXELS STOCK VIDEO FALLBACK
# ─────────────────────────────────────────────

def _pexels_video_fallback(
    scene:  dict,
    pillar: str,
    out:    Path,
    idx:    int,
) -> Optional[Path]:
    """
    Downloads a dark cinematic stock video from Pexels as a T2V fallback.
    Uses pillar-specific queries to ensure thematic relevance.
    Trims to the required scene duration using FFmpeg -t flag.
    """
    try:
        from utils.api_client import fetch_pexels_videos, get_pexels_video_queries_for_pillar
        from utils.api_client import download_image

        queries = get_pexels_video_queries_for_pillar(pillar)
        # Mix in scene-specific terms for better relevance
        part_id = scene.get("part_id", "")
        if part_id in ("climax", "escalation"):
            queries = queries[:2] + [
                "dark dramatic intense scene",
                "horror atmosphere dark shadows",
            ]
        elif part_id == "hook":
            queries = ["dark atmospheric dramatic opening"] + queries[:2]

        for query in queries[:4]:
            results = fetch_pexels_videos(query=query, count=3)
            for result in results:
                url      = result.get("url", "")
                duration = int(result.get("duration", 0))
                if not url or duration < 3:
                    continue

                raw_path = out.parent / f"_pexels_raw_{idx:04d}.mp4"
                ok = download_image(url, str(raw_path), timeout=60)
                if not ok or not raw_path.exists() or raw_path.stat().st_size < 100_000:
                    raw_path.unlink(missing_ok=True)
                    continue

                # Apply dark cinematic grading via FFmpeg
                import subprocess
                result_cmd = subprocess.run([
                    "ffmpeg", "-y",
                    "-i", str(raw_path),
                    "-vf", (
                        "scale=1920:1080:force_original_aspect_ratio=decrease,"
                        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
                        "eq=contrast=1.25:brightness=-0.08:saturation=0.6,"
                        "vignette=PI/4,"
                        "format=yuv420p"
                    ),
                    "-c:v", "libx264", "-preset", "faster", "-crf", "23",
                    "-an",
                    str(out),
                ], capture_output=True, timeout=120)

                raw_path.unlink(missing_ok=True)

                if result_cmd.returncode == 0 and out.exists() and out.stat().st_size > 50_000:
                    return out
                out.unlink(missing_ok=True)

    except Exception as exc:
        from utils.logger import get_logger
        get_logger(__name__).debug(f"Pexels video fallback failed (scene {idx}): {exc}")

    return None


# ─────────────────────────────────────────────
# PIKA LABS
# ─────────────────────────────────────────────

def _pika_generate(prompt: str, out_path: Path) -> bool:
    from config.settings import PIKA_LABS
    if not PIKA_LABS:
        return False
    try:
        resp = http_post_json(
            f"{_PIKA_BASE}/v1/generate",
            {
                "promptText":  prompt[:300],
                "style":       "cinematic",
                "duration":    _CLIP_DURATION_SEC,
                "frameRate":   24,
                "resolution":  "1080p",
                "camera":      {"zoom": "in", "tilt": "none", "rotate": "none", "pan": "none"},
            },
            headers={"Authorization": f"Bearer {PIKA_LABS}"},
            timeout=30,
        )
        task_id = resp.get("id") or resp.get("task_id") or resp.get("job_id")
        if not task_id:
            return False

        for _ in range(_MAX_POLL_ATTEMPTS):
            time.sleep(_POLL_INTERVAL_SEC)
            try:
                poll = http_get_json(
                    f"{_PIKA_BASE}/v1/generations/{task_id}",
                    headers={"Authorization": f"Bearer {PIKA_LABS}"},
                    timeout=15,
                )
                state = (poll.get("status") or "").lower()
                if state in ("succeeded", "complete", "success", "finished"):
                    url = (
                        poll.get("resultUrl")
                        or poll.get("video_url")
                        or ((poll.get("result") or {}).get("url"))
                        or ((poll.get("videos") or [{}])[0].get("url"))
                    )
                    if url:
                        return download_image(url, str(out_path), timeout=120)
                if state in ("failed", "error", "cancelled"):
                    return False
            except Exception:
                pass
    except Exception as exc:
        log.debug(f"Pika error: {exc}")
    return False


# ─────────────────────────────────────────────
# MODELS LAB
# ─────────────────────────────────────────────

def _modelslab_generate(prompt: str, out_path: Path) -> bool:
    from config.settings import MODELS_LAB
    if not MODELS_LAB:
        return False
    try:
        resp = http_post_json(
            f"{_MODELSLAB_BASE}/video/text2video",
            {
                "key":             MODELS_LAB,
                "prompt":          prompt[:300],
                "negative_prompt": "text, watermark, letters, blurry, cartoon, anime, nsfw",
                "width":           1280,
                "height":          720,
                "num_frames":      120,
                "fps":             24,
                "guidance_scale":  7.5,
                "output_type":     "mp4",
            },
            timeout=40,
        )
        status   = (resp.get("status") or "").lower()
        outputs  = resp.get("output") or resp.get("future_links") or []
        out_url  = outputs[0] if outputs else None

        if status == "success" and out_url:
            return download_image(out_url, str(out_path), timeout=120)

        fetch_id = resp.get("id")
        if not fetch_id:
            return False

        for _ in range(_MAX_POLL_ATTEMPTS):
            time.sleep(_POLL_INTERVAL_SEC)
            try:
                poll = http_post_json(
                    f"{_MODELSLAB_BASE}/video/fetch/{fetch_id}",
                    {"key": MODELS_LAB},
                    timeout=20,
                )
                st  = (poll.get("status") or "").lower()
                out = (poll.get("output") or [None])[0]
                if st == "success" and out:
                    return download_image(out, str(out_path), timeout=120)
                if st in ("failed", "error"):
                    return False
            except Exception:
                pass
    except Exception as exc:
        log.debug(f"ModelsLab error: {exc}")
    return False


# ─────────────────────────────────────────────
# REPLICATE SVD
# ─────────────────────────────────────────────

def _replicate_svd_generate(
    prompt:  str,
    ref_b64: Optional[str],
    out_path: Path,
) -> bool:
    from config.settings import REPLICATE_API_TOKEN
    if not REPLICATE_API_TOKEN:
        return False
    if not ref_b64:
        return False
    try:
        resp = http_post_json(
            "https://api.replicate.com/v1/predictions",
            {
                "version": "7d6a2f9c4754477b12c14ed2a58f89bb85128edcdd581d24ce58b6926029de08",
                "input": {
                    "image":             f"data:image/jpeg;base64,{ref_b64}",
                    "cond_aug":          0.02,
                    "decoding_t":        14,
                    "video_length":      25,
                    "sizing_strategy":   "maintain_aspect_ratio",
                    "motion_bucket_id":  40,
                    "fps_id":            6,
                },
            },
            headers={
                "Authorization": f"Token {REPLICATE_API_TOKEN}",
                "Prefer":        "wait=60",
            },
            timeout=90,
        )
        output = resp.get("output", [])
        if isinstance(output, list) and output:
            return download_image(output[0], str(out_path), timeout=120)

        pred_id = resp.get("id")
        if not pred_id:
            return False

        for _ in range(_MAX_POLL_ATTEMPTS):
            time.sleep(10)
            try:
                poll = http_get_json(
                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                    headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"},
                    timeout=20,
                )
                if poll.get("status") == "succeeded":
                    out = poll.get("output", [])
                    if out:
                        return download_image(out[0], str(out_path), timeout=120)
                if poll.get("status") in ("failed", "canceled"):
                    return False
            except Exception:
                pass
    except Exception as exc:
        log.debug(f"Replicate SVD error: {exc}")
    return False


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

_PILLAR_STYLE: dict[str, str] = {
    "paranormal_haunted_jinn":      "supernatural eerie atmosphere, candles, mist, slow drift",
    "human_betrayal_revenge":       "tense noir, dramatic side lighting, slow push-in",
    "mystery_disappearances":       "cold desaturated, empty road, fog, suspenseful pan",
    "disturbing_accidents_records": "documentary handheld, clinical, desaturated",
    "historical_dark_secrets":      "warm amber tones, aged textures, slow zoom",
    "ai_original_horror":           "cold blue LED glow, server room, technological dread",
    "secret_double_life":           "split shadows, venetian blind light, film noir",
    "internet_confession":          "screen-glow dark room, intimate handheld",
    "urban_legends_paranormal":     "night street, low angle, creeping fog",
    "true_shocking_crime":          "crime scene blue flash, clinical cold, static wide",
}

_PART_CAMERA: dict[str, str] = {
    "hook":        "slow push-in toward subject, opening shot",
    "context":     "wide establishing, gentle pan",
    "first_sign":  "slow creep toward clue",
    "escalation":  "creeping slow zoom, building tension",
    "climax":      "static wide, subtle handheld shake",
    "aftermath":   "slow pull-back reveal, lonely",
    "resolution":  "slow fade-out, contemplative",
}


def _build_prompt(scene: dict, country: str, pillar: str) -> str:
    scene_desc = (
        scene.get("scene_prompt")
        or scene.get("asset_prompt")
        or "dark cinematic interior"
    )
    part_id    = scene.get("part_id", "escalation")
    style      = _PILLAR_STYLE.get(pillar, "cinematic dark dramatic")
    camera     = _PART_CAMERA.get(part_id, "slow drift")

    return (
        f"Cinematic dark documentary, {country}, {style}, {camera}. "
        f"{scene_desc[:180].strip()}. "
        f"Photorealistic, 4K, film grain, no text, no captions, no logos."
    )[:400]


# ─────────────────────────────────────────────
# REFERENCE IMAGE BUILDER
# ─────────────────────────────────────────────

def _get_reference_b64(
    scene:   dict,
    run_id:  str,
    idx:     int,
) -> Optional[str]:
    """
    Gets a reference still image as base64 for image-to-video models.
    Uses the scene's existing asset_path if it's a stock photo,
    otherwise generates a quick AI still via the image_generator.
    """
    # Option 1: use already-fetched stock image
    existing = scene.get("asset_path", "")
    if existing and Path(existing).exists():
        try:
            return base64.b64encode(Path(existing).read_bytes()).decode()
        except Exception:
            pass

    # Option 2: generate a new AI still
    try:
        from engines.image_generator import generate_ai_image
        ref_path = image_path(run_id, f"ref_still_{idx:04d}.jpg")
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = (
            scene.get("scene_prompt")
            or scene.get("asset_prompt")
            or "dark cinematic dramatic scene"
        )
        if generate_ai_image(prompt[:200], ref_path):
            return base64.b64encode(ref_path.read_bytes()).decode()
    except Exception as exc:
        log.debug(f"Reference image gen failed (scene {idx}): {exc}")

    return None

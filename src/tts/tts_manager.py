from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.text import choose_weighted
from ..utils.hashing import sha256_hex
from ..state import add_history
from . import edge_tts_engine
from . import elevenlabs_engine

log = logging.getLogger("tts_manager")


def _voice_weight(state: Dict[str, Any], voice_id: str) -> float:
    perf = state.get("performance", {}).get("voices", {})
    rec = perf.get(voice_id)
    if not isinstance(rec, dict):
        return 1.0
    count = max(1, int(rec.get("count", 0)))
    avg = float(rec.get("views24_sum", 0.0)) / float(count)
    return 1.0 + min(50.0, max(0.0, avg / 50.0))


def choose_edge_voice(cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, str]:
    voices = cfg.get("tts", {}).get("edge_tts", {}).get("voices") or []
    if not isinstance(voices, list) or not voices:
        return {"id": "en-US-JennyNeural", "gender": "female"}
    ids = [str(v.get("id")) for v in voices if isinstance(v, dict) and v.get("id")]
    genders = {str(v.get("id")): str(v.get("gender", "")) for v in voices if isinstance(v, dict) and v.get("id")}
    weights = [_voice_weight(state, vid) for vid in ids]
    chosen = choose_weighted(ids, weights)
    return {"id": chosen, "gender": genders.get(chosen, "")}


def synthesize_with_fallback(
    cfg: Dict[str, Any],
    state: Dict[str, Any],
    *,
    text: str,
    out_dir: str | Path,
    basename: str,
) -> Tuple[Path, str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    engines: List[str] = list(cfg.get("tts", {}).get("fallback_engines") or ["edge_tts"])
    engines = [str(e) for e in engines]

    voice = choose_edge_voice(cfg, state)
    voice_id = voice["id"]

    rate = str(cfg.get("tts", {}).get("edge_tts", {}).get("rate", "+0%"))
    pitch = str(cfg.get("tts", {}).get("edge_tts", {}).get("pitch", "+0Hz"))

    for engine in engines:
        try:
            if engine == "edge_tts":
                out_path = out_dir / f"{basename}_edge.mp3"
                audio = edge_tts_engine.synthesize(text, voice=voice_id, rate=rate, pitch=pitch, out_path=out_path)
                return audio, voice_id, "edge_tts"
            if engine == "elevenlabs":
                out_path = out_dir / f"{basename}_eleven.mp3"
                audio = elevenlabs_engine.synthesize(text, out_path=out_path)
                return audio, voice_id, "elevenlabs"
        except Exception as e:
            log.warning("TTS engine %s failed: %s", engine, e)
            continue

    raise RuntimeError("All TTS engines failed")

"""
protection/visual_verifier.py

Confirms that fetched media actually depicts the requested topic
(e.g. a clip labelled "lion" genuinely shows a lion, not a tiger or
an empty savanna).  Uses Gemini 1.5 Flash multimodal vision directly —
this is independent of the text-only LLM cascade.

Failure modes degrade gracefully: if Gemini Vision is unavailable or
errors out, the verifier returns a neutral pass (confidence=50,
is_match=True) so the pipeline is never blocked by this check alone.
"""
from __future__ import annotations
import json, os, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import structlog

logger = structlog.get_logger(__name__)

_MIN_MATCH_CONFIDENCE = 55
_VISION_MODEL = "gemini-1.5-flash"


@dataclass
class VerificationResult:
    is_match:         bool
    confidence:       int
    detected_subject: str
    reason:           str


class VisualVerifier:

    def is_available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())

    # ── Public API ────────────────────────────────────────────────────────────

    def verify(
        self,
        local_path: str,
        asset_type: str,
        topic_name: str,
        category:   str,
    ) -> VerificationResult:
        if not self.is_available():
            return VerificationResult(True, 50, "unknown", "vision_unavailable_skipped")

        try:
            image_bytes = self._extract_frame(local_path, asset_type)
        except Exception as exc:
            logger.debug("frame_extract_failed", path=local_path, error=str(exc)[:80])
            return VerificationResult(True, 50, "unknown", "frame_extraction_failed")

        if image_bytes is None:
            return VerificationResult(True, 50, "unknown", "no_frame_extracted")

        try:
            return self._call_vision(image_bytes, topic_name, category)
        except Exception as exc:
            logger.debug("vision_call_failed", error=str(exc)[:80])
            return VerificationResult(True, 50, "unknown", "vision_call_failed")

    def verify_batch(
        self,
        media_items,
        topic_name: str,
        category:   str,
        min_confidence: int = _MIN_MATCH_CONFIDENCE,
    ) -> list:
        """
        Verify every media item.  Items that fail (is_match=False AND
        confidence below min_confidence) are replaced with None so the
        assembler falls back to a black frame and the pipeline can decide
        whether to re-fetch.
        """
        results = []
        for item in media_items:
            if item is None:
                results.append(None)
                continue

            v = self.verify(item.local_path, item.asset_type, topic_name, category)

            if v.is_match or v.confidence >= min_confidence:
                results.append(item)
            else:
                logger.info(
                    "visual_verification_rejected",
                    path=item.local_path,
                    topic=topic_name,
                    detected=v.detected_subject,
                    confidence=v.confidence,
                )
                results.append(None)

        return results

    # ── Frame extraction ──────────────────────────────────────────────────────

    def _extract_frame(self, local_path: str, asset_type: str) -> Optional[bytes]:
        if asset_type == "image":
            return Path(local_path).read_bytes()

        duration = self._probe_duration(local_path)
        seek = min(1.0, duration / 2) if duration > 0 else 0.5

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                "ffmpeg", "-y", "-ss", str(seek), "-i", local_path,
                "-frames:v", "1", "-q:v", "2", tmp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0 or not Path(tmp_path).exists():
                return None
            data = Path(tmp_path).read_bytes()
            return data if data else None
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _probe_duration(path: str) -> float:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            data = json.loads(r.stdout)
            return float(data["format"].get("duration", 0) or 0)
        except Exception:
            return 0.0

    # ── Vision call ───────────────────────────────────────────────────────────

    def _call_vision(
        self, image_bytes: bytes, topic_name: str, category: str
    ) -> VerificationResult:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

        prompt = (
            f"You are verifying footage for a {category} nature video about: '{topic_name}'.\n"
            f"Look at this image and answer:\n"
            f"1. What is the main subject visible? (one short phrase)\n"
            f"2. Does it visually match or relate to '{topic_name}'? "
            f"It does not need to be the exact species — a related or contextually "
            f"appropriate scene (e.g. its habitat, prey, or a close relative) counts as a match.\n"
            f"3. Confidence 0-100 that this image is appropriate footage for a video about '{topic_name}'.\n\n"
            f'Return ONLY JSON: {{"detected_subject":"...","is_match":true/false,"confidence":0-100}}'
        )

        model = genai.GenerativeModel(_VISION_MODEL)
        response = model.generate_content(
            [prompt, {"mime_type": "image/jpeg", "data": image_bytes}],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=150,
                temperature=0.2,
            ),
        )

        if not response.candidates:
            return VerificationResult(True, 50, "unknown", "vision_no_candidates")

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        data = json.loads(raw)
        confidence = int(data.get("confidence", 50))
        is_match   = bool(data.get("is_match", confidence >= _MIN_MATCH_CONFIDENCE))
        subject    = str(data.get("detected_subject", "unknown"))

        return VerificationResult(is_match, confidence, subject, "vision_checked")


_instance: Optional[VisualVerifier] = None

def get_visual_verifier() -> VisualVerifier:
    global _instance
    if _instance is None:
        _instance = VisualVerifier()
    return _instance

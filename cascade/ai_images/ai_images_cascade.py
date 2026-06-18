"""
cascade/ai_images/ai_images_cascade.py
Used when ALL real footage and real images have been exhausted for a segment.
"""
from __future__ import annotations
import os, tempfile
from dataclasses import dataclass
from typing import Dict, Optional
import structlog
from cascade.base_provider import ProviderResult
from cascade.cascade_manager import CascadeManager, CircuitBreaker
from cascade.ai_images.getimg_provider    import GetImgProvider
from cascade.ai_images.stability_provider import StabilityProvider
from cascade.ai_images.dezgo_provider     import DezgoProvider
from cascade.ai_images.ai_horde_provider  import AIHordeProvider

logger = structlog.get_logger(__name__)
_SHARED_BREAKER = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300)


@dataclass
class AIImageResult:
    local_path:          str
    provider_source_id:  str
    width:               int
    height:              int
    file_size_bytes:     int
    provider:            str
    prompt:              str
    is_ai_generated:     bool = True
    license:             str  = "generated"


class AIImagesCascade:
    def __init__(self) -> None:
        self._getimg    = GetImgProvider()
        self._stability = StabilityProvider()
        self._dezgo     = DezgoProvider()
        self._horde     = AIHordeProvider()

    def generate_image(
        self,
        prompt: str,
        download_dir: Optional[str] = None,
        width:  int = 1024,
        height: int = 1024,
    ) -> AIImageResult:
        if not prompt.strip():
            raise ValueError("generate_image() received empty prompt.")
        if download_dir is None:
            download_dir = tempfile.mkdtemp(prefix="yta_ai_img_")
        os.makedirs(download_dir, exist_ok=True)

        manager = CascadeManager(
            providers=[self._getimg, self._stability, self._dezgo, self._horde],
            category="ai_images",
            max_retries_per_provider=1,
            circuit_breaker=_SHARED_BREAKER,
        )
        result: ProviderResult = manager.execute(
            prompt=prompt,
            download_dir=download_dir,
            width=width,
            height=height,
        )
        if not result.success:
            raise RuntimeError(
                f"AI Images cascade exhausted. prompt={prompt[:60]!r}. "
                f"Error: {result.error}"
            )
        d = result.data
        img = AIImageResult(
            local_path=d["local_path"],
            provider_source_id=d["provider_source_id"],
            width=d["width"],
            height=d["height"],
            file_size_bytes=d["file_size_bytes"],
            provider=result.provider_used,
            prompt=prompt,
        )
        logger.info("ai_images_cascade_success",
                    provider=img.provider, prompt=prompt[:60])
        return img

    def get_status(self) -> Dict:
        return {
            "category": "ai_images",
            "circuit_status": _SHARED_BREAKER.get_status(),
        }


_ai_images_instance: Optional[AIImagesCascade] = None


def get_ai_images() -> AIImagesCascade:
    global _ai_images_instance
    if _ai_images_instance is None:
        _ai_images_instance = AIImagesCascade()
    return _ai_images_instance

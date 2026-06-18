"""
cascade/ai_images/dezgo_provider.py
Required GitHub Secret: DEZGO
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict
import requests, structlog
from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)
_URL = "https://api.dezgo.com/text2image"
_NEG = "text, watermark, cartoon, anime, blurry, low quality, nsfw"


class DezgoProvider(BaseProvider):
    provider_name    = "dezgo"
    is_free_tier     = False
    cascade_category = "ai_images"

    def is_available(self) -> bool:
        return self.env_present("DEZGO")

    def execute(self, **kwargs: Any) -> ProviderResult:
        prompt:       str = kwargs.get("prompt", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_ai_images")
        width:        int = min(int(kwargs.get("width", 768)), 1024)
        height:       int = min(int(kwargs.get("height", 768)), 1024)

        if not prompt:
            return ProviderResult.failure(self.provider_name, "Empty prompt.")

        enhanced = (
            f"{prompt}, ultra-realistic, wildlife photography, 8k, "
            "professional nature photo, award winning"
        )
        try:
            resp = requests.post(
                _URL,
                headers={"X-Dezgo-Key": os.environ["DEZGO"]},
                data={
                    "prompt": enhanced, "negative_prompt": _NEG,
                    "model": "realistic_vision_v51",
                    "guidance": 7.5, "steps": 30, "seed": -1,
                    "width": width, "height": height, "format": "jpg",
                },
                timeout=120,
            )
            if resp.status_code == 429:
                return ProviderResult.failure(self.provider_name, "Dezgo rate limit.")
            if resp.status_code in (401, 403):
                return ProviderResult.failure(self.provider_name, "Dezgo auth failed.")
            resp.raise_for_status()
            img_bytes = resp.content
            if len(img_bytes) < 10_000:
                return ProviderResult.failure(self.provider_name, "Dezgo returned tiny image.")
            Path(download_dir).mkdir(parents=True, exist_ok=True)
            import hashlib
            sig = hashlib.md5(img_bytes[:256]).hexdigest()[:12]
            local_path = str(Path(download_dir) / f"dezgo_{sig}.jpg")
            Path(local_path).write_bytes(img_bytes)
            data: Dict[str, Any] = {
                "local_path": local_path, "source_url": _URL,
                "provider_source_id": sig,
                "width": width, "height": height,
                "file_size_bytes": len(img_bytes),
                "provider": self.provider_name,
                "license": "generated", "is_ai_generated": True, "prompt": prompt,
            }
            logger.info("dezgo_image_generated", prompt=prompt[:60])
            return ProviderResult(success=True, data=data,
                                  provider_used=self.provider_name,
                                  metadata={"prompt": prompt})
        except Exception as exc:
            return ProviderResult.failure(self.provider_name, f"Dezgo error: {exc}")

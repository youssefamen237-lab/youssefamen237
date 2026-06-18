"""
cascade/ai_images/stability_provider.py
Required GitHub Secret: STABILITY
"""
from __future__ import annotations
import base64, os
from pathlib import Path
from typing import Any, Dict
import requests, structlog
from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)
_MODEL     = "stable-diffusion-xl-1024-v1-0"
_ENDPOINT  = f"https://api.stability.ai/v1/generation/{_MODEL}/text-to-image"
_NEG = "text, watermark, cartoon, anime, illustration, blurry, low quality, nsfw, logo"


class StabilityProvider(BaseProvider):
    provider_name    = "stability"
    is_free_tier     = False
    cascade_category = "ai_images"

    def is_available(self) -> bool:
        return self.env_present("STABILITY")

    def execute(self, **kwargs: Any) -> ProviderResult:
        prompt:       str = kwargs.get("prompt", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_ai_images")
        width:        int = int(kwargs.get("width", 1024))
        height:       int = int(kwargs.get("height", 1024))

        if not prompt:
            return ProviderResult.failure(self.provider_name, "Empty prompt.")

        # SDXL requires dimensions that are multiples of 64 between 512-1536
        width  = max(512, min(1536, (width  // 64) * 64))
        height = max(512, min(1536, (height // 64) * 64))

        api_key = os.environ["STABILITY"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        enhanced = (
            f"{prompt}, ultra-realistic, wildlife photography, 8k, "
            "professional nature documentary, award-winning photo"
        )
        body = {
            "text_prompts": [
                {"text": enhanced,   "weight": 1.0},
                {"text": _NEG,       "weight": -1.0},
            ],
            "width": width, "height": height,
            "steps": 30, "samples": 1, "cfg_scale": 7.5,
        }
        try:
            resp = requests.post(_ENDPOINT, headers=headers, json=body, timeout=120)
            if resp.status_code == 429:
                return ProviderResult.failure(self.provider_name, "Stability rate limit.")
            if resp.status_code in (401, 403):
                return ProviderResult.failure(self.provider_name, "Stability auth failed.")
            resp.raise_for_status()
            artifacts = resp.json().get("artifacts", [])
            if not artifacts:
                return ProviderResult.failure(self.provider_name, "Stability returned no artifacts.")
            art = artifacts[0]
            if art.get("finishReason") not in ("SUCCESS", "success", None):
                return ProviderResult.failure(
                    self.provider_name, f"Stability finish reason: {art.get('finishReason')}")
            img_bytes = base64.b64decode(art["base64"])
            Path(download_dir).mkdir(parents=True, exist_ok=True)
            seed = str(art.get("seed", "0"))
            local_path = str(Path(download_dir) / f"stability_{seed}.jpg")
            Path(local_path).write_bytes(img_bytes)
            data: Dict[str, Any] = {
                "local_path": local_path, "source_url": _ENDPOINT,
                "provider_source_id": seed,
                "width": width, "height": height,
                "file_size_bytes": len(img_bytes),
                "provider": self.provider_name,
                "license": "generated", "is_ai_generated": True, "prompt": prompt,
            }
            logger.info("stability_image_generated", prompt=prompt[:60], seed=seed)
            return ProviderResult(success=True, data=data,
                                  provider_used=self.provider_name,
                                  metadata={"prompt": prompt})
        except Exception as exc:
            return ProviderResult.failure(self.provider_name, f"Stability error: {exc}")

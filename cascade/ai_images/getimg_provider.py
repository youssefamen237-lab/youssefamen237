"""
cascade/ai_images/getimg_provider.py
Required GitHub Secrets: GETIMG_API_KEY (or GETIMG_AI)
"""
from __future__ import annotations
import base64, os
from pathlib import Path
from typing import Any, Dict, Optional
import requests, structlog
from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)
_SDXL_URL = "https://api.getimg.ai/v1/stable-diffusion-xl/text-to-image"
_FLUX_URL  = "https://api.getimg.ai/v1/flux-schnell/text-to-image"
_NEG = "text, watermark, logo, cartoon, anime, illustration, drawing, blurry, low quality, nsfw"


class GetImgProvider(BaseProvider):
    provider_name   = "getimg"
    is_free_tier    = False
    cascade_category= "ai_images"

    def is_available(self) -> bool:
        return self.env_present("GETIMG_API_KEY") or self.env_present("GETIMG_AI")

    def execute(self, **kwargs: Any) -> ProviderResult:
        prompt:       str = kwargs.get("prompt", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_ai_images")
        width:        int = int(kwargs.get("width", 1024))
        height:       int = int(kwargs.get("height", 1024))

        if not prompt:
            return ProviderResult.failure(self.provider_name, "Empty prompt.")

        api_key = os.getenv("GETIMG_API_KEY") or os.getenv("GETIMG_AI", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        enhanced_prompt = (
            f"{prompt}, ultra-realistic wildlife photography, 8k resolution, "
            "professional nature documentary, sharp focus, natural lighting"
        )

        for url, body in [
            (_SDXL_URL, {"prompt": enhanced_prompt, "negative_prompt": _NEG,
                          "width": width, "height": height, "steps": 30,
                          "guidance": 7.5, "output_format": "jpeg"}),
            (_FLUX_URL, {"prompt": enhanced_prompt,
                          "width": width, "height": height,
                          "steps": 4, "output_format": "jpeg"}),
        ]:
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=90)
                if resp.status_code == 429:
                    continue
                if resp.status_code in (401, 403):
                    return ProviderResult.failure(self.provider_name, "GetImg auth failed.")
                resp.raise_for_status()
                img_b64: str = resp.json().get("image", "")
                if not img_b64:
                    continue
                img_bytes = base64.b64decode(img_b64)
                Path(download_dir).mkdir(parents=True, exist_ok=True)
                seed = str(resp.json().get("seed", "0"))
                filename = f"getimg_{seed}.jpg"
                local_path = str(Path(download_dir) / filename)
                Path(local_path).write_bytes(img_bytes)
                data: Dict[str, Any] = {
                    "local_path": local_path, "source_url": url,
                    "provider_source_id": seed,
                    "width": width, "height": height,
                    "file_size_bytes": len(img_bytes),
                    "provider": self.provider_name,
                    "license": "generated", "is_ai_generated": True,
                    "prompt": prompt,
                }
                logger.info("getimg_image_generated", prompt=prompt[:60], seed=seed)
                return ProviderResult(success=True, data=data,
                                      provider_used=self.provider_name,
                                      metadata={"prompt": prompt})
            except Exception as exc:
                logger.warning("getimg_attempt_failed", url=url, error=str(exc))
                continue

        return ProviderResult.failure(self.provider_name, "GetImg all endpoints failed.")

"""
cascade/ai_images/ai_horde_provider.py
Required GitHub Secret: AI_HORDE  (or uses anonymous key "0000000000")
"""
from __future__ import annotations
import base64, os, time
from pathlib import Path
from typing import Any, Dict, Optional
import requests, structlog
from cascade.base_provider import BaseProvider, ProviderResult

logger = structlog.get_logger(__name__)
_BASE        = "https://stablehorde.net/api/v2"
_ANON_KEY    = "0000000000"
_MAX_WAIT_S  = 180
_POLL_S      = 8
_NEG = "text, watermark, cartoon, anime, blurry, low quality, nsfw, logo"


class AIHordeProvider(BaseProvider):
    provider_name    = "ai_horde"
    is_free_tier     = True
    cascade_category = "ai_images"

    def is_available(self) -> bool:
        # Always available — uses anonymous key if secret absent
        try:
            import requests as _r  # noqa
            return True
        except ImportError:
            return False

    def execute(self, **kwargs: Any) -> ProviderResult:
        prompt:       str = kwargs.get("prompt", "").strip()
        download_dir: str = kwargs.get("download_dir", "/tmp/yta_ai_images")
        width:        int = int(kwargs.get("width", 512))
        height:       int = int(kwargs.get("height", 512))

        if not prompt:
            return ProviderResult.failure(self.provider_name, "Empty prompt.")

        # AI Horde only supports multiples of 64 up to 1024
        width  = max(64, min(1024, (width  // 64) * 64))
        height = max(64, min(1024, (height // 64) * 64))

        api_key = os.getenv("AI_HORDE", _ANON_KEY)
        headers = {"apikey": api_key, "Content-Type": "application/json"}
        enhanced = (
            f"{prompt}, ultra-realistic, wildlife photography, 8k, "
            "professional nature documentary"
        )
        payload = {
            "prompt": f"{enhanced} ### {_NEG}",
            "params": {
                "sampler_name": "k_euler_a",
                "cfg_scale": 7.5,
                "steps": 25,
                "width": width,
                "height": height,
                "n": 1,
            },
            "models": ["Realistic Vision"],
            "r2": False,
        }
        try:
            resp = requests.post(f"{_BASE}/generate/async",
                                 headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            job_id: str = resp.json().get("id", "")
            if not job_id:
                return ProviderResult.failure(self.provider_name, "AI Horde returned no job ID.")
        except Exception as exc:
            return ProviderResult.failure(self.provider_name, f"AI Horde submit failed: {exc}")

        # Poll until done
        deadline = time.time() + _MAX_WAIT_S
        while time.time() < deadline:
            time.sleep(_POLL_S)
            try:
                chk = requests.get(f"{_BASE}/generate/check/{job_id}",
                                   headers=headers, timeout=15)
                chk.raise_for_status()
                status = chk.json()
                if status.get("faulted"):
                    return ProviderResult.failure(self.provider_name, "AI Horde job faulted.")
                if status.get("done"):
                    break
            except Exception:
                continue
        else:
            return ProviderResult.failure(
                self.provider_name, f"AI Horde timed out after {_MAX_WAIT_S}s.")

        # Fetch result
        try:
            final = requests.get(f"{_BASE}/generate/status/{job_id}",
                                 headers=headers, timeout=20)
            final.raise_for_status()
            generations = final.json().get("generations", [])
            if not generations:
                return ProviderResult.failure(self.provider_name, "AI Horde: no generations.")
            gen = generations[0]
            img_b64: str = gen.get("img", "")
            if not img_b64:
                return ProviderResult.failure(self.provider_name, "AI Horde: empty image data.")
            img_bytes = base64.b64decode(img_b64)
        except Exception as exc:
            return ProviderResult.failure(self.provider_name, f"AI Horde fetch failed: {exc}")

        Path(download_dir).mkdir(parents=True, exist_ok=True)
        local_path = str(Path(download_dir) / f"horde_{job_id[:16]}.jpg")
        Path(local_path).write_bytes(img_bytes)

        data: Dict[str, Any] = {
            "local_path": local_path, "source_url": _BASE,
            "provider_source_id": job_id,
            "width": width, "height": height,
            "file_size_bytes": len(img_bytes),
            "provider": self.provider_name,
            "license": "generated", "is_ai_generated": True, "prompt": prompt,
        }
        logger.info("ai_horde_image_generated", job_id=job_id[:16], prompt=prompt[:60])
        return ProviderResult(success=True, data=data,
                              provider_used=self.provider_name,
                              metadata={"job_id": job_id})

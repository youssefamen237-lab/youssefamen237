from pathlib import Path
import random

import requests
from PIL import Image, ImageFilter

from core.config import CONFIG
from utils.retry import with_retry


class ImageEngine:
    def __init__(self) -> None:
        self.bg_dir = CONFIG.assets_dir / "backgrounds"
        self.bg_dir.mkdir(parents=True, exist_ok=True)

    def _download(self, url: str, headers: dict | None = None) -> bytes:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.content

    def fetch_background(self) -> Path:
        local = list(self.bg_dir.glob("*.jpg")) + list(self.bg_dir.glob("*.png"))
        if local:
            selected = random.choice(local)
            return self._blur(selected)

        def from_unsplash() -> Path:
            if not CONFIG.unsplash_access_key:
                raise RuntimeError("No unsplash key")
            r = requests.get(
                "https://api.unsplash.com/photos/random?orientation=portrait&query=abstract",
                headers={"Authorization": f"Client-ID {CONFIG.unsplash_access_key}"},
                timeout=30,
            )
            r.raise_for_status()
            img_url = r.json()["urls"]["regular"]
            content = self._download(img_url)
            p = self.bg_dir / "unsplash.jpg"
            p.write_bytes(content)
            return self._blur(p)

        def generated() -> Path:
            p = self.bg_dir / "generated.jpg"
            img = Image.new("RGB", (1080, 1920), color=(20, 20, 35))
            img.save(p)
            return self._blur(p)

        return with_retry(lambda: from_unsplash(), retries=1, fallback=generated)

    def _blur(self, img_path: Path) -> Path:
        out = CONFIG.output_dir / f"bg_{img_path.stem}.jpg"
        Image.open(img_path).convert("RGB").resize((1080, 1920)).filter(ImageFilter.GaussianBlur(5)).save(out)
        return out

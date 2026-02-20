from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from core.config import CONFIG


class ThumbnailEngine:
    def create(self, background: Path, title: str, mode: str) -> Path:
        out = CONFIG.output_dir / f"thumbnail_{mode}.jpg"
        img = Image.open(background).convert("RGB").resize((1280, 720))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        draw.rectangle((20, 470, 1260, 700), fill=(0, 0, 0, 180))
        draw.text((50, 520), title[:85], font=font, fill=(255, 255, 255))
        img.save(out, quality=92)
        return out

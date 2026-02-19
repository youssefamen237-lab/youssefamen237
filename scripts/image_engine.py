import random
import logging
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw, ImageFont

from .config import Config

logger = logging.getLogger("image_engine")
handler = logging.FileHandler(Config.LOG_DIR / "image_engine.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class ImageEngine:
    def __init__(self):
        self.bg_dir = Config.BACKGROUND_DIR
        self.font_path = Config.FONT_PATH
        self.thumbnail_dir = Config.THUMBNAIL_DIR

    def _list_backgrounds(self):
        files = [p for p in self.bg_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
        return files

    def get_random_background(self) -> Path:
        files = self._list_backgrounds()
        if not files:
            raise FileNotFoundError("No background images found in assets/backgrounds/")
        selected = random.choice(files)
        logger.info(f"Selected background {selected.name}")
        return selected

    def get_blurred_background(self) -> Path:
        src = self.get_random_background()
        out_path = Path("temp") / f"blurred_{src.stem}_{random.randint(0,9999)}.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src).convert("RGB")
        blurred = img.filter(ImageFilter.GaussianBlur(radius=12))
        blurred.save(out_path, quality=85)
        logger.info(f"Blurred background saved to {out_path}")
        return out_path

    def generate_thumbnail(self, text: str) -> Path:
        """
        Create a thumbnail (1280x720) with blurred background and centered text.
        """
        bg_path = self.get_random_background()
        img = Image.open(bg_path).convert("RGB")
        img = img.resize((1280, 720), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=8))

        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(str(self.font_path), size=80)
        except Exception:
            logger.warning("Failed to load custom font, using default.")
            font = ImageFont.load_default()

        # Text wrap to fit width
        max_width = 1100
        lines = []
        words = text.split()
        line = ""
        for w in words:
            test_line = f"{line} {w}".strip()
            w_size = draw.textsize(test_line, font=font)[0]
            if w_size <= max_width:
                line = test_line
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)

        y_start = (720 - (len(lines) * font.getsize('Ay')[1])) // 2
        for i, line in enumerate(lines):
            w, h = draw.textsize(line, font=font)
            x = (1280 - w) // 2
            y = y_start + i * h
            draw.text((x, y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")

        out_path = self.thumbnail_dir / f"thumb_{random.randint(0,999999)}.jpg"
        img.save(out_path, quality=90)
        logger.info(f"Thumbnail generated at {out_path}")
        return out_path

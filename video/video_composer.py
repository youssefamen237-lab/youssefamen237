"""
video/video_composer.py – Quizzaro Video Composer
==================================================
Top-level orchestrator for Short production. Called by main.py.

Pipeline:
  1.  Pick template via TemplateEngine
  2.  Fetch background frames via BackgroundManager
  3.  Synthesise voiceovers + humanise via AudioEngine
  4.  Fetch BGM slice via MusicEngine
  5.  Mix final audio track via AudioEngine.mix_final_audio()
  6.  Render all frames via video_renderer._render_frame()
  7.  Assemble MP4 via FFmpeg
  8.  Return final .mp4 path

Also writes the local video path back to data/publish_log.json
so the LongVideoEngine can find it for weekly compilations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from pydub import AudioSegment

from core.content_engine import QuestionObject
from video.template_engine import TemplateEngine
from video.background_manager import BackgroundManager
from video.music_engine import MusicEngine
from video.watermark import WatermarkEngine
from video.timer_renderer import draw_timer
from video.text_animator import get_popup_frame, wrap_text, auto_font_size
from audio.audio_engine import AudioEngine

RENDER_DIR = Path("data/render_tmp")
RENDER_DIR.mkdir(parents=True, exist_ok=True)
PUBLISH_LOG_PATH = Path("data/publish_log.json")

# Video spec
WIDTH = 1080
HEIGHT = 1920
FPS = 30
SAFE_LEFT = int(WIDTH * 0.08)
SAFE_RIGHT = int(WIDTH * 0.92)
SAFE_TOP = int(HEIGHT * 0.12)
SAFE_BOTTOM = int(HEIGHT * 0.88)
SAFE_W = SAFE_RIGHT - SAFE_LEFT

# Timeline constants
QUESTION_SEC = 4.0
TIMER_SEC = 5.0
ANSWER_SEC = 5.0

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
PHOSPHOR = (57, 255, 20)
YELLOW = (255, 220, 50)
CHUNK_BYTES = 8 * 1024 * 1024


class VideoComposer:

    def __init__(
        self,
        tts_engine,
        voice_humanizer,
        sfx_manager,
        background_manager: BackgroundManager,
        music_engine: MusicEngine,
        template_engine: TemplateEngine,
        watermark_engine: WatermarkEngine,
    ) -> None:
        self._tts = tts_engine
        self._humanizer = voice_humanizer
        self._sfx = sfx_manager
        self._bg = background_manager
        self._music = music_engine
        self._templates = template_engine
        self._wm = watermark_engine

    def render_short(self, question: QuestionObject) -> str:
        """
        Full pipeline. Returns absolute path to the output .mp4 file.
        """
        import random
        job_id = uuid.uuid4().hex[:12]
        job_dir = RENDER_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Duration jitter (human-touch fingerprint) ───────────────────
        jitter = random.uniform(-1.0, 1.5)
        q_sec = max(3.0, QUESTION_SEC + jitter)
        total_sec = q_sec + TIMER_SEC + ANSWER_SEC
        total_frames = int(total_sec * FPS)
        timer_start_f = int(q_sec * FPS)
        timer_end_f = timer_start_f + int(TIMER_SEC * FPS)
        answer_start_f = timer_end_f

        logger.info(f"[Composer] {job_id} | dur={total_sec:.1f}s | frames={total_frames}")

        # ── 2. Template selection ──────────────────────────────────────────
        tmpl = self._templates.pick_template()
        logger.info(f"[Composer] Template: {tmpl.name}")

        # ── 3. Background frames ───────────────────────────────────────────
        bg_frames = self._bg.get_background_frames(total_sec, job_dir)

        # ── 4. Audio synthesis ─────────────────────────────────────────────
        audio_result = self._tts_and_mix(
            question=question,
            job_dir=job_dir,
            job_id=job_id,
            q_sec=q_sec,
            total_sec=total_sec,
        )
        audio_path = audio_result["audio_path"]
        gender = audio_result["gender"]

        # ── 5. Render frames ───────────────────────────────────────────────
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(exist_ok=True)

        font_path = self._best_font_path()

        for i in range(total_frames):
            bg_idx = min(i, len(bg_frames) - 1)
            frame_bgr = bg_frames[bg_idx]
            pil_img = self._bgr_to_pil(frame_bgr)
            pil_img = self._apply_overlay(pil_img, alpha=150)

            if i < timer_start_f:
                pil_img = self._draw_question_phase(
                    pil_img, question, tmpl, i, font_path
                )
            elif i < timer_end_f:
                pil_img = self._draw_timer_phase(
                    pil_img, question, i, timer_start_f, timer_end_f, font_path
                )
            else:
                pil_img = self._draw_answer_phase(
                    pil_img, question, i, answer_start_f, font_path
                )

            pil_img = self._wm.apply(pil_img, i, total_frames)
            frame_path = frames_dir / f"frame_{i:05d}.png"
            self._pil_to_png(pil_img, str(frame_path))

        # ── 6. FFmpeg assembly ─────────────────────────────────────────────
        output_path = str(job_dir / "final_short.mp4")
        self._ffmpeg_assemble(str(frames_dir), audio_path, output_path, total_sec)
        shutil.rmtree(str(frames_dir), ignore_errors=True)

        # ── 7. Patch publish log with local path ───────────────────────────
        self._patch_log_local_path(job_id, output_path, gender)

        logger.success(f"[Composer] Done: {output_path}")
        return output_path

    # ── Phase drawers ──────────────────────────────────────────────────────

    def _draw_question_phase(self, img, question, tmpl, frame_idx, font_path):
        from PIL import Image, ImageDraw, ImageFont
        import random

        anim = get_popup_frame(frame_idx, full_font_size=72)
        q_font_size = anim.font_size
        try:
            q_font = ImageFont.truetype(font_path, q_font_size) if font_path else ImageFont.load_default()
        except Exception:
            q_font = ImageFont.load_default()

        cx = WIDTH // 2
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Template badge
        badge_font_size = 36
        try:
            bf = ImageFont.truetype(font_path, badge_font_size) if font_path else ImageFont.load_default()
        except Exception:
            bf = ImageFont.load_default()

        badge_y1, badge_y2 = SAFE_TOP + 25, SAFE_TOP + 75
        draw.rounded_rectangle([cx - 170, badge_y1, cx + 170, badge_y2],
                                radius=22, fill=(255, 200, 0, 210))
        draw.text((cx, (badge_y1 + badge_y2) // 2), tmpl.badge_label,
                  font=bf, fill=(0, 0, 0, 255), anchor="mm")

        # Question text
        lines = wrap_text(question.question_text, q_font, SAFE_W - 20)
        self._draw_multiline(draw, lines, cx, HEIGHT // 2 - 60, q_font,
                             (255, 255, 255, anim.alpha), stroke=5)

        # CTA text (appears after 15 frames)
        if frame_idx > 15:
            try:
                cta_font = ImageFont.truetype(font_path, 30) if font_path else ImageFont.load_default()
            except Exception:
                cta_font = ImageFont.load_default()
            cta_lines = wrap_text(question.cta_text, cta_font, SAFE_W - 40)
            self._draw_multiline(draw, cta_lines, cx, HEIGHT // 2 + 230, cta_font,
                                 (255, 230, 100, 190), stroke=3)

        # Template-specific options
        if tmpl.name == "multiple_choice" and frame_idx > 20 and question.wrong_answers:
            self._draw_mc_options(draw, question, font_path)

        if tmpl.name == "true_false" and frame_idx > 20:
            self._draw_tf_buttons(draw, font_path)

        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    def _draw_timer_phase(self, img, question, frame_idx, timer_start_f, timer_end_f, font_path):
        from PIL import Image, ImageDraw, ImageFont
        timer_frame = frame_idx - timer_start_f
        timer_total = timer_end_f - timer_start_f
        progress = timer_frame / timer_total

        # Dimmed question text stays visible
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            q_font = ImageFont.truetype(font_path, 56) if font_path else ImageFont.load_default()
        except Exception:
            q_font = ImageFont.load_default()
        lines = wrap_text(question.question_text, q_font, SAFE_W - 20)
        self._draw_multiline(draw, lines, WIDTH // 2, HEIGHT // 2 - 200,
                             q_font, (255, 255, 255, 160), stroke=4)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

        # Circular timer
        img = draw_timer(img, progress, center=(WIDTH // 2, HEIGHT // 2 + 100),
                         font_path=font_path)
        return img

    def _draw_answer_phase(self, img, question, frame_idx, answer_start_f, font_path):
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        reveal_f = frame_idx - answer_start_f

        # Glow layer
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        try:
            a_font_size = 76 if len(question.correct_answer) < 16 else 58
            a_font = ImageFont.truetype(font_path, a_font_size) if font_path else ImageFont.load_default()
        except Exception:
            a_font = ImageFont.load_default()

        lines = wrap_text(question.correct_answer, a_font, SAFE_W - 30)
        self._draw_multiline(gd, lines, WIDTH // 2, HEIGHT // 2 + 60,
                             a_font, PHOSPHOR + (100,), stroke=0)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=16))

        sharp = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sharp)
        self._draw_multiline(sd, lines, WIDTH // 2, HEIGHT // 2 + 60,
                             a_font, PHOSPHOR + (255,), stroke=6)

        img = Image.alpha_composite(img.convert("RGBA"), glow)
        img = Image.alpha_composite(img, sharp).convert("RGB")

        # CORRECT badge
        badge = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        try:
            bfont = ImageFont.truetype(font_path, 50) if font_path else ImageFont.load_default()
        except Exception:
            bfont = ImageFont.load_default()
        cx = WIDTH // 2
        by1, by2 = HEIGHT // 2 - 210, HEIGHT // 2 - 140
        bd.rounded_rectangle([cx - 190, by1, cx + 190, by2], radius=26,
                              fill=(57, 255, 20, 210))
        bd.text((cx, (by1 + by2) // 2), "✓  CORRECT!", font=bfont,
                fill=(0, 0, 0, 255), anchor="mm")
        img = Image.alpha_composite(img.convert("RGBA"), badge).convert("RGB")

        # Explanation (after 15 frames)
        if question.explanation and reveal_f > 15:
            try:
                ef = ImageFont.truetype(font_path, 32) if font_path else ImageFont.load_default()
            except Exception:
                ef = ImageFont.load_default()
            exp_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ed = ImageDraw.Draw(exp_overlay)
            exp_lines = wrap_text(question.explanation, ef, SAFE_W - 40)
            self._draw_multiline(ed, exp_lines, WIDTH // 2, HEIGHT // 2 + 270,
                                 ef, (200, 200, 200, 200), stroke=2)
            img = Image.alpha_composite(img.convert("RGBA"), exp_overlay).convert("RGB")

        return img

    # ── Drawing utilities ──────────────────────────────────────────────────

    @staticmethod
    def _draw_multiline(draw, lines, cx, cy, font, fill, stroke=4, spacing=12):
        from PIL import ImageDraw, Image
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        heights = [dummy.textbbox((0, 0), l, font=font)[3] - dummy.textbbox((0, 0), l, font=font)[1]
                   for l in lines]
        total_h = sum(heights) + spacing * (len(lines) - 1)
        y = cy - total_h // 2
        for i, line in enumerate(lines):
            lh = heights[i]
            if stroke > 0:
                sc = (0, 0, 0, 255) if len(fill) == 4 else BLACK
                for dx in range(-stroke, stroke + 1):
                    for dy in range(-stroke, stroke + 1):
                        if dx or dy:
                            draw.text((cx + dx, y + lh // 2 + dy), line,
                                      font=font, fill=sc, anchor="mm")
            draw.text((cx, y + lh // 2), line, font=font, fill=fill, anchor="mm")
            y += lh + spacing

    def _draw_mc_options(self, draw, question, font_path):
        from PIL import ImageFont, Image
        import random as _r
        all_opts = [question.correct_answer] + question.wrong_answers[:3]
        _r.shuffle(all_opts)
        try:
            opt_font = (ImageFont.truetype(font_path, 36)
                        if font_path else ImageFont.load_default())
        except Exception:
            opt_font = ImageFont.load_default()
        labels = ["A", "B", "C", "D"]
        start_y = HEIGHT // 2 + 130
        spacing = 88
        for i, (lbl, opt) in enumerate(zip(labels, all_opts)):
            oy = start_y + i * spacing
            draw.rounded_rectangle([SAFE_LEFT, oy - 28, SAFE_RIGHT, oy + 28],
                                    radius=14, fill=(255, 255, 255, 38))
            draw.text((SAFE_LEFT + 18, oy), f"{lbl}.  {opt}",
                      font=opt_font, fill=(255, 255, 255, 230), anchor="lm")

    def _draw_tf_buttons(self, draw, font_path):
        from PIL import ImageFont
        cx = WIDTH // 2
        try:
            tf_font = ImageFont.truetype(font_path, 50) if font_path else ImageFont.load_default()
        except Exception:
            tf_font = ImageFont.load_default()
        y1, y2 = HEIGHT // 2 + 190, HEIGHT // 2 + 280
        draw.rounded_rectangle([SAFE_LEFT, y1, cx - 18, y2], radius=20,
                                fill=(0, 200, 80, 200))
        draw.text(((SAFE_LEFT + cx - 18) // 2, (y1 + y2) // 2), "TRUE",
                  font=tf_font, fill=(255, 255, 255, 255), anchor="mm")
        draw.rounded_rectangle([cx + 18, y1, SAFE_RIGHT, y2], radius=20,
                                fill=(220, 50, 50, 200))
        draw.text(((cx + 18 + SAFE_RIGHT) // 2, (y1 + y2) // 2), "FALSE",
                  font=tf_font, fill=(255, 255, 255, 255), anchor="mm")

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_overlay(img, alpha: int = 150):
        from PIL import Image
        ov = Image.new("RGBA", img.size, (0, 0, 0, alpha))
        return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    @staticmethod
    def _bgr_to_pil(frame: np.ndarray):
        import cv2
        from PIL import Image
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    @staticmethod
    def _pil_to_png(img, path: str) -> None:
        import cv2
        import numpy as np
        from PIL import Image
        arr = np.array(img.convert("RGB"))
        cv2.imwrite(path, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))

    @staticmethod
    def _best_font_path() -> str | None:
        for p in [
            "data/fonts/montserrat_extrabold.ttf",
            "data/fonts/montserrat_bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            if Path(p).exists():
                return p
        return None

    # ── Audio pipeline ─────────────────────────────────────────────────────

    def _tts_and_mix(self, question, job_dir, job_id, q_sec, total_sec) -> dict:
        # Synthesise question + CTA voiceovers
        audio_result = self._tts.render_question_audio(
            question_text=question.question_text,
            cta_text=question.cta_text,
            job_id=job_id,
        )

        # BGM
        bgm_path = str(job_dir / "bgm.wav")
        bgm = self._music.get_bgm(int(total_sec * 1000), bgm_path)
        if bgm is None:
            bgm = AudioSegment.silent(duration=int(total_sec * 1000))

        mixed = self._tts.mix_final_audio(
            question_vo_path=audio_result["question_vo"],
            cta_vo_path=audio_result["cta_vo"],
            tick_tock=self._sfx.get_tick_tock(duration_ms=int(TIMER_SEC * 1000)),
            answer_sfx=self._sfx.get_answer_sfx(),
            background_music=bgm,
            timer_start_ms=int(q_sec * 1000),
            answer_reveal_ms=int((q_sec + TIMER_SEC) * 1000),
            total_duration_ms=int(total_sec * 1000),
        )
        audio_path = str(job_dir / "final_audio.wav")
        mixed.export(audio_path, format="wav")

        return {"audio_path": audio_path, "gender": audio_result.get("gender", "mixed")}

    @staticmethod
    def _ffmpeg_assemble(frames_dir: str, audio_path: str, output_path: str, duration: float) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            "-t", f"{duration:.2f}",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"[Composer] FFmpeg failed:\n{result.stderr[-800:]}")

    @staticmethod
    def _patch_log_local_path(job_id: str, video_path: str, gender: str) -> None:
        """Append local_video_path + gender to the most recent publish_log entry."""
        if not PUBLISH_LOG_PATH.exists():
            return
        try:
            with open(PUBLISH_LOG_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)
            if entries:
                entries[-1]["local_video_path"] = video_path
                entries[-1]["gender"] = gender
                with open(PUBLISH_LOG_PATH, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"[Composer] Could not patch log: {exc}")

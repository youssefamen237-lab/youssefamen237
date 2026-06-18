"""
engines/image_processor.py
Converts static images to animated MP4 clips using the Ken Burns effect.
All operations use direct FFmpeg subprocess calls for reliability.
"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
from typing import Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)


class ImageProcessor:

    # ── Public API ─────────────────────────────────────────────────────────────

    def image_to_video_clip(
        self,
        image_path: str,
        duration:   float,
        output_path: str,
        width:  int = 1920,
        height: int = 1080,
        fps:    int = 25,
    ) -> str:
        """
        Convert a static image to an animated MP4 using a slow Ken Burns zoom.
        Output has no audio stream.  Raises RuntimeError on FFmpeg failure.
        """
        duration = max(0.5, float(duration))
        frames   = max(1, int(duration * fps))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Scale to 2× target first so zoompan has room to zoom without pixelation
        sw, sh = width * 2, height * 2
        vf = (
            f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={sw}:{sh},"
            f"zoompan="
            f"z='min(zoom+0.0008,1.06)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},"
            f"scale={width}:{height}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        self._run(cmd, timeout=180, context="image_to_video_clip")
        logger.info("image_animated", path=output_path,
                    duration=duration, resolution=f"{width}x{height}")
        return output_path

    def resize_and_crop(
        self,
        image_path:  str,
        output_path: str,
        width:  int,
        height: int,
    ) -> str:
        """Scale-and-center-crop an image to exact target dimensions."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
        cmd = [
            "ffmpeg", "-y", "-i", image_path,
            "-vf", vf, "-frames:v", "1", output_path,
        ]
        self._run(cmd, timeout=30, context="resize_and_crop")
        return output_path

    def preprocess_video_clip(
        self,
        clip_path:   str,
        duration:    float,
        output_path: str,
        width:  int,
        height: int,
        fps:    int = 30,
    ) -> str:
        """
        Scale, crop, and trim (or loop) a video clip to exact duration.
        Strips audio — the assembler handles audio separately.
        """
        duration = max(0.1, float(duration))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"fps={fps}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",   # loop indefinitely so short clips fill the slot
            "-i", clip_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        self._run(cmd, timeout=120, context="preprocess_video_clip")
        return output_path

    def generate_black_clip(
        self,
        duration:    float,
        output_path: str,
        width:  int,
        height: int,
        fps:    int = 30,
    ) -> str:
        """Generate a plain black MP4 clip — used when all media sources fail."""
        duration = max(0.1, float(duration))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:r={fps}",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
        ]
        self._run(cmd, timeout=30, context="generate_black_clip")
        return output_path

    def get_media_info(self, path: str) -> dict:
        """Return {width, height, duration, has_video, has_audio} for any media file."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            data = json.loads(result.stdout)
        except Exception:
            return {"width": 0, "height": 0, "duration": 0.0,
                    "has_video": False, "has_audio": False}

        info = {"width": 0, "height": 0, "duration": 0.0,
                "has_video": False, "has_audio": False}
        fmt_dur = float(data.get("format", {}).get("duration", 0) or 0)
        info["duration"] = fmt_dur

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type", "")
            if codec_type == "video" and not info["has_video"]:
                info["has_video"] = True
                info["width"]  = int(stream.get("width", 0))
                info["height"] = int(stream.get("height", 0))
                dur = float(stream.get("duration", 0) or 0)
                if dur > 0:
                    info["duration"] = dur
            elif codec_type == "audio":
                info["has_audio"] = True

        return info

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _run(cmd: list, timeout: int, context: str) -> None:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[-600:]
            raise RuntimeError(f"{context} failed (rc={result.returncode}): {stderr}")


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[ImageProcessor] = None

def get_image_processor() -> ImageProcessor:
    global _instance
    if _instance is None:
        _instance = ImageProcessor()
    return _instance

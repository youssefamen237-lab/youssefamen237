"""
engines/subtitle_engine.py

Converts TTS alignment data into SRT subtitle files.
Used by VideoAssembler before final FFmpeg encoding.
"""
from __future__ import annotations
import os, re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)

_WORDS_PER_LINE  = 3    # group N words per subtitle line
_MIN_LINE_DUR    = 0.5  # minimum subtitle line duration in seconds
_SILENCE_GAP     = 0.08 # seconds to subtract from line end for clean reading


class SubtitleEngine:

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_srt(
        self,
        alignment: Optional[Dict],
        output_path: str,
        full_text: Optional[str] = None,
        audio_duration: Optional[float] = None,
        words_per_line: int = _WORDS_PER_LINE,
    ) -> str:
        """
        Generate an SRT file from alignment data and write it to output_path.
        Returns output_path.

        Falls back to estimated timing when alignment is unavailable,
        using full_text + audio_duration.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if alignment and alignment.get("characters"):
            lines = self._from_character_alignment(alignment, words_per_line)
        elif alignment and alignment.get("type") == "word":
            lines = self._from_word_alignment(alignment, words_per_line)
        elif full_text and audio_duration and audio_duration > 0:
            lines = self._from_estimated_timing(full_text, audio_duration, words_per_line)
        else:
            # Nothing to work with — write empty SRT
            Path(output_path).write_text("", encoding="utf-8")
            return output_path

        srt_content = self._lines_to_srt(lines)
        Path(output_path).write_text(srt_content, encoding="utf-8")
        logger.info("subtitle_srt_generated",
                    path=output_path, line_count=len(lines))
        return output_path

    # ── Character-level alignment (ElevenLabs) ────────────────────────────────

    def _from_character_alignment(
        self, alignment: Dict, words_per_line: int
    ) -> List[Tuple[float, float, str]]:
        chars:   List[str]   = alignment["characters"]
        starts:  List[float] = alignment["start_times"]
        ends:    List[float] = alignment["end_times"]

        # Group characters into words
        words, w_starts, w_ends = self._chars_to_words(chars, starts, ends)
        return self._words_to_lines(words, w_starts, w_ends, words_per_line)

    @staticmethod
    def _chars_to_words(
        chars: List[str], starts: List[float], ends: List[float]
    ) -> Tuple[List[str], List[float], List[float]]:
        words:    List[str]   = []
        w_starts: List[float] = []
        w_ends:   List[float] = []

        cur_word  = ""
        cur_start = 0.0
        cur_end   = 0.0

        for ch, s, e in zip(chars, starts, ends):
            if ch in (" ", "\n", "\t"):
                if cur_word:
                    words.append(cur_word)
                    w_starts.append(cur_start)
                    w_ends.append(cur_end)
                    cur_word = ""
            else:
                if not cur_word:
                    cur_start = s
                cur_word += ch
                cur_end = e

        if cur_word:
            words.append(cur_word)
            w_starts.append(cur_start)
            w_ends.append(cur_end)

        return words, w_starts, w_ends

    # ── Word-level alignment (edge-tts) ───────────────────────────────────────

    def _from_word_alignment(
        self, alignment: Dict, words_per_line: int
    ) -> List[Tuple[float, float, str]]:
        words:   List[str]   = alignment["characters"]   # "characters" = words here
        starts:  List[float] = alignment["start_times"]
        ends:    List[float] = alignment["end_times"]
        return self._words_to_lines(words, starts, ends, words_per_line)

    # ── Estimated timing fallback ──────────────────────────────────────────────

    def _from_estimated_timing(
        self, full_text: str, audio_duration: float, words_per_line: int
    ) -> List[Tuple[float, float, str]]:
        raw_words = re.split(r"\s+", full_text.strip())
        words = [w for w in raw_words if w]
        if not words:
            return []

        seconds_per_word = audio_duration / max(len(words), 1)
        w_starts = [i * seconds_per_word for i in range(len(words))]
        w_ends   = [(i + 1) * seconds_per_word for i in range(len(words))]
        return self._words_to_lines(words, w_starts, w_ends, words_per_line)

    # ── Word grouping ─────────────────────────────────────────────────────────

    @staticmethod
    def _words_to_lines(
        words: List[str],
        starts: List[float],
        ends: List[float],
        words_per_line: int,
    ) -> List[Tuple[float, float, str]]:
        lines: List[Tuple[float, float, str]] = []
        i = 0
        while i < len(words):
            group = words[i : i + words_per_line]
            g_start = starts[i]
            g_end   = ends[min(i + words_per_line - 1, len(ends) - 1)]
            # Ensure minimum duration
            if g_end - g_start < _MIN_LINE_DUR:
                g_end = g_start + _MIN_LINE_DUR
            g_end = max(g_start + 0.1, g_end - _SILENCE_GAP)
            text = " ".join(w.strip(".,!?;:\"'") for w in group if w)
            if text:
                lines.append((round(g_start, 3), round(g_end, 3), text))
            i += words_per_line
        return lines

    # ── SRT formatting ────────────────────────────────────────────────────────

    @staticmethod
    def _lines_to_srt(lines: List[Tuple[float, float, str]]) -> str:
        parts = []
        for idx, (start, end, text) in enumerate(lines, start=1):
            parts.append(
                f"{idx}\n"
                f"{_sec_to_srt(start)} --> {_sec_to_srt(end)}\n"
                f"{text}\n"
            )
        return "\n".join(parts)


def _sec_to_srt(sec: float) -> str:
    """Convert float seconds to SRT timestamp: HH:MM:SS,mmm"""
    sec = max(0.0, sec)
    h   = int(sec // 3600)
    m   = int((sec % 3600) // 60)
    s   = int(sec % 60)
    ms  = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── Singleton ──────────────────────────────────────────────────────────────────

_sub_instance: Optional[SubtitleEngine] = None


def get_subtitle_engine() -> SubtitleEngine:
    global _sub_instance
    if _sub_instance is None:
        _sub_instance = SubtitleEngine()
    return _sub_instance

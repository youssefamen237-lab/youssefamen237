from __future__ import annotations


def ffmpeg_escape(text: str) -> str:
    # FFmpeg drawtext escaping: backslash, colon, apostrophe, percent, brackets
    t = text
    t = t.replace("\\", "\\\\")
    t = t.replace(":", "\\:")
    t = t.replace("'", "\\'")
    t = t.replace("%", "\\%")
    t = t.replace("[", "\\[")
    t = t.replace("]", "\\]")
    # newlines are supported as \n in drawtext
    t = t.replace("\n", "\\n")
    return t

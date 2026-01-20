from __future__ import annotations

import hashlib


def sha256_hex(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8", errors="ignore"))
    return h.hexdigest()

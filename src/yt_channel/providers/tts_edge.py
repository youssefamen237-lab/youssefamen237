from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .base import ProviderError, TTSProviderBase, TTSResult

logger = logging.getLogger(__name__)


class EdgeTTSProvider(TTSProviderBase):
    key = "tts_edge"

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False

    def synthesize(self, text: str, voice: str, out_path: Path) -> TTSResult:
        try:
            import edge_tts
        except Exception as e:
            raise ProviderError(f"edge-tts not available: {e}")

        out_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(text=text, voice=voice)
            await communicate.save(str(out_path))

        try:
            asyncio.run(_run())
        except RuntimeError:
            # If we're already in an event loop (rare in GitHub Actions), create a new loop.
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()
        except Exception as e:
            raise ProviderError(f"edge-tts synthesis failed: {e}")

        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise ProviderError("edge-tts produced empty audio")

        return TTSResult(path=out_path, provider_key=self.key, voice=voice)

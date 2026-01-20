from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import List, Optional

from ..config.settings import Settings
from ..state.db import StateDB
from .base import (
    AudioPick,
    AssetPick,
    ProviderError,
    TTSResult,
    TTSProviderBase,
    BackgroundProviderBase,
    MusicProviderBase,
)
from .background_generated import GeneratedBackgroundProvider
from .background_local import LocalBackgroundProvider
from .background_pexels import PexelsBackgroundProvider
from .music_freesound import FreesoundMusicProvider
from .music_generated import GeneratedMusicProvider
from .music_local import LocalMusicProvider
from .tts_edge import EdgeTTSProvider
from .tts_espeak import EspeakTTSProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    def __init__(self, *, settings: Settings, db: StateDB, rng: random.Random, **_: object) -> None:
        self.settings = settings
        self.db = db
        self.rng = rng

        # Directories
        self.user_bg_dir = settings.user_assets_dir / "backgrounds"
        self.user_music_dir = settings.user_assets_dir / "music"

        self.generated_bg_dir = settings.assets_dir / "backgrounds" / "generated"
        self.pexels_bg_dir = settings.assets_dir / "backgrounds" / "pexels"

        self.generated_music_dir = settings.assets_dir / "music" / "generated"
        self.freesound_music_dir = settings.assets_dir / "music" / "freesound"

        # Providers
        self._tts_providers: List[TTSProviderBase] = [
            EdgeTTSProvider(),
            EspeakTTSProvider(),
        ]

        self._bg_providers: List[BackgroundProviderBase] = [
            LocalBackgroundProvider(rng=rng, user_dir=self.user_bg_dir, assets_dir=settings.backgrounds_dir),
            GeneratedBackgroundProvider(rng=rng, out_dir=self.generated_bg_dir),
            PexelsBackgroundProvider(rng=rng, api_key=settings.pexels_api_key, out_dir=self.pexels_bg_dir),
        ]

        self._music_providers: List[MusicProviderBase] = [
            LocalMusicProvider(rng=rng, user_dir=self.user_music_dir, assets_dir=settings.music_dir),
            GeneratedMusicProvider(rng=rng, out_dir=self.generated_music_dir),
            FreesoundMusicProvider(rng=rng, token=settings.freesound_token, out_dir=self.freesound_music_dir),
        ]

    def _in_cooldown(self, provider_key: str) -> bool:
        h = self.db.get_provider_health(provider_key)
        if not h.cooldown_until:
            return False
        try:
            import datetime as _dt

            until = _dt.datetime.fromisoformat(h.cooldown_until)
            return _dt.datetime.now(_dt.timezone.utc) < until
        except Exception:
            return False

    def _try(self, provider_key: str, fn, *, cooldown_seconds: int = 1800):
        if self._in_cooldown(provider_key):
            raise ProviderError(f"provider in cooldown: {provider_key}")
        try:
            res = fn()
            self.db.provider_on_success(provider_key)
            return res
        except Exception as e:
            self.db.provider_on_failure(provider_key, error=str(e), cooldown_seconds=cooldown_seconds)
            raise

    def tts_question(self, *, text: str, gender: str, out_path: Path) -> TTSResult:
        return self.synthesize_tts(text=text, gender=gender, out_path=out_path)

    def synthesize_tts(self, *, text: str, gender: str, out_path: Path) -> TTSResult:
        voice = self.settings.tts_voice_female if gender.lower() == "female" else self.settings.tts_voice_male

        chain = [p for p in self._tts_providers if p.is_available()]
        if not chain:
            chain = self._tts_providers

        last_err: Optional[Exception] = None
        for provider in chain:
            provider_key = provider.key
            for attempt in range(1, 4):
                try:
                    return self._try(provider_key, lambda: provider.synthesize(text, voice, out_path))
                except Exception as e:
                    last_err = e
                    time.sleep(min(2**attempt, 8))
                    continue
        raise ProviderError(f"All TTS providers failed: {last_err}")

    def pick_background(self) -> AssetPick:
        chain: List[BackgroundProviderBase] = []
        for key in self.settings.bg_provider_chain:
            if key == "local":
                chain.append(self._bg_providers[0])
            elif key == "generated":
                chain.append(self._bg_providers[1])
            elif key == "pexels":
                chain.append(self._bg_providers[2])

        if not chain:
            chain = self._bg_providers

        last_err: Optional[Exception] = None
        for provider in chain:
            if not provider.is_available():
                continue
            provider_key = provider.key
            for attempt in range(1, 3):
                try:
                    res = self._try(provider_key, lambda: provider.pick())
                    if res is None:
                        raise ProviderError("no asset")
                    return res
                except Exception as e:
                    last_err = e
                    time.sleep(min(2**attempt, 6))
                    continue
        raise ProviderError(f"All background providers failed: {last_err}")

    def pick_music(self, *, duration_seconds: float = 60.0) -> AudioPick:
        chain: List[MusicProviderBase] = []
        for key in self.settings.music_provider_chain:
            if key == "local":
                chain.append(self._music_providers[0])
            elif key == "generated":
                chain.append(self._music_providers[1])
            elif key == "freesound":
                chain.append(self._music_providers[2])

        if not chain:
            chain = self._music_providers

        last_err: Optional[Exception] = None
        for provider in chain:
            if not provider.is_available():
                continue
            provider_key = provider.key
            for attempt in range(1, 3):
                try:
                    res = self._try(provider_key, lambda: provider.pick(duration_seconds=duration_seconds))
                    if res is None:
                        raise ProviderError("no music")
                    return res
                except Exception as e:
                    last_err = e
                    time.sleep(min(2**attempt, 6))
                    continue

        gen = GeneratedMusicProvider(rng=self.rng, out_dir=self.generated_music_dir)
        res = gen.pick(duration_seconds=duration_seconds)
        if res:
            return res
        raise ProviderError(f"All music providers failed: {last_err}")

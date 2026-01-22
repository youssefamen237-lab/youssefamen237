\
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from autoyt.utils.fs import read_json, write_json


@dataclass
class ConfigBundle:
    base: Dict[str, Any]
    state: Dict[str, Any]

    @property
    def target_country(self) -> str:
        return self.state.get("target_country") or self.base["channel"]["default_country"]

    @property
    def target_timezone(self) -> str:
        return self.state.get("target_timezone") or self.base["channel"]["default_timezone"]

    def template_weight(self, template_id: str) -> float:
        return float(self.state.get("template_weights", {}).get(template_id, 1.0))

    def voice_weight(self, voice_id: str) -> float:
        return float(self.state.get("voice_weights", {}).get(voice_id, 1.0))


class ConfigManager:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.base_path = repo_root / "config" / "base_config.json"
        self.state_path = repo_root / "config" / "state.json"

    def load(self) -> ConfigBundle:
        base = read_json(self.base_path)
        state = read_json(self.state_path)
        # Fill missing keys in state from base defaults
        state.setdefault("target_country", base["channel"]["default_country"])
        state.setdefault("target_timezone", base["channel"]["default_timezone"])
        state.setdefault("schedule_hours_local", base["scheduling"]["default_post_hours_local"])
        state.setdefault("template_weights", {t["id"]: t.get("weight", 1.0) for t in base.get("templates", [])})
        state.setdefault("voice_weights", {v["id"]: v.get("weight", 1.0) for v in base.get("voices", [])})
        state.setdefault("topic_weights", base.get("topics", {}).get("weights", {}))
        state.setdefault("recent_cta_ids", [])
        state.setdefault("recent_background_ids", [])
        state.setdefault("recent_music_ids", [])
        return ConfigBundle(base=base, state=state)

    def save_state(self, state: Dict[str, Any]) -> None:
        write_json(self.state_path, state)

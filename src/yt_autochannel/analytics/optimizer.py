from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..db.sqlite_db import DB


@dataclass
class ArmStats:
    n: int = 0
    total_reward: float = 0.0

    def mean(self) -> float:
        return 0.0 if self.n == 0 else self.total_reward / self.n


def _load_stats(db: DB, state_key: str) -> Dict[str, ArmStats]:
    raw = db.get_state(state_key)
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        out: Dict[str, ArmStats] = {}
        for k, v in obj.items():
            out[str(k)] = ArmStats(n=int(v.get("n", 0)), total_reward=float(v.get("total_reward", 0.0)))
        return out
    except Exception:
        return {}


def _save_stats(db: DB, state_key: str, stats: Dict[str, ArmStats]) -> None:
    obj = {k: {"n": v.n, "total_reward": v.total_reward} for k, v in stats.items()}
    db.set_state(state_key, json.dumps(obj, sort_keys=True))


def choose_arm(db: DB, dim: str, arms: List[str], epsilon: float = 0.15) -> str:
    """Epsilon-greedy with slight randomization; persisted per-dimension."""
    if not arms:
        raise ValueError("arms is empty")
    key = f"bandit::{dim}"
    stats = _load_stats(db, key)

    # exploration
    if random.random() < epsilon:
        return random.choice(arms)

    # exploitation: pick best mean, tie-break random
    best = None
    best_score = None
    for a in arms:
        s = stats.get(a, ArmStats())
        m = s.mean()
        # add tiny noise to reduce deterministic fingerprints
        m2 = m + random.uniform(-1e-4, 1e-4)
        if best is None or m2 > best_score:
            best = a
            best_score = m2
    return best or random.choice(arms)


def update_arm(db: DB, dim: str, arm: str, reward: float) -> None:
    key = f"bandit::{dim}"
    stats = _load_stats(db, key)
    s = stats.get(arm, ArmStats())
    s.n += 1
    s.total_reward += float(reward)
    stats[arm] = s
    _save_stats(db, key, stats)


class Bandit:
    def __init__(self, db: DB):
        self.db = db

    def choose(self, dim: str, arms: list[str], epsilon: float = 0.15) -> str:
        return choose_arm(self.db, dim, arms, epsilon=epsilon)

    def update(self, dim: str, arm: str, reward: float) -> None:
        update_arm(self.db, dim, arm, reward)

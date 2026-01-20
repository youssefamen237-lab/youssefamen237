from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from ..state.db import StateDB


@dataclass(frozen=True)
class ArmScore:
    arm_value: str
    sample: float
    alpha: float
    beta: float


class BetaBandit:
    def __init__(self, *, rng: random.Random, db: StateDB) -> None:
        self.rng = rng
        self.db = db

    def sample_arm(self, *, arm_type: str, arm_value: str) -> ArmScore:
        alpha, beta = self.db.get_arm(arm_type, arm_value)
        s = self.rng.betavariate(alpha, beta)
        return ArmScore(arm_value=arm_value, sample=s, alpha=alpha, beta=beta)

    def choose(self, *, arm_type: str, choices: List[str]) -> str:
        best = None
        for c in choices:
            score = self.sample_arm(arm_type=arm_type, arm_value=c)
            if best is None or score.sample > best.sample:
                best = score
        return best.arm_value if best else choices[0]

    def update(self, *, arm_type: str, arm_value: str, success: bool) -> None:
        alpha, beta = self.db.get_arm(arm_type, arm_value)
        if success:
            alpha += 1.0
        else:
            beta += 1.0
        self.db.update_arm(arm_type, arm_value, alpha=alpha, beta=beta)

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ytquiz.utils import clamp


@dataclass
class ArmStats:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, x: float) -> None:
        x = float(clamp(x, 0.0, 1.0))
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def variance(self) -> float:
        if self.n < 2:
            return 0.10
        return max(1e-6, self.m2 / (self.n - 1))

    def sample(self, rng: random.Random, explore: float = 0.15) -> float:
        v = self.variance()
        sd = math.sqrt(v / max(1, self.n)) + explore
        return float(rng.gauss(self.mean, sd))


class CategoricalBandit:
    def __init__(self, arms: list[str]) -> None:
        self.arms = list(dict.fromkeys([str(a) for a in arms if str(a)]))
        self.stats: dict[str, ArmStats] = {a: ArmStats() for a in self.arms}

    def update(self, arm: str, reward: float) -> None:
        a = str(arm)
        if a not in self.stats:
            self.arms.append(a)
            self.stats[a] = ArmStats()
        self.stats[a].update(reward)

    def best(self, rng: random.Random, explore: float = 0.15) -> str:
        if not self.arms:
            return ""
        best_arm = self.arms[0]
        best_val = -1e9
        for a in self.arms:
            val = self.stats[a].sample(rng, explore=explore)
            if val > best_val:
                best_val = val
                best_arm = a
        return best_arm

    def mean(self, arm: str) -> float:
        a = str(arm)
        if a not in self.stats:
            return 0.0
        return float(self.stats[a].mean)

    def count(self, arm: str) -> int:
        a = str(arm)
        if a not in self.stats:
            return 0
        return int(self.stats[a].n)

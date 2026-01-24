\
import random
from typing import Dict, List, Sequence, Tuple, TypeVar

T = TypeVar("T")


def weighted_choice(weights: Dict[T, float]) -> T:
    items = [(k, float(v)) for k, v in weights.items() if float(v) > 0]
    if not items:
        return random.choice(list(weights.keys()))
    total = sum(w for _, w in items)
    r = random.random() * total
    acc = 0.0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def shuffled(seq: Sequence[T]) -> List[T]:
    out = list(seq)
    random.shuffle(out)
    return out

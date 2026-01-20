from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping


def load_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for row in r:
            rows.append({k: (v.strip() if isinstance(v, str) else "") for k, v in row.items()})
        return rows


@dataclass
class DatasetRegistry:
    datasets: Dict[str, List[Dict[str, str]]]

    @staticmethod
    def load_from_dir(datasets_dir: Path) -> "DatasetRegistry":
        datasets: Dict[str, List[Dict[str, str]]] = {}
        if not datasets_dir.exists():
            return DatasetRegistry(datasets={})

        for path in sorted(datasets_dir.glob("*.csv")):
            name = path.stem
            datasets[name] = load_csv(path)
        return DatasetRegistry(datasets=datasets)

    def get(self, name: str) -> List[Dict[str, str]]:
        return self.datasets.get(name, [])

    def available(self) -> List[str]:
        return sorted(self.datasets.keys())

\
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from autoyt.utils.fs import ensure_dir
from autoyt.utils.logging_utils import get_logger

log = get_logger("autoyt.country_data")


# NOTE (2025+): RestCountries "all" endpoint returns 400 unless `fields` is
# specified. We request only what we need (<=10 fields).
RESTCOUNTRIES_ALL = "https://restcountries.com/v3.1/all?fields=name,cca2,capital,region,subregion,population,currencies"


@dataclass(frozen=True)
class Country:
    name: str
    cca2: str
    capital: str
    region: str
    subregion: str
    population: int
    currencies: List[str]

    @property
    def flag_emoji(self) -> str:
        # Regional indicator symbols from A-Z
        if not self.cca2 or len(self.cca2) != 2:
            return ""
        out = ""
        for ch in self.cca2.upper():
            if "A" <= ch <= "Z":
                out += chr(127397 + ord(ch))
        return out


_FALLBACK_MINI: List[Dict[str, Any]] = [
    {"name": "United States", "cca2": "US", "capital": "Washington, D.C.", "region": "Americas", "subregion": "North America", "population": 331002651, "currencies": ["USD"]},
    {"name": "Canada", "cca2": "CA", "capital": "Ottawa", "region": "Americas", "subregion": "North America", "population": 37742154, "currencies": ["CAD"]},
    {"name": "Brazil", "cca2": "BR", "capital": "Brasília", "region": "Americas", "subregion": "South America", "population": 212559417, "currencies": ["BRL"]},
    {"name": "United Kingdom", "cca2": "GB", "capital": "London", "region": "Europe", "subregion": "Northern Europe", "population": 67886011, "currencies": ["GBP"]},
    {"name": "France", "cca2": "FR", "capital": "Paris", "region": "Europe", "subregion": "Western Europe", "population": 65273511, "currencies": ["EUR"]},
    {"name": "Germany", "cca2": "DE", "capital": "Berlin", "region": "Europe", "subregion": "Western Europe", "population": 83783942, "currencies": ["EUR"]},
    {"name": "Japan", "cca2": "JP", "capital": "Tokyo", "region": "Asia", "subregion": "Eastern Asia", "population": 126476461, "currencies": ["JPY"]},
    {"name": "South Korea", "cca2": "KR", "capital": "Seoul", "region": "Asia", "subregion": "Eastern Asia", "population": 51269185, "currencies": ["KRW"]},
    {"name": "Australia", "cca2": "AU", "capital": "Canberra", "region": "Oceania", "subregion": "Australia and New Zealand", "population": 25499884, "currencies": ["AUD"]},
    {"name": "Egypt", "cca2": "EG", "capital": "Cairo", "region": "Africa", "subregion": "Northern Africa", "population": 102334404, "currencies": ["EGP"]},
]


class CountryDataset:
    def __init__(self, countries: List[Country]) -> None:
        self.countries = countries

    @classmethod
    def load(cls, cache_dir: Path, timeout_s: int = 30) -> "CountryDataset":
        ensure_dir(cache_dir)
        cache_path = cache_dir / "restcountries_all.json"

        data: Optional[List[Dict[str, Any]]] = None

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if not isinstance(data, list) or len(data) < 50:
                    data = None
            except Exception:
                data = None

        if data is None:
            try:
                log.info("Downloading RestCountries dataset…")
                resp = requests.get(RESTCOUNTRIES_ALL, timeout=timeout_s, headers={"User-Agent": "autoyt/1.0"})
                resp.raise_for_status()
                data = resp.json()
                cache_path.write_text(json.dumps(data), encoding="utf-8")
            except Exception as e:
                log.warning(f"RestCountries download failed, using fallback mini dataset. Reason: {e}")
                data = _FALLBACK_MINI

        countries: List[Country] = []
        for item in data:
            try:
                name = (item.get("name") or {}).get("common") or item.get("name") or ""
                cca2 = item.get("cca2") or item.get("cca2") or ""
                capital_list = item.get("capital") or []
                capital = capital_list[0] if isinstance(capital_list, list) and capital_list else item.get("capital") or ""
                region = item.get("region") or ""
                subregion = item.get("subregion") or ""
                population = int(item.get("population") or 0)
                currencies_obj = item.get("currencies") or {}
                currencies = sorted(list(currencies_obj.keys())) if isinstance(currencies_obj, dict) else []
                if not name or not capital or not cca2:
                    continue
                countries.append(
                    Country(
                        name=str(name),
                        cca2=str(cca2),
                        capital=str(capital),
                        region=str(region),
                        subregion=str(subregion),
                        population=population,
                        currencies=currencies,
                    )
                )
            except Exception:
                continue

        # Deduplicate by cca2
        uniq: Dict[str, Country] = {}
        for c in countries:
            uniq[c.cca2.upper()] = c
        countries = sorted(uniq.values(), key=lambda x: x.name)

        if len(countries) < 10:
            # absolute last resort
            countries = [Country(**d) for d in _FALLBACK_MINI]  # type: ignore[arg-type]

        return cls(countries=countries)

    def by_region(self, region: str) -> List[Country]:
        r = region.strip().lower()
        return [c for c in self.countries if c.region.strip().lower() == r]

    def find_by_name(self, name: str) -> Optional[Country]:
        n = name.strip().lower()
        for c in self.countries:
            if c.name.lower() == n:
                return c
        return None

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from ytquiz.log import Log
from ytquiz.utils import ensure_dir, save_json


_RESTCOUNTRIES_URL = "https://restcountries.com/v3.1/all?fields=name,capital,continents,currencies,cca2"


def load_countries(datasets_dir: Path, log: Log) -> list[dict[str, Any]]:
    ensure_dir(datasets_dir)
    cache_path = datasets_dir / "countries.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data = _download_restcountries(log)
    if not data:
        data = _fallback_countries()

    cleaned = _clean_countries(data)
    if cleaned:
        save_json(cache_path, cleaned)
    return cleaned


def _download_restcountries(log: Log) -> list[dict[str, Any]] | None:
    try:
        r = requests.get(_RESTCOUNTRIES_URL, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warn(f"Failed to download RestCountries data: {e}")
        return None


def _clean_countries(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            name = (item.get("name") or {}).get("common") or ""
            if not name:
                continue
            caps = item.get("capital") or []
            capital = caps[0] if isinstance(caps, list) and caps else ""
            conts = item.get("continents") or []
            continent = conts[0] if isinstance(conts, list) and conts else ""
            currencies = item.get("currencies") or {}
            currency_name = ""
            currency_code = ""
            if isinstance(currencies, dict) and currencies:
                currency_code = next(iter(currencies.keys()))
                cobj = currencies.get(currency_code) or {}
                currency_name = (cobj.get("name") or "").strip()
            cca2 = (item.get("cca2") or "").strip()

            if not capital or not continent:
                continue

            entry = {
                "country": str(name).strip(),
                "capital": str(capital).strip(),
                "continent": str(continent).strip(),
                "currency_name": str(currency_name).strip() or str(currency_code).strip(),
                "currency_code": str(currency_code).strip(),
                "cca2": cca2,
            }
            if not entry["currency_name"]:
                continue
            out.append(entry)
        except Exception:
            continue

    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for e in out:
        k = (e["country"].lower(), e["capital"].lower())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    return uniq


def _fallback_countries() -> list[dict[str, Any]]:
    return [
        {"country": "Japan", "capital": "Tokyo", "continent": "Asia", "currency_name": "Japanese yen", "currency_code": "JPY", "cca2": "JP"},
        {"country": "Canada", "capital": "Ottawa", "continent": "North America", "currency_name": "Canadian dollar", "currency_code": "CAD", "cca2": "CA"},
        {"country": "Brazil", "capital": "Brasilia", "continent": "South America", "currency_name": "Brazilian real", "currency_code": "BRL", "cca2": "BR"},
        {"country": "France", "capital": "Paris", "continent": "Europe", "currency_name": "Euro", "currency_code": "EUR", "cca2": "FR"},
        {"country": "Australia", "capital": "Canberra", "continent": "Oceania", "currency_name": "Australian dollar", "currency_code": "AUD", "cca2": "AU"},
        {"country": "Egypt", "capital": "Cairo", "continent": "Africa", "currency_name": "Egyptian pound", "currency_code": "EGP", "cca2": "EG"},
        {"country": "India", "capital": "New Delhi", "continent": "Asia", "currency_name": "Indian rupee", "currency_code": "INR", "cca2": "IN"},
        {"country": "Mexico", "capital": "Mexico City", "continent": "North America", "currency_name": "Mexican peso", "currency_code": "MXN", "cca2": "MX"},
        {"country": "Argentina", "capital": "Buenos Aires", "continent": "South America", "currency_name": "Argentine peso", "currency_code": "ARS", "cca2": "AR"},
        {"country": "South Africa", "capital": "Pretoria", "continent": "Africa", "currency_name": "South African rand", "currency_code": "ZAR", "cca2": "ZA"},
    ]

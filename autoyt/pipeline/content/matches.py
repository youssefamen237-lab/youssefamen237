\
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from autoyt.utils.logging_utils import get_logger
from autoyt.utils.text import normalize_key

log = get_logger("autoyt.matches")


@dataclass(frozen=True)
class Match:
    kickoff_utc: dt.datetime
    competition: str
    home: str
    away: str

    @property
    def match_date(self) -> dt.date:
        return self.kickoff_utc.date()


# football-data.org competition codes (v4)
# Docs/examples use competition codes like PL, PD, SA, BL1, FL1, CL.
# Using codes is more reliable across tiers than numeric IDs.
FOOTBALL_DATA_COMPETITIONS: Dict[str, str] = {
    "UEFA Champions League": "CL",
    "Premier League": "PL",
    "La Liga": "PD",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue 1": "FL1",
}

# API-Football league IDs (api-sports v3)
API_FOOTBALL_LEAGUES: Dict[str, int] = {
    "UEFA Champions League": 2,
    "Premier League": 39,
    "La Liga": 140,
    "Bundesliga": 78,
    "Serie A": 135,
    "Ligue 1": 61,
}

BIG_CLUBS = {
    # Spain
    "Real Madrid CF", "FC Barcelona", "Atlético de Madrid",
    # England
    "Manchester City FC", "Liverpool FC", "Manchester United FC", "Arsenal FC", "Chelsea FC", "Tottenham Hotspur FC",
    # Germany
    "FC Bayern München", "Borussia Dortmund",
    # France
    "Paris Saint-Germain FC",
    # Italy
    "Juventus FC", "AC Milan", "Inter Milan", "SSC Napoli",
}


def _team_score(name: str) -> int:
    return 2 if name in BIG_CLUBS else (1 if any(name.startswith(x.split()[0]) for x in BIG_CLUBS) else 0)


def is_big_match(home: str, away: str) -> bool:
    # Big if both are in big clubs, or if combined score >= 3
    return (_team_score(home) + _team_score(away)) >= 3


def dupe_key_for_match(home: str, away: str, date: dt.date) -> str:
    a, b = sorted([home.strip(), away.strip()])
    return normalize_key(f"match::{a}::{b}::{date.isoformat()}")


def fetch_matches_football_data(token: str, date_from: dt.date, date_to: dt.date, timeout_s: int = 30) -> List[Match]:
    matches: List[Match] = []
    headers = {"X-Auth-Token": token, "User-Agent": "autoyt/1.0"}
    for comp_name, comp_id in FOOTBALL_DATA_COMPETITIONS.items():
        url = f"https://api.football-data.org/v4/competitions/{comp_id}/matches"
        params = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "status": "SCHEDULED",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout_s)
            if resp.status_code == 429:
                log.warning("football-data.org rate limited (429).")
                continue
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("matches", []) or []:
                utc_date = m.get("utcDate")
                if not utc_date:
                    continue
                try:
                    kickoff = dt.datetime.fromisoformat(utc_date.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
                except Exception:
                    continue
                home = (m.get("homeTeam") or {}).get("name") or ""
                away = (m.get("awayTeam") or {}).get("name") or ""
                if not home or not away:
                    continue
                matches.append(Match(kickoff_utc=kickoff, competition=comp_name, home=home, away=away))
        except Exception as e:
            log.warning(f"football-data.org failed for {comp_name}: {e}")
            continue

    return matches


def _season_for_date(d: dt.date) -> int:
    # European seasons usually start around Aug (month 8). Using July (7) as threshold.
    return d.year if d.month >= 7 else d.year - 1


def fetch_matches_api_football(api_key: str, date_from: dt.date, date_to: dt.date, timeout_s: int = 30) -> List[Match]:
    matches: List[Match] = []
    headers = {"x-apisports-key": api_key, "User-Agent": "autoyt/1.0"}
    season = _season_for_date(date_from)

    for comp_name, league_id in API_FOOTBALL_LEAGUES.items():
        url = "https://v3.football.api-sports.io/fixtures"
        params = {
            "league": league_id,
            "season": season,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout_s)
            if resp.status_code == 429:
                log.warning("api-football rate limited (429).")
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            for item in data.get("response", []) or []:
                fixture = item.get("fixture") or {}
                kickoff_str = (fixture.get("date") or "")
                if not kickoff_str:
                    continue
                try:
                    kickoff = dt.datetime.fromisoformat(kickoff_str.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
                except Exception:
                    continue
                teams = item.get("teams") or {}
                home = (teams.get("home") or {}).get("name") or ""
                away = (teams.get("away") or {}).get("name") or ""
                if not home or not away:
                    continue
                matches.append(Match(kickoff_utc=kickoff, competition=comp_name, home=home, away=away))
        except Exception as e:
            log.warning(f"api-football failed for {comp_name}: {e}")
            continue

    return matches


def fetch_big_matches(
    lookahead_days: int,
    football_data_token: Optional[str],
    api_football_key: Optional[str],
    now_utc: Optional[dt.datetime] = None,
) -> List[Match]:
    now_utc = now_utc or dt.datetime.now(tz=dt.timezone.utc)
    date_from = now_utc.date()
    date_to = (now_utc + dt.timedelta(days=lookahead_days)).date()

    all_matches: List[Match] = []

    if football_data_token:
        all_matches.extend(fetch_matches_football_data(football_data_token, date_from, date_to))

    if not all_matches and api_football_key:
        # Only use API-Football if football-data returned nothing / failed
        all_matches.extend(fetch_matches_api_football(api_football_key, date_from, date_to))

    big = [m for m in all_matches if is_big_match(m.home, m.away)]
    big.sort(key=lambda x: x.kickoff_utc)
    return big

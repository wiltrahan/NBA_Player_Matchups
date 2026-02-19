from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx

from app.models import Game, GameLine


TEAM_NAME_BY_ABBR: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


@dataclass(slots=True)
class OddsAPIConfig:
    api_key: str | None
    sport_key: str
    regions: str
    markets: str
    odds_format: str
    date_format: str
    timeout_seconds: float


class OddsAPIService:
    def __init__(self, config: OddsAPIConfig | None = None) -> None:
        if config is None:
            config = OddsAPIConfig(
                api_key=os.getenv("THE_ODDS_API_KEY"),
                sport_key=os.getenv("THE_ODDS_SPORT", "basketball_nba"),
                regions=os.getenv("THE_ODDS_REGIONS", "us"),
                markets=os.getenv("THE_ODDS_MARKETS", "spreads,totals"),
                odds_format=os.getenv("THE_ODDS_FORMAT", "american"),
                date_format=os.getenv("THE_ODDS_DATE_FORMAT", "iso"),
                timeout_seconds=float(os.getenv("THE_ODDS_TIMEOUT_SECONDS", "8.0")),
            )
        self._config = config

    async def fetch_game_lines(self, games: list[Game]) -> list[GameLine]:
        if not self._config.api_key:
            return [
                GameLine(
                    game_id=game.game_id,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    source="odds-api-unconfigured",
                )
                for game in games
            ]

        events = await self._fetch_events()
        by_matchup: dict[tuple[str, str], dict[str, Any]] = {}
        for event in events:
            home_team = event.get("home_team")
            away_team = event.get("away_team")
            if isinstance(home_team, str) and isinstance(away_team, str):
                by_matchup[(away_team.strip().lower(), home_team.strip().lower())] = event

        lines: list[GameLine] = []
        for game in games:
            away_name = TEAM_NAME_BY_ABBR.get(game.away_team, game.away_team).lower()
            home_name = TEAM_NAME_BY_ABBR.get(game.home_team, game.home_team).lower()
            event = by_matchup.get((away_name, home_name))
            if not event:
                lines.append(
                    GameLine(
                        game_id=game.game_id,
                        away_team=game.away_team,
                        home_team=game.home_team,
                        source="odds-api-no-match",
                    )
                )
                continue

            away_spread, home_spread, game_total = self._extract_market_lines(event)
            lines.append(
                GameLine(
                    game_id=game.game_id,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    away_spread=away_spread,
                    home_spread=home_spread,
                    game_total=game_total,
                    source="odds-api",
                )
            )

        return lines

    async def _fetch_events(self) -> list[dict[str, Any]]:
        url = f"https://api.the-odds-api.com/v4/sports/{self._config.sport_key}/odds"
        params = {
            "apiKey": self._config.api_key,
            "regions": self._config.regions,
            "markets": self._config.markets,
            "oddsFormat": self._config.odds_format,
            "dateFormat": self._config.date_format,
        }
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _extract_market_lines(self, event: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            return None, None, None

        home_name = str(event.get("home_team", "")).strip().lower()
        away_name = str(event.get("away_team", "")).strip().lower()
        away_spread: float | None = None
        home_spread: float | None = None
        game_total: float | None = None

        for bookmaker in bookmakers:
            if not isinstance(bookmaker, dict):
                continue
            markets = bookmaker.get("markets")
            if not isinstance(markets, list):
                continue

            for market in markets:
                if not isinstance(market, dict):
                    continue
                key = str(market.get("key", "")).strip().lower()
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue

                if key == "spreads" and (away_spread is None or home_spread is None):
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        point = self._to_float(outcome.get("point"))
                        name = str(outcome.get("name", "")).strip().lower()
                        if point is None:
                            continue
                        if name == away_name:
                            away_spread = point
                        elif name == home_name:
                            home_spread = point

                if key == "totals" and game_total is None:
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        point = self._to_float(outcome.get("point"))
                        if point is not None:
                            game_total = point
                            break

            if away_spread is not None and home_spread is not None and game_total is not None:
                break

        return away_spread, home_spread, game_total

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None


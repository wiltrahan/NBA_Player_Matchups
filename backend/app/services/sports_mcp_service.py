from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Iterable

import httpx

from app.models import Game, GameLine


TEAM_ABBR_ALIASES: dict[str, tuple[str, ...]] = {
    "ATL": ("atlanta hawks", "hawks"),
    "BOS": ("boston celtics", "celtics", "boston"),
    "BKN": ("brooklyn nets", "nets", "brooklyn"),
    "CHA": ("charlotte hornets", "hornets", "charlotte"),
    "CHI": ("chicago bulls", "bulls", "chicago"),
    "CLE": ("cleveland cavaliers", "cavaliers", "cavs", "cleveland"),
    "DAL": ("dallas mavericks", "mavericks", "mavs", "dallas"),
    "DEN": ("denver nuggets", "nuggets", "denver"),
    "DET": ("detroit pistons", "pistons", "detroit"),
    "GSW": ("golden state warriors", "warriors", "golden state"),
    "HOU": ("houston rockets", "rockets", "houston"),
    "IND": ("indiana pacers", "pacers", "indiana"),
    "LAC": ("la clippers", "los angeles clippers", "clippers"),
    "LAL": ("los angeles lakers", "la lakers", "lakers"),
    "MEM": ("memphis grizzlies", "grizzlies", "memphis"),
    "MIA": ("miami heat", "heat", "miami"),
    "MIL": ("milwaukee bucks", "bucks", "milwaukee"),
    "MIN": ("minnesota timberwolves", "timberwolves", "wolves", "minnesota"),
    "NOP": ("new orleans pelicans", "pelicans", "new orleans"),
    "NYK": ("new york knicks", "knicks", "new york"),
    "OKC": ("oklahoma city thunder", "thunder", "oklahoma city"),
    "ORL": ("orlando magic", "magic", "orlando"),
    "PHI": ("philadelphia 76ers", "76ers", "sixers", "philadelphia"),
    "PHX": ("phoenix suns", "suns", "phoenix"),
    "POR": ("portland trail blazers", "trail blazers", "blazers", "portland"),
    "SAC": ("sacramento kings", "kings", "sacramento"),
    "SAS": ("san antonio spurs", "spurs", "san antonio"),
    "TOR": ("toronto raptors", "raptors", "toronto"),
    "UTA": ("utah jazz", "jazz", "utah"),
    "WAS": ("washington wizards", "wizards", "washington"),
}


@dataclass(slots=True)
class SportsMCPConfig:
    url: str | None
    competition_names: tuple[str, ...]
    timeout_seconds: float
    limit: int


class SportsMCPService:
    def __init__(self, config: SportsMCPConfig | None = None) -> None:
        if config is None:
            raw_competitions = os.getenv("SPORTS_MCP_COMPETITIONS", "").strip()
            if raw_competitions:
                competition_names = tuple(
                    token.strip() for token in raw_competitions.split(",") if token.strip()
                )
            else:
                primary = os.getenv("SPORTS_MCP_COMPETITION", "NBA")
                competition_names = (primary, "basketball-usa-nba")
            config = SportsMCPConfig(
                url=os.getenv("SPORTS_MCP_URL"),
                competition_names=competition_names,
                timeout_seconds=float(os.getenv("SPORTS_MCP_TIMEOUT_SECONDS", "8.0")),
                limit=int(os.getenv("SPORTS_MCP_LIMIT", "50")),
            )
        self._config = config

    async def fetch_game_lines(self, games: list[Game]) -> list[GameLine]:
        if not self._config.url or not games:
            return [
                GameLine(
                    game_id=game.game_id,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    source="mcp-unconfigured",
                )
                for game in games
            ]

        events = await self._fetch_competition_events()
        if not events:
            return [
                GameLine(
                    game_id=game.game_id,
                    away_team=game.away_team,
                    home_team=game.home_team,
                    source="mcp-no-events",
                )
                for game in games
            ]
        lines_by_game_id = {
            game.game_id: self._line_from_event(game, events) for game in games
        }
        return [lines_by_game_id[game.game_id] for game in games]

    async def fetch_event_diagnostics(self, limit: int = 15) -> dict[str, Any]:
        if not self._config.url:
            return {
                "configured": False,
                "competition_names": list(self._config.competition_names),
                "event_count": 0,
                "samples": [],
            }

        events = await self._fetch_competition_events()
        samples: list[dict[str, Any]] = []
        for event in events[: max(1, limit)]:
            markets = event.get("markets")
            market_labels: list[str] = []
            if isinstance(markets, list):
                for market in markets:
                    if not isinstance(market, dict):
                        continue
                    label = (
                        market.get("key")
                        or market.get("name")
                        or market.get("type")
                        or market.get("marketType")
                    )
                    if isinstance(label, str):
                        market_labels.append(label)

            samples.append(
                {
                    "id": event.get("id") or event.get("eventId"),
                    "name": event.get("name") or event.get("eventName") or event.get("matchName"),
                    "homeTeam": event.get("homeTeam"),
                    "awayTeam": event.get("awayTeam"),
                    "haystack_excerpt": self._event_haystack(event)[:260],
                    "market_labels": market_labels[:12],
                }
            )

        return {
            "configured": True,
            "competition_names": list(self._config.competition_names),
            "event_count": len(events),
            "samples": samples,
        }

    async def _fetch_competition_events(self) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            for index, competition_name in enumerate(self._config.competition_names, start=1):
                payload = {
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {
                        "name": "findEventsAndMarketsByCompetition",
                        "arguments": {
                            "competitionName": competition_name,
                            "limit": self._config.limit,
                        },
                    },
                }
                response = await client.post(self._config.url, json=payload)
                response.raise_for_status()
                body = response.json()
                for event in self._extract_events(body):
                    event_key = str(
                        event.get("id")
                        or event.get("eventId")
                        or event.get("name")
                        or event.get("eventName")
                        or id(event)
                    )
                    if event_key in seen_keys:
                        continue
                    seen_keys.add(event_key)
                    merged.append(event)
        return merged

    def _line_from_event(self, game: Game, events: list[dict[str, Any]]) -> GameLine:
        event = self._match_event(game, events)
        if not event:
            return GameLine(
                game_id=game.game_id,
                away_team=game.away_team,
                home_team=game.home_team,
                source="mcp-no-match",
            )

        away_spread, home_spread, game_total = self._extract_market_lines(event)
        return GameLine(
            game_id=game.game_id,
            away_team=game.away_team,
            home_team=game.home_team,
            away_spread=away_spread,
            home_spread=home_spread,
            game_total=game_total,
            source="mcp",
        )

    def _match_event(self, game: Game, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        away_aliases = tuple(
            dict.fromkeys(
                [
                    game.away_team.lower(),
                    *TEAM_ABBR_ALIASES.get(game.away_team, (game.away_team.lower(),)),
                ]
            )
        )
        home_aliases = tuple(
            dict.fromkeys(
                [
                    game.home_team.lower(),
                    *TEAM_ABBR_ALIASES.get(game.home_team, (game.home_team.lower(),)),
                ]
            )
        )

        for event in events:
            haystack = self._event_haystack(event)
            if any(alias in haystack for alias in away_aliases) and any(alias in haystack for alias in home_aliases):
                return event
        return None

    @staticmethod
    def _event_haystack(event: dict[str, Any]) -> str:
        return " | ".join(SportsMCPService._collect_strings(event)).lower()

    @staticmethod
    def _collect_strings(node: Any, *, depth: int = 0, max_depth: int = 5) -> list[str]:
        if depth > max_depth:
            return []
        if isinstance(node, str):
            trimmed = node.strip()
            return [trimmed] if trimmed else []
        if isinstance(node, dict):
            out: list[str] = []
            for value in node.values():
                out.extend(SportsMCPService._collect_strings(value, depth=depth + 1, max_depth=max_depth))
            return out
        if isinstance(node, list):
            out: list[str] = []
            for item in node:
                out.extend(SportsMCPService._collect_strings(item, depth=depth + 1, max_depth=max_depth))
            return out
        return []

    def _extract_market_lines(self, event: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        markets = event.get("markets")
        if not isinstance(markets, list):
            return None, None, None

        away_spread: float | None = None
        home_spread: float | None = None
        game_total: float | None = None

        for market in markets:
            if not isinstance(market, dict):
                continue
            market_key = " ".join(
                str(market.get(key, "")).lower() for key in ("key", "name", "type", "marketType")
            )
            selections = market.get("selections")
            if not isinstance(selections, list):
                selections = market.get("outcomes")
            if not isinstance(selections, list):
                selections = []

            if ("handicap" in market_key or "spread" in market_key) and (away_spread is None or home_spread is None):
                away_spread, home_spread = self._extract_spreads(selections)
            if ("totals" in market_key or "total" in market_key or "over/under" in market_key) and game_total is None:
                game_total = self._extract_total(market, selections)

        return away_spread, home_spread, game_total

    @staticmethod
    def _extract_spreads(selections: list[Any]) -> tuple[float | None, float | None]:
        numeric_lines: list[float] = []
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            for key in ("line", "handicap", "points"):
                value = selection.get(key)
                number = SportsMCPService._to_float(value)
                if number is not None:
                    numeric_lines.append(number)
                    break
        if not numeric_lines:
            return None, None
        if len(numeric_lines) == 1:
            line = numeric_lines[0]
            return line, -line
        return numeric_lines[0], numeric_lines[1]

    @staticmethod
    def _extract_total(market: dict[str, Any], selections: list[Any]) -> float | None:
        for key in ("line", "total", "points"):
            number = SportsMCPService._to_float(market.get(key))
            if number is not None:
                return number
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            for key in ("line", "total", "points"):
                number = SportsMCPService._to_float(selection.get(key))
                if number is not None:
                    return number
        return None

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

    def _extract_events(self, mcp_payload: Any) -> list[dict[str, Any]]:
        candidates: list[Any] = []
        if isinstance(mcp_payload, dict):
            candidates.append(mcp_payload.get("result", mcp_payload))
        else:
            candidates.append(mcp_payload)

        queue = list(candidates)
        visited = 0
        while queue and visited < 2000:
            visited += 1
            node = queue.pop(0)
            if isinstance(node, dict):
                events = node.get("events")
                if isinstance(events, list) and all(isinstance(item, dict) for item in events):
                    return events
                content = node.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if isinstance(item.get("json"), (dict, list)):
                                queue.append(item["json"])
                            text = item.get("text")
                            if isinstance(text, str):
                                try:
                                    queue.append(json.loads(text))
                                except Exception:
                                    continue
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(node, list):
                queue.extend(item for item in node if isinstance(item, (dict, list)))

        return []

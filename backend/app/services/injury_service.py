from __future__ import annotations

import os
import re
from datetime import date, datetime
from time import monotonic
from typing import Any, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.models import InjuryTag
from app.services.odds_api_service import TEAM_NAME_BY_ABBR


class InjuryService:
    _STATUS_NORMALIZATION = {
        "OUT": "OUT",
        "O": "OUT",
        "DOUBTFUL": "DOUBTFUL",
        "D": "DOUBTFUL",
        "QUESTIONABLE": "QUESTIONABLE",
        "Q": "QUESTIONABLE",
        "PROBABLE": "PROBABLE",
        "P": "PROBABLE",
        "GAME TIME DECISION": "GTD",
        "GTD": "GTD",
    }
    _INJURY_ROW_KEYS = {
        "playerName",
        "player_name",
        "player",
        "name",
        "status",
        "injuryStatus",
        "designation",
        "teamAbbrev",
        "team",
        "teamCode",
        "notes",
        "description",
    }

    def __init__(self, timeout_seconds: float = 8.0, ttl_seconds: int = 300) -> None:
        self._timeout = timeout_seconds
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, List[InjuryTag]]] = {}
        self._team_abbr_by_name = {
            re.sub(r"[^a-z0-9]+", "", name.lower()): abbr for abbr, name in TEAM_NAME_BY_ABBR.items()
        }

    async def fetch_injuries(self, slate_date: date) -> List[InjuryTag]:
        cache_key = slate_date.isoformat()
        cached = self._cache.get(cache_key)
        now = monotonic()
        if cached and now - cached[0] < self._ttl_seconds:
            return cached[1]

        providers = self._provider_urls(slate_date)
        for source, url, headers in providers:
            injuries, _ = await self._fetch_provider_injuries(source=source, url=url, headers=headers)
            if not injuries:
                continue
            self._cache[cache_key] = (now, injuries)
            return injuries

        return []

    async def fetch_injuries_debug(self, slate_date: date) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        for source, url, headers in self._provider_urls(slate_date):
            injuries, detail = await self._fetch_provider_injuries(source=source, url=url, headers=headers)
            diagnostics.append(
                {
                    "source": source,
                    "url": self._redact_url(url),
                    "status_code": detail.get("status_code"),
                    "error": detail.get("error"),
                    "payload_type": detail.get("payload_type"),
                    "candidate_rows": detail.get("candidate_rows"),
                    "parsed_injuries": len(injuries),
                    "sample": [
                        {
                            "team": injury.team,
                            "player_name": injury.player_name,
                            "status": injury.status,
                            "comment": injury.comment,
                        }
                        for injury in injuries[:5]
                    ],
                }
            )
        return {
            "slate_date": slate_date.isoformat(),
            "providers": diagnostics,
        }

    @staticmethod
    def _redact_url(url: str) -> str:
        parts = urlsplit(url)
        if not parts.query:
            return url
        sanitized = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in {"apikey", "api_key", "key", "token"}:
                sanitized.append((key, "***redacted***"))
            else:
                sanitized.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sanitized), parts.fragment))

    async def _fetch_provider_injuries(
        self,
        source: str,
        url: str,
        headers: dict[str, str] | None,
    ) -> tuple[List[InjuryTag], dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
            status_code = response.status_code
            if status_code != 200:
                return [], {"status_code": status_code, "error": None}
            payload = response.json()
            injuries = self._extract_injuries(payload=payload, source=source, default_team=None)
            candidate_rows = len(self._collect_candidate_rows(payload)) if isinstance(payload, (dict, list)) else 0
            return injuries, {
                "status_code": status_code,
                "error": None,
                "payload_type": type(payload).__name__,
                "candidate_rows": candidate_rows,
            }
        except Exception as exc:
            return [], {"status_code": None, "error": str(exc)}

    def _provider_urls(self, slate_date: date) -> list[tuple[str, str, dict[str, str] | None]]:
        date_token = slate_date.strftime("%Y%m%d")
        browser_headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nba.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        }
        urls: list[tuple[str, str, dict[str, str] | None]] = [
            (
                "espn",
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
                {
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    ),
                },
            ),
            (
                "nba-cdn",
                f"https://cdn.nba.com/static/json/liveData/injuryReport/injuryReport_{date_token}.json",
                browser_headers,
            ),
            (
                "nba-cdn",
                "https://cdn.nba.com/static/json/liveData/injuryReport/injuryReport.json",
                browser_headers,
            ),
        ]

        odds_key = os.getenv("THE_ODDS_API_KEY", "").strip()
        odds_sport = os.getenv("THE_ODDS_SPORT", "basketball_nba").strip() or "basketball_nba"
        if odds_key:
            urls.append(
                (
                    "odds-api",
                    f"https://api.the-odds-api.com/v4/sports/{odds_sport}/injuries?apiKey={odds_key}",
                    None,
                )
            )

        fallback_url = os.getenv("INJURY_FALLBACK_URL", "").strip()
        fallback_key = os.getenv("INJURY_FALLBACK_API_KEY", "").strip()
        fallback_key_header = os.getenv("INJURY_FALLBACK_API_KEY_HEADER", "x-api-key").strip() or "x-api-key"
        if fallback_url:
            headers = {fallback_key_header: fallback_key} if fallback_key else None
            urls.append(
                (
                    "injury-fallback",
                    fallback_url.format(date=slate_date.isoformat(), date_token=date_token),
                    headers,
                )
            )
        return urls

    def _extract_injuries(self, payload: Any, source: str, default_team: str | None) -> List[InjuryTag]:
        if source == "odds-api":
            return self._extract_odds_api_injuries(payload)
        if source == "espn":
            return self._extract_espn_injuries(payload)

        rows: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            injury_report = payload.get("injuryReport")
            if isinstance(injury_report, dict):
                maybe_rows = injury_report.get("injuries") or injury_report.get("rows")
                if isinstance(maybe_rows, list):
                    rows = [row for row in maybe_rows if isinstance(row, dict)]
            if not rows:
                maybe_rows = payload.get("injuries") or payload.get("data")
                if isinstance(maybe_rows, list):
                    rows = [row for row in maybe_rows if isinstance(row, dict)]
            if not rows:
                rows = self._collect_candidate_rows(payload)
        elif isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]

        injuries: List[InjuryTag] = []
        for row in rows:
            player_name = str(
                row.get("playerName")
                or row.get("name")
                or row.get("player")
                or row.get("player_name")
                or ""
            ).strip()
            raw_team = str(
                row.get("teamAbbrev")
                or row.get("team")
                or row.get("teamCode")
                or row.get("team_abbrev")
                or ""
            ).strip()
            team = self._normalize_team(raw_team) or (default_team or "")
            raw_status = str(
                row.get("status")
                or row.get("injuryStatus")
                or row.get("designation")
                or row.get("player_status")
                or ""
            ).strip().upper()
            status = self._normalize_status(raw_status)
            comment = str(
                row.get("description")
                or row.get("notes")
                or row.get("comment")
                or ""
            ).strip() or None
            updated_at = self._parse_updated_at(
                row.get("lastUpdated")
                or row.get("updatedAt")
                or row.get("updated_at")
                or row.get("timestamp")
            )

            if not status and comment:
                status = self._infer_status_from_text(comment)

            if player_name and not player_name.upper().startswith("INJURY_STATUS_") and status:
                injuries.append(
                    InjuryTag(
                        player_name=player_name,
                        team=team or "UNK",
                        status=status,
                        comment=comment,
                        source=source,
                        updated_at=updated_at,
                    )
                )

        return injuries

    def _extract_odds_api_injuries(self, payload: Any) -> List[InjuryTag]:
        if not isinstance(payload, list):
            return []

        injuries: List[InjuryTag] = []
        for team_item in payload:
            if not isinstance(team_item, dict):
                continue
            raw_team = str(team_item.get("title") or team_item.get("team") or team_item.get("name") or "").strip()
            team = self._normalize_team(raw_team) or "UNK"
            team_injuries = team_item.get("injuries")
            if not isinstance(team_injuries, list):
                continue

            for injury_item in team_injuries:
                if not isinstance(injury_item, dict):
                    continue
                player_name = str(
                    injury_item.get("player")
                    or injury_item.get("playerName")
                    or injury_item.get("name")
                    or ""
                ).strip()
                raw_status = str(
                    injury_item.get("status")
                    or injury_item.get("designation")
                    or injury_item.get("injuryStatus")
                    or ""
                ).strip().upper()
                comment = str(
                    injury_item.get("description")
                    or injury_item.get("comment")
                    or injury_item.get("details")
                    or ""
                ).strip() or None
                status = self._normalize_status(raw_status)
                if not status and comment:
                    status = self._infer_status_from_text(comment)
                updated_at = self._parse_updated_at(
                    injury_item.get("updatedAt")
                    or injury_item.get("lastUpdate")
                    or team_item.get("last_update")
                )
                if player_name and status:
                    injuries.append(
                        InjuryTag(
                            player_name=player_name,
                            team=team,
                            status=status,
                            comment=comment,
                            source="odds-api",
                            updated_at=updated_at,
                        )
                    )
        return injuries

    def _extract_espn_injuries(self, payload: Any) -> List[InjuryTag]:
        nodes = self._collect_candidate_rows(payload, max_depth=8)
        injuries: List[InjuryTag] = []

        for node in nodes:
            athlete = node.get("athlete") if isinstance(node, dict) else None
            team_obj = node.get("team") if isinstance(node, dict) else None
            status_obj = node.get("status") if isinstance(node, dict) else None

            player_name = ""
            if isinstance(athlete, dict):
                player_name = str(
                    athlete.get("displayName")
                    or athlete.get("shortName")
                    or athlete.get("fullName")
                    or ""
                ).strip()
            if not player_name:
                player_name = str(node.get("playerName") or node.get("name") or "").strip()

            raw_team = ""
            if isinstance(team_obj, dict):
                raw_team = str(
                    team_obj.get("abbreviation")
                    or team_obj.get("shortDisplayName")
                    or team_obj.get("displayName")
                    or ""
                ).strip()
            if not raw_team:
                raw_team = str(node.get("team") or node.get("teamAbbrev") or "").strip()
            team = self._normalize_team(raw_team) or "UNK"

            raw_status = ""
            if isinstance(status_obj, dict):
                raw_status = str(
                    status_obj.get("name")
                    or status_obj.get("type")
                    or status_obj.get("abbreviation")
                    or ""
                ).strip().upper()
            if not raw_status:
                raw_status = str(
                    node.get("status")
                    or node.get("injuryStatus")
                    or node.get("designation")
                    or ""
                ).strip().upper()
            status = self._normalize_status(raw_status)

            comment = str(
                node.get("detail")
                or node.get("description")
                or node.get("longComment")
                or node.get("shortComment")
                or ""
            ).strip() or None
            if not status and comment:
                status = self._infer_status_from_text(comment)

            updated_at = self._parse_updated_at(
                node.get("date")
                or node.get("updated")
                or node.get("lastUpdated")
                or node.get("timestamp")
            )

            if player_name and status:
                injuries.append(
                    InjuryTag(
                        player_name=player_name,
                        team=team,
                        status=status,
                        comment=comment,
                        source="espn",
                        updated_at=updated_at,
                    )
                )

        deduped: dict[tuple[str, str], InjuryTag] = {}
        for injury in injuries:
            deduped[(injury.team, injury.player_name.upper())] = injury
        return list(deduped.values())

    def _collect_candidate_rows(self, payload: Any, depth: int = 0, max_depth: int = 6) -> List[dict[str, Any]]:
        if depth > max_depth:
            return []

        out: List[dict[str, Any]] = []
        if isinstance(payload, dict):
            keys = set(payload.keys())
            if keys.intersection(self._INJURY_ROW_KEYS) or "athlete" in keys or "status" in keys:
                out.append(payload)
            for value in payload.values():
                out.extend(self._collect_candidate_rows(value, depth=depth + 1, max_depth=max_depth))
            return out

        if isinstance(payload, list):
            for item in payload:
                out.extend(self._collect_candidate_rows(item, depth=depth + 1, max_depth=max_depth))
        return out

    def _normalize_status(self, raw_status: str) -> str:
        if not raw_status:
            return ""
        normalized = self._STATUS_NORMALIZATION.get(raw_status)
        if normalized:
            return normalized
        if "GAME" in raw_status and "DECISION" in raw_status:
            return "GTD"
        if "OUT" in raw_status:
            return "OUT"
        if "DOUBT" in raw_status:
            return "DOUBTFUL"
        if "QUESTION" in raw_status:
            return "QUESTIONABLE"
        if "PROB" in raw_status:
            return "PROBABLE"
        return raw_status

    def _normalize_team(self, value: str) -> str:
        candidate = value.strip().upper()
        if len(candidate) in (2, 3, 4) and candidate.isalpha():
            return candidate
        normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
        if not normalized:
            return ""
        return self._team_abbr_by_name.get(normalized, "")

    def _infer_status_from_text(self, text: str) -> str:
        raw = text.strip().upper()
        if "OUT" in raw:
            return "OUT"
        if "DOUBT" in raw:
            return "DOUBTFUL"
        if "QUESTION" in raw:
            return "QUESTIONABLE"
        if "PROB" in raw:
            return "PROBABLE"
        return ""

    @staticmethod
    def _parse_updated_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        raw = str(value).strip()
        if not raw:
            return None
        try:
            # Support trailing Z and plain ISO timestamps.
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

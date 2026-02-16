from __future__ import annotations

from datetime import date
from typing import List

import httpx

from app.models import InjuryTag


class InjuryService:
    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self._timeout = timeout_seconds

    async def fetch_injuries(self, slate_date: date) -> List[InjuryTag]:
        date_token = slate_date.strftime("%Y%m%d")
        urls = [
            f"https://cdn.nba.com/static/json/liveData/injuryReport/injuryReport_{date_token}.json",
            "https://cdn.nba.com/static/json/liveData/injuryReport/injuryReport.json",
        ]

        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url)
                if response.status_code != 200:
                    continue
                payload = response.json()
                rows = payload.get("injuryReport", {}).get("injuries", [])
                injuries: List[InjuryTag] = []
                for row in rows:
                    player_name = str(row.get("playerName") or row.get("name") or "").strip()
                    team = str(row.get("teamAbbrev") or row.get("team") or "").strip().upper()
                    status = str(row.get("status") or row.get("injuryStatus") or "").strip().upper()
                    comment = str(row.get("description") or row.get("notes") or "").strip() or None
                    if player_name and team and status:
                        injuries.append(
                            InjuryTag(
                                player_name=player_name,
                                team=team,
                                status=status,
                                comment=comment,
                            )
                        )
                return injuries
            except Exception:
                continue

        return []

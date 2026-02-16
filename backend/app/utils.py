from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import MatchupTier, PositionGroup

EASTERN = ZoneInfo("America/New_York")
SUPPORTED_STATS = ("PTS", "REB", "AST", "FG3M", "STL", "BLK")
DISPLAY_STATS = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "FG3M": "3PM",
    "STL": "STL",
    "BLK": "BLK",
}


def now_et() -> datetime:
    return datetime.now(tz=EASTERN)


def current_et_date() -> date:
    return now_et().date()


def season_label_for_date(target_date: date) -> str:
    year = target_date.year
    if target_date.month >= 10:
        start_year = year
    else:
        start_year = year - 1
    end_year_short = str((start_year + 1) % 100).zfill(2)
    return f"{start_year}-{end_year_short}"


def season_bounds_for_label(season_label: str) -> tuple[date, date]:
    start_year = int(season_label.split("-")[0])
    return date(start_year, 10, 1), date(start_year + 1, 6, 30)


def as_of_date_for_slate(slate_date: date) -> date:
    return slate_date - timedelta(days=1)


def map_position_groups(position: str | None) -> list[PositionGroup]:
    if not position:
        return []

    normalized = position.upper().replace("/", "-")
    parts = [part.strip() for part in normalized.split("-") if part.strip()]
    groups: list[PositionGroup] = []

    for part in parts:
        if part in {"PG", "SG", "G"} and PositionGroup.guards not in groups:
            groups.append(PositionGroup.guards)
        if part in {"SF", "PF", "F"} and PositionGroup.forwards not in groups:
            groups.append(PositionGroup.forwards)
        if part == "C" and PositionGroup.centers not in groups:
            groups.append(PositionGroup.centers)

    if "GUARD" in normalized and PositionGroup.guards not in groups:
        groups.append(PositionGroup.guards)
    if "FORWARD" in normalized and PositionGroup.forwards not in groups:
        groups.append(PositionGroup.forwards)
    if "CENTER" in normalized and PositionGroup.centers not in groups:
        groups.append(PositionGroup.centers)

    return groups


def parse_matchup_opponent(matchup: str | None) -> str | None:
    if not matchup:
        return None

    tokens = matchup.split()
    if not tokens:
        return None

    # Examples: "BOS @ CHI", "BOS vs. CHI"
    return tokens[-1].replace(".", "").strip().upper()


def to_tier(rank: int) -> MatchupTier:
    if rank <= 6:
        return MatchupTier.green
    if rank <= 12:
        return MatchupTier.yellow
    if rank <= 20:
        return MatchupTier.orange
    return MatchupTier.red


def normalize_score(value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        return 50.0
    return ((value - min_value) / (max_value - min_value)) * 100.0

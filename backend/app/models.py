from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Window(str, Enum):
    season = "season"
    last10 = "last10"


class PlayerCardWindow(str, Enum):
    season = "season"
    last10 = "last10"
    last5 = "last5"


class PositionGroup(str, Enum):
    guards = "Guards"
    forwards = "Forwards"
    centers = "Centers"


class MatchupTier(str, Enum):
    green = "green"
    yellow = "yellow"
    orange = "orange"
    red = "red"


class Game(BaseModel):
    game_id: str
    start_time_utc: Optional[str] = None
    away_team: str
    home_team: str


class InjuryTag(BaseModel):
    player_name: str
    team: str
    status: str
    comment: Optional[str] = None
    source: str = "nba-cdn"
    updated_at: Optional[datetime] = None


class PlayerMatchup(BaseModel):
    player_id: int
    player_name: str
    team: str
    opponent: str
    position_group: PositionGroup
    avg_minutes: float
    injury_status: Optional[str] = None
    environment_score: float
    stat_ranks: Dict[str, int] = Field(default_factory=dict)
    stat_tiers: Dict[str, MatchupTier] = Field(default_factory=dict)


class MatchupResponse(BaseModel):
    slate_date: date
    as_of_date: date
    window: Window
    games: List[Game]
    injuries: List[InjuryTag]
    players: List[PlayerMatchup]


class GameLine(BaseModel):
    game_id: str
    away_team: str
    home_team: str
    away_spread: Optional[float] = None
    home_spread: Optional[float] = None
    game_total: Optional[float] = None
    source: str = "mcp"


class GameLinesResponse(BaseModel):
    slate_date: date
    lines: List[GameLine]


class MetaResponse(BaseModel):
    season_label: str
    current_date_et: date
    season_start: date
    season_end: date


class RefreshResponse(BaseModel):
    slate_date: date
    cleared_keys: int
    recomputed: bool


class PlayerCardResponse(BaseModel):
    player_id: int
    player_name: str
    team: str
    season: str
    as_of_date: date
    window: PlayerCardWindow = PlayerCardWindow.season
    position_group: PositionGroup
    mpg: float
    ppg: float
    assists_pg: float
    rebounds_pg: float
    steals_pg: float
    blocks_pg: float
    three_pa_pg: float
    three_pm_pg: float
    fta_pg: float
    ftm_pg: float
    fg_pct: float
    three_p_pct: float
    ft_pct: float
    turnovers_pg: float
    plus_minus_pg: float

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.models import (
    GameLinesResponse,
    MatchupResponse,
    MetaResponse,
    PlayerCardResponse,
    PlayerCardWindow,
    RefreshResponse,
    Window,
)
from app.services.matchup_service import MatchupService
from app.utils import current_et_date

router = APIRouter(prefix="/api", tags=["matchups"])


def get_matchup_service(request: Request) -> MatchupService:
    return request.app.state.matchup_service


@router.get("/meta", response_model=MetaResponse)
def get_meta(service: MatchupService = Depends(get_matchup_service)) -> MetaResponse:
    return MetaResponse(**service.get_meta())


@router.get("/matchups", response_model=MatchupResponse)
async def get_matchups(
    service: MatchupService = Depends(get_matchup_service),
    date_param: Optional[date] = Query(default=None, alias="date"),
    window: Window = Query(default=Window.season),
) -> MatchupResponse:
    try:
        target_date = date_param or current_et_date()
        return await service.get_matchups(
            slate_date=target_date,
            window=window,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to compute matchups: {exc}") from exc


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    service: MatchupService = Depends(get_matchup_service),
    date_param: date = Query(alias="date"),
    recompute: bool = Query(default=False),
) -> RefreshResponse:
    try:
        return await service.refresh(slate_date=date_param, recompute=recompute)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to refresh: {exc}") from exc


@router.get("/player-card", response_model=PlayerCardResponse)
async def get_player_card(
    service: MatchupService = Depends(get_matchup_service),
    player_id: int = Query(alias="player_id"),
    date_param: Optional[date] = Query(default=None, alias="date"),
    window: PlayerCardWindow = Query(default=PlayerCardWindow.season),
) -> PlayerCardResponse:
    try:
        card = await service.get_player_card(player_id=player_id, slate_date=date_param, window=window)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch player card: {exc}") from exc

    if card is None:
        raise HTTPException(status_code=404, detail="Player card not found for selected date.")
    return card


@router.get("/game-lines", response_model=GameLinesResponse)
async def get_game_lines(
    service: MatchupService = Depends(get_matchup_service),
    date_param: Optional[date] = Query(default=None, alias="date"),
) -> GameLinesResponse:
    try:
        target_date = date_param or current_et_date()
        return await service.get_game_lines(slate_date=target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch game lines: {exc}") from exc


@router.get("/game-lines-debug")
async def get_game_lines_debug(
    service: MatchupService = Depends(get_matchup_service),
    limit: int = Query(default=15, ge=1, le=50),
) -> dict:
    try:
        return await service.sports_mcp_service.fetch_event_diagnostics(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch game line diagnostics: {exc}") from exc


@router.get("/injuries-debug")
async def get_injuries_debug(
    service: MatchupService = Depends(get_matchup_service),
    date_param: Optional[date] = Query(default=None, alias="date"),
) -> dict:
    try:
        target_date = date_param or current_et_date()
        return await service.injury_service.fetch_injuries_debug(target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch injury diagnostics: {exc}") from exc

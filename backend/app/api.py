from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.models import MatchupResponse, MetaResponse, PlayerCardResponse, RefreshResponse, Window
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
) -> PlayerCardResponse:
    try:
        card = await service.get_player_card(player_id=player_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch player card: {exc}") from exc

    if card is None:
        raise HTTPException(status_code=404, detail="Player card not found for selected date.")
    return card

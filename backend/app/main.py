from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from pathlib import Path

from app.api import router
from app.core.config import get_settings
from app.services.cache import InMemoryCache
from app.services.injury_service import InjuryService
from app.services.matchup_service import MatchupService
from app.services.nba_client import NBADataService
from app.services.odds_api_service import OddsAPIService
from app.services.snapshot_store import SnapshotStore
from app.services.sports_mcp_service import SportsMCPService


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.api_title, version=settings.api_version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    nba_service = NBADataService(enable_roster_fetch=_env_bool("ENABLE_ROSTER_FETCH", True))
    injury_service = InjuryService()
    snapshot_db_path = Path(
        os.getenv(
            "MATCHUP_DB_PATH",
            str(Path(__file__).resolve().parents[1] / ".data" / "matchup_snapshots.db"),
        )
    )
    database_url = os.getenv("DATABASE_URL")
    snapshot_store = SnapshotStore(
        database_url=database_url,
        db_path=str(snapshot_db_path) if not database_url else None,
    )
    snapshot_store.initialize()
    cache_path = Path(__file__).resolve().parents[1] / ".cache" / "app_cache.pkl"
    cache = InMemoryCache(ttl_minutes=360, persist_path=str(cache_path))
    sports_mcp_service = SportsMCPService()
    odds_api_service = OddsAPIService()
    app.state.matchup_service = MatchupService(
        nba_service=nba_service,
        injury_service=injury_service,
        cache=cache,
        snapshot_store=snapshot_store,
        sports_mcp_service=sports_mcp_service,
        odds_api_service=odds_api_service,
    )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(router)
    return app


app = create_app()

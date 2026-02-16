from __future__ import annotations

from datetime import date
import logging
from time import perf_counter
from typing import Dict, List

from app.models import (
    MatchupResponse,
    PlayerCardResponse,
    PlayerMatchup,
    RefreshResponse,
    Window,
)
from app.services.cache import InMemoryCache
from app.services.injury_service import InjuryService
from app.services.nba_client import NBADataService
from app.services.snapshot_store import SnapshotStore
from app.utils import (
    DISPLAY_STATS,
    SUPPORTED_STATS,
    as_of_date_for_slate,
    current_et_date,
    season_bounds_for_label,
    season_label_for_date,
    to_tier,
)


class MatchupService:
    def __init__(
        self,
        nba_service: NBADataService,
        injury_service: InjuryService,
        cache: InMemoryCache,
        snapshot_store: SnapshotStore,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self.nba_service = nba_service
        self.injury_service = injury_service
        self.cache = cache
        self.snapshot_store = snapshot_store

    async def get_matchups(
        self,
        slate_date: date,
        window: Window,
    ) -> MatchupResponse:
        window_key = window.value
        base_cache_key = f"matchups:{slate_date.isoformat()}:{window_key}"
        base_response = self.cache.get(base_cache_key)

        if base_response is None:
            base_response = self.snapshot_store.get(slate_date=slate_date, window=window)
            if base_response is not None:
                self.cache.set(base_cache_key, base_response)
        if base_response is None:
            base_response = await self._compute_matchups(slate_date=slate_date, window=window)
            try:
                self.snapshot_store.upsert(base_response)
            except Exception as exc:
                self._logger.warning(
                    "Failed to persist snapshot for %s window=%s: %s",
                    slate_date.isoformat(),
                    window.value,
                    exc,
                )
            self.cache.set(base_cache_key, base_response)

        return MatchupResponse(
            slate_date=base_response.slate_date,
            as_of_date=base_response.as_of_date,
            window=base_response.window,
            games=base_response.games,
            injuries=base_response.injuries,
            players=base_response.players,
        )

    async def refresh(self, slate_date: date, recompute: bool) -> RefreshResponse:
        date_key = slate_date.isoformat()
        cleared = 0
        cleared += self.cache.invalidate_prefix(f"matchups:{date_key}:")
        cleared += self.snapshot_store.delete_slate(slate_date)

        as_of_date = as_of_date_for_slate(slate_date)
        season = season_label_for_date(slate_date)
        snapshot_key = f"snapshot:{season}:{as_of_date.isoformat()}"
        cleared += self.cache.invalidate_prefix(snapshot_key)

        if recompute:
            await self.get_matchups(slate_date=slate_date, window=Window.season)
            await self.get_matchups(slate_date=slate_date, window=Window.last10)

        return RefreshResponse(slate_date=slate_date, cleared_keys=cleared, recomputed=recompute)

    def get_meta(self) -> dict:
        today = current_et_date()
        season_label = season_label_for_date(today)
        season_start, season_end = season_bounds_for_label(season_label)
        return {
            "season_label": season_label,
            "current_date_et": today,
            "season_start": season_start,
            "season_end": season_end,
        }

    async def get_player_card(self, player_id: int) -> PlayerCardResponse | None:
        card = self.snapshot_store.get_latest_player_card(player_id=player_id)
        if card is not None:
            return card

        # Best-effort population on cold start.
        await self.get_matchups(slate_date=current_et_date(), window=Window.season)
        return self.snapshot_store.get_latest_player_card(player_id=player_id)

    async def _compute_matchups(self, slate_date: date, window: Window) -> MatchupResponse:
        started = perf_counter()
        games = self.nba_service.fetch_slate_games(slate_date)
        scoreboard_elapsed = perf_counter() - started
        try:
            injuries = await self.injury_service.fetch_injuries(slate_date)
        except Exception as exc:
            self._logger.warning("Injury fetch failed for %s: %s", slate_date.isoformat(), exc)
            injuries = []
        injury_elapsed = perf_counter() - started

        opponent_map: Dict[str, str] = {}
        slate_teams: set[str] = set()
        for game in games:
            opponent_map[game.away_team] = game.home_team
            opponent_map[game.home_team] = game.away_team
            slate_teams.add(game.away_team)
            slate_teams.add(game.home_team)

        as_of_date = as_of_date_for_slate(slate_date)
        season = season_label_for_date(slate_date)
        team_token = ",".join(sorted(slate_teams)) if slate_teams else "none"

        snapshot_cache_key = f"snapshot:{season}:{as_of_date.isoformat()}:{team_token}"
        snapshot = self.cache.get(snapshot_cache_key)
        if snapshot is None:
            snapshot_start = perf_counter()
            try:
                snapshot = self.nba_service.build_snapshot(
                    as_of_date=as_of_date,
                    season=season,
                    slate_teams=slate_teams,
                )
            except Exception as exc:
                self._logger.warning(
                    "Snapshot build failed for season=%s as_of=%s: %s",
                    season,
                    as_of_date.isoformat(),
                    exc,
                )
                snapshot = {
                    "rotation_pool": [],
                    "season": {"ranks": {}, "allowed": {}, "environment": {}},
                    "last10": {"ranks": {}, "allowed": {}, "environment": {}},
                }
            self.cache.set(snapshot_cache_key, snapshot)
            self._logger.info(
                "Snapshot built for %s %s in %.2fs (teams=%d)",
                season,
                as_of_date.isoformat(),
                perf_counter() - snapshot_start,
                len(slate_teams),
            )

        window_payload = snapshot[window.value]
        ranks = window_payload["ranks"]
        allowed = window_payload["allowed"]
        environment = window_payload["environment"]

        injury_lookup: Dict[tuple[str, str], str] = {}
        for injury in injuries:
            injury_lookup[(injury.team, injury.player_name.upper())] = injury.status

        players: List[PlayerMatchup] = []
        for player in snapshot["rotation_pool"]:
            team = player["team"]
            if team not in slate_teams:
                continue

            opponent = opponent_map.get(team)
            if not opponent:
                continue

            group = player["position_group"]
            stat_ranks: Dict[str, int] = {}
            stat_allowed: Dict[str, float] = {}
            stat_tiers = {}

            for stat_key in SUPPORTED_STATS:
                display_stat = DISPLAY_STATS[stat_key]
                rank = int(ranks.get(opponent, {}).get(group, {}).get(stat_key, 30))
                value = float(allowed.get(opponent, {}).get(group, {}).get(stat_key, 0.0))
                stat_ranks[display_stat] = rank
                stat_allowed[display_stat] = round(value, 3)
                stat_tiers[display_stat] = to_tier(rank)

            players.append(
                PlayerMatchup(
                    player_id=int(player["player_id"]),
                    player_name=player["player_name"],
                    team=team,
                    opponent=opponent,
                    position_group=group,
                    avg_minutes=float(player["avg_minutes"]),
                    injury_status=injury_lookup.get((team, player["player_name"].upper())),
                    environment_score=float(environment.get(opponent, 50.0)),
                    stat_ranks=stat_ranks,
                    stat_allowed=stat_allowed,
                    stat_tiers=stat_tiers,
                )
            )

        players.sort(
            key=lambda player: (
                min(player.stat_ranks.values()) if player.stat_ranks else 30,
                -player.environment_score,
                player.player_name,
            )
        )

        self._logger.info(
            "Computed matchups for %s window=%s in %.2fs (scoreboard=%.2fs injuries=%.2fs players=%d)",
            slate_date.isoformat(),
            window.value,
            perf_counter() - started,
            scoreboard_elapsed,
            injury_elapsed - scoreboard_elapsed,
            len(players),
        )

        player_cards = snapshot.get("player_cards", [])
        if player_cards:
            try:
                stored = self.snapshot_store.upsert_player_cards(player_cards)
                self._logger.info(
                    "Upserted %d player cards for season=%s as_of=%s",
                    stored,
                    season,
                    as_of_date.isoformat(),
                )
            except Exception as exc:
                self._logger.warning(
                    "Failed to upsert player cards for season=%s as_of=%s: %s",
                    season,
                    as_of_date.isoformat(),
                    exc,
                )

        return MatchupResponse(
            slate_date=slate_date,
            as_of_date=as_of_date,
            window=window,
            games=games,
            injuries=injuries,
            players=players,
        )

from __future__ import annotations

from datetime import date
import logging
from time import perf_counter
from typing import Dict, List

from app.models import (
    GameLinesResponse,
    MatchupResponse,
    PlayerCardWindow,
    PlayerCardResponse,
    PlayerMatchup,
    RefreshResponse,
    Window,
)
from app.services.cache import InMemoryCache
from app.services.injury_service import InjuryService
from app.services.nba_client import NBADataService
from app.services.odds_api_service import OddsAPIService
from app.services.snapshot_store import SnapshotStore
from app.services.sports_mcp_service import SportsMCPService
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
        sports_mcp_service: SportsMCPService | None = None,
        odds_api_service: OddsAPIService | None = None,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self.nba_service = nba_service
        self.injury_service = injury_service
        self.cache = cache
        self.snapshot_store = snapshot_store
        self.sports_mcp_service = sports_mcp_service or SportsMCPService()
        self.odds_api_service = odds_api_service or OddsAPIService()

    async def get_matchups(
        self,
        slate_date: date,
        window: Window,
    ) -> MatchupResponse:
        window_key = window.value
        base_cache_key = f"matchups:{slate_date.isoformat()}:{window_key}"
        base_response = self.cache.get(base_cache_key)
        expected_as_of = as_of_date_for_slate(slate_date)

        if base_response is None:
            base_response = self.snapshot_store.get(slate_date=slate_date, window=window)
            if base_response is not None:
                self.cache.set(base_cache_key, base_response)
        if base_response is not None and base_response.as_of_date < expected_as_of:
            self._logger.info(
                "Ignoring stale snapshot for %s window=%s (as_of=%s expected>=%s)",
                slate_date.isoformat(),
                window.value,
                base_response.as_of_date.isoformat(),
                expected_as_of.isoformat(),
            )
            base_response = None

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

        try:
            live_injuries = await self.injury_service.fetch_injuries(slate_date)
        except Exception as exc:
            self._logger.warning("Live injury overlay failed for %s: %s", slate_date.isoformat(), exc)
            live_injuries = base_response.injuries

        return self._with_injury_overlay(base_response=base_response, injuries=live_injuries)

    def _with_injury_overlay(self, base_response: MatchupResponse, injuries: List) -> MatchupResponse:
        injury_lookup_by_team_name: Dict[tuple[str, str], str] = {}
        injury_lookup_by_name: Dict[str, str] = {}
        for injury in injuries:
            normalized_name = injury.player_name.upper()
            injury_lookup_by_team_name[(injury.team.upper(), normalized_name)] = injury.status
            injury_lookup_by_name[normalized_name] = injury.status

        players: List[PlayerMatchup] = []
        for player in base_response.players:
            normalized_name = player.player_name.upper()
            status = injury_lookup_by_team_name.get((player.team.upper(), normalized_name))
            if status is None:
                status = injury_lookup_by_name.get(normalized_name)
            players.append(
                PlayerMatchup(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    team=player.team,
                    opponent=player.opponent,
                    position_group=player.position_group,
                    avg_minutes=player.avg_minutes,
                    injury_status=status,
                    environment_score=player.environment_score,
                    stat_ranks=player.stat_ranks,
                    stat_tiers=player.stat_tiers,
                )
            )

        return MatchupResponse(
            slate_date=base_response.slate_date,
            as_of_date=base_response.as_of_date,
            window=base_response.window,
            games=base_response.games,
            injuries=injuries,
            players=players,
        )

    async def refresh(self, slate_date: date, recompute: bool) -> RefreshResponse:
        date_key = slate_date.isoformat()
        cleared = 0
        existing_season = self.snapshot_store.get(slate_date=slate_date, window=Window.season)
        existing_last10 = self.snapshot_store.get(slate_date=slate_date, window=Window.last10)

        cleared += self.cache.invalidate_prefix(f"matchups:{date_key}:")
        as_of_date = as_of_date_for_slate(slate_date)
        season = season_label_for_date(slate_date)
        snapshot_key = f"snapshot:{season}:{as_of_date.isoformat()}"
        cleared += self.cache.invalidate_prefix(snapshot_key)

        if recompute:
            season_response = await self._compute_matchups(slate_date=slate_date, window=Window.season)
            last10_response = await self._compute_matchups(slate_date=slate_date, window=Window.last10)

            if existing_season is not None and not season_response.games and existing_season.games:
                self._logger.warning(
                    "Recompute produced empty season slate for %s; preserving existing snapshot.",
                    slate_date.isoformat(),
                )
                season_response = existing_season
            if existing_last10 is not None and not last10_response.games and existing_last10.games:
                self._logger.warning(
                    "Recompute produced empty last10 slate for %s; preserving existing snapshot.",
                    slate_date.isoformat(),
                )
                last10_response = existing_last10

            self.snapshot_store.upsert(season_response)
            self.snapshot_store.upsert(last10_response)
            self.cache.set(f"matchups:{date_key}:{Window.season.value}", season_response)
            self.cache.set(f"matchups:{date_key}:{Window.last10.value}", last10_response)
        else:
            cleared += self.snapshot_store.delete_slate(slate_date)

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

    async def get_player_card(
        self,
        player_id: int,
        slate_date: date | None = None,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> PlayerCardResponse | None:
        as_of_date = slate_date or current_et_date()
        if window == PlayerCardWindow.season:
            if slate_date is not None:
                card = self.snapshot_store.get_player_card_as_of(
                    player_id=player_id,
                    as_of_date=slate_date,
                    window=window,
                )
            else:
                card = self.snapshot_store.get_latest_player_card(player_id=player_id, window=window)
            if card is not None:
                return card

        # Fast path for missing non-season windows: backfill from locally cached player logs only.
        season_card = self.snapshot_store.get_player_card_as_of(
            player_id=player_id,
            as_of_date=as_of_date,
            window=PlayerCardWindow.season,
        )
        if season_card is not None:
            season = season_label_for_date(as_of_date)
            cards = self.nba_service.build_player_card_windows_for_player(
                player_id=player_id,
                as_of_date=as_of_date_for_slate(as_of_date),
                season=season,
                fallback_team=season_card.team,
                fallback_position=season_card.position_group,
            )
            if cards:
                try:
                    self.snapshot_store.upsert_player_cards(cards)
                except Exception as exc:
                    self._logger.warning(
                        "Failed upserting windowed player cards for player_id=%s as_of=%s: %s",
                        player_id,
                        as_of_date.isoformat(),
                        exc,
                    )
            if slate_date is not None:
                card = self.snapshot_store.get_player_card_as_of(
                    player_id=player_id,
                    as_of_date=slate_date,
                    window=window,
                )
            else:
                card = self.snapshot_store.get_latest_player_card(player_id=player_id, window=window)
            if card is not None:
                return card
            # Graceful fallback instead of 404 if we still could not compute window values quickly.
            return season_card

        # Best-effort population on cold start when even season card is missing.
        target_date = as_of_date
        await self._populate_player_cards_for_date(target_date)
        if slate_date is not None:
            return self.snapshot_store.get_player_card_as_of(player_id=player_id, as_of_date=slate_date, window=window)
        return self.snapshot_store.get_latest_player_card(player_id=player_id, window=window)

    async def _populate_player_cards_for_date(self, slate_date: date) -> None:
        try:
            as_of_date = as_of_date_for_slate(slate_date)
            season = season_label_for_date(slate_date)
            games = self.nba_service.fetch_slate_games(slate_date)
            slate_teams = {team for game in games for team in (game.away_team, game.home_team)}
            team_token = ",".join(sorted(slate_teams)) if slate_teams else "none"
            snapshot_cache_key = f"snapshot:{season}:{as_of_date.isoformat()}:{team_token}"

            snapshot = self.cache.get(snapshot_cache_key)
            if snapshot is None:
                try:
                    snapshot = self.nba_service.build_snapshot(
                        as_of_date=as_of_date,
                        season=season,
                        slate_teams=slate_teams,
                    )
                except Exception as exc:
                    self._logger.warning(
                        "Player-card backfill snapshot build failed for %s (season=%s as_of=%s): %s",
                        slate_date.isoformat(),
                        season,
                        as_of_date.isoformat(),
                        exc,
                    )
                    return
                self.cache.set(snapshot_cache_key, snapshot)

            player_cards = snapshot.get("player_cards", [])
            if player_cards:
                try:
                    self.snapshot_store.upsert_player_cards(player_cards)
                except Exception as exc:
                    self._logger.warning(
                        "Player-card backfill upsert failed for %s: %s",
                        slate_date.isoformat(),
                        exc,
                    )
        except Exception as exc:
            self._logger.warning(
                "Player-card backfill failed for %s: %s",
                slate_date.isoformat(),
                exc,
            )

    async def get_game_lines(self, slate_date: date) -> GameLinesResponse:
        cache_key = f"game-lines:{slate_date.isoformat()}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, GameLinesResponse):
            return cached

        games = self.nba_service.fetch_slate_games(slate_date)
        lines = await self.odds_api_service.fetch_game_lines(games)
        has_live_lines = any(
            line.away_spread is not None or line.home_spread is not None or line.game_total is not None
            for line in lines
        )
        if not has_live_lines:
            lines = await self.sports_mcp_service.fetch_game_lines(games)
        response = GameLinesResponse(slate_date=slate_date, lines=lines)
        self.cache.set(cache_key, response)
        return response

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
                    "season": {"ranks": {}, "environment": {}},
                    "last10": {"ranks": {}, "environment": {}},
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
            stat_tiers = {}

            for stat_key in SUPPORTED_STATS:
                display_stat = DISPLAY_STATS[stat_key]
                rank = int(ranks.get(opponent, {}).get(group, {}).get(stat_key, 30))
                stat_ranks[display_stat] = rank
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

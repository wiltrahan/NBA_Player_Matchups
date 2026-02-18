from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import AsyncMock

from app.models import Game, PlayerCardResponse, PositionGroup, Window
from app.services.cache import InMemoryCache
from app.services.matchup_service import MatchupService


class FakeNBADataService:
    def __init__(self) -> None:
        self.build_calls = 0

    def fetch_slate_games(self, slate_date: date) -> list[Game]:
        return [
            Game(
                game_id="001",
                away_team="CHI",
                home_team="BOS",
                start_time_utc=None,
            )
        ]

    def build_snapshot(self, as_of_date: date, season: str, slate_teams: set[str] | None = None) -> dict:
        self.build_calls += 1
        return {
            "rotation_pool": [
                {
                    "player_id": 1,
                    "player_name": "Test Player",
                    "team": "BOS",
                    "avg_minutes": 30.0,
                    "position_group": "Guards",
                }
            ],
            "player_cards": [
                PlayerCardResponse(
                    player_id=1,
                    player_name="Test Player",
                    team="BOS",
                    season=season,
                    as_of_date=as_of_date,
                    position_group=PositionGroup.guards,
                    mpg=30.0,
                    ppg=20.0,
                    assists_pg=6.0,
                    rebounds_pg=5.0,
                    steals_pg=1.2,
                    blocks_pg=0.6,
                    three_pa_pg=7.0,
                    three_pm_pg=2.8,
                    fta_pg=4.5,
                    ftm_pg=3.7,
                    fg_pct=0.49,
                    three_p_pct=0.4,
                    ft_pct=0.82,
                    turnovers_pg=2.1,
                    plus_minus_pg=4.3,
                )
            ],
            "season": {
                "ranks": {"CHI": {"Guards": {"PTS": 5, "REB": 10, "AST": 7, "FG3M": 4, "STL": 11, "BLK": 18}}},
                "environment": {"CHI": 62.3},
            },
            "last10": {
                "ranks": {"CHI": {"Guards": {"PTS": 8, "REB": 11, "AST": 9, "FG3M": 6, "STL": 10, "BLK": 17}}},
                "environment": {"CHI": 58.1},
            },
        }


class FakeInjuryService:
    async def fetch_injuries(self, slate_date: date) -> list:
        return []


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[date, Window], object] = {}
        self.upsert_calls = 0
        self.delete_calls = 0
        self.player_card_upserts = 0
        self.player_cards: dict[tuple[int, str, date], PlayerCardResponse] = {}

    def get(self, slate_date: date, window: Window):
        return self.rows.get((slate_date, window))

    def upsert(self, matchup_response) -> None:
        self.upsert_calls += 1
        self.rows[(matchup_response.slate_date, matchup_response.window)] = matchup_response

    def delete_slate(self, slate_date: date) -> int:
        self.delete_calls += 1
        keys = [key for key in self.rows if key[0] == slate_date]
        for key in keys:
            self.rows.pop(key, None)
        return len(keys)

    def upsert_player_cards(self, cards) -> int:
        count = 0
        for card in cards:
            self.player_cards[(card.player_id, card.season, card.as_of_date)] = card
            count += 1
        self.player_card_upserts += count
        return count

    def get_latest_player_card(self, player_id: int):
        candidates = [
            card
            for (candidate_player_id, candidate_season, candidate_date), card in self.player_cards.items()
            if candidate_player_id == player_id
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda card: (card.as_of_date, card.season),
            reverse=True,
        )[0]


class MatchupServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_matchups_uses_cache_after_first_build(self) -> None:
        nba_service = FakeNBADataService()
        snapshot_store = FakeSnapshotStore()
        service = MatchupService(
            nba_service=nba_service,
            injury_service=FakeInjuryService(),
            cache=InMemoryCache(ttl_minutes=30),
            snapshot_store=snapshot_store,
        )

        slate_date = date(2026, 2, 11)
        first = await service.get_matchups(slate_date=slate_date, window=Window.season)
        second = await service.get_matchups(slate_date=slate_date, window=Window.season)

        self.assertEqual(nba_service.build_calls, 1)
        self.assertEqual(snapshot_store.upsert_calls, 1)
        self.assertEqual(len(first.players), 1)
        self.assertEqual(len(second.players), 1)

    async def test_get_matchups_uses_snapshot_store_before_compute(self) -> None:
        slate_date = date(2026, 2, 11)
        snapshot_store = FakeSnapshotStore()
        prebuilt = await MatchupService(
            nba_service=FakeNBADataService(),
            injury_service=FakeInjuryService(),
            cache=InMemoryCache(ttl_minutes=30),
            snapshot_store=FakeSnapshotStore(),
        )._compute_matchups(slate_date=slate_date, window=Window.season)
        snapshot_store.rows[(slate_date, Window.season)] = prebuilt

        nba_service = FakeNBADataService()
        service = MatchupService(
            nba_service=nba_service,
            injury_service=FakeInjuryService(),
            cache=InMemoryCache(ttl_minutes=30),
            snapshot_store=snapshot_store,
        )

        loaded = await service.get_matchups(slate_date=slate_date, window=Window.season)
        self.assertEqual(nba_service.build_calls, 0)
        self.assertEqual(len(loaded.players), 1)

    async def test_refresh_without_recompute_does_not_trigger_get_matchups(self) -> None:
        nba_service = FakeNBADataService()
        cache = InMemoryCache(ttl_minutes=30)
        snapshot_store = FakeSnapshotStore()
        service = MatchupService(
            nba_service=nba_service,
            injury_service=FakeInjuryService(),
            cache=cache,
            snapshot_store=snapshot_store,
        )

        slate_date = date(2026, 2, 11)
        as_of = date(2026, 2, 10)
        cache.set("matchups:2026-02-11:season", {"x": 1})
        cache.set("snapshot:2025-26:2026-02-10:season:BOS,CHI", {"x": 1})
        snapshot_store.rows[(slate_date, Window.season)] = {"x": 1}

        service.get_matchups = AsyncMock()  # type: ignore[method-assign]
        response = await service.refresh(slate_date=slate_date, recompute=False)

        self.assertGreaterEqual(response.cleared_keys, 2)
        self.assertEqual(snapshot_store.delete_calls, 1)
        service.get_matchups.assert_not_called()

    async def test_refresh_with_recompute_builds_both_windows(self) -> None:
        snapshot_store = FakeSnapshotStore()
        service = MatchupService(
            nba_service=FakeNBADataService(),
            injury_service=FakeInjuryService(),
            cache=InMemoryCache(ttl_minutes=30),
            snapshot_store=snapshot_store,
        )

        service.get_matchups = AsyncMock()  # type: ignore[method-assign]
        await service.refresh(slate_date=date(2026, 2, 11), recompute=True)

        self.assertEqual(service.get_matchups.await_count, 2)
        awaited = service.get_matchups.await_args_list
        self.assertEqual(awaited[0].kwargs["window"], Window.season)
        self.assertEqual(awaited[1].kwargs["window"], Window.last10)

    async def test_get_player_card_populates_when_missing(self) -> None:
        snapshot_store = FakeSnapshotStore()
        service = MatchupService(
            nba_service=FakeNBADataService(),
            injury_service=FakeInjuryService(),
            cache=InMemoryCache(ttl_minutes=30),
            snapshot_store=snapshot_store,
        )

        loaded = await service.get_player_card(player_id=1)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.player_id, 1)
        self.assertEqual(loaded.team, "BOS")
        self.assertGreater(snapshot_store.player_card_upserts, 0)


if __name__ == "__main__":
    unittest.main()

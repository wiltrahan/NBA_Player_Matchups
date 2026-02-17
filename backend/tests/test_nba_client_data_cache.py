from __future__ import annotations

from datetime import date
import unittest

import pandas as pd

from app.models import PositionGroup
from app.services.nba_client import NBADataService


class NBAClientDataCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = NBADataService(enable_roster_fetch=False)

    def test_filter_logs_by_as_of(self) -> None:
        frame = pd.DataFrame(
            [
                {"PLAYER_ID": 1, "GAME_DATE": "2026-02-07", "MIN": 20},
                {"PLAYER_ID": 1, "GAME_DATE": "2026-02-10", "MIN": 25},
                {"PLAYER_ID": 1, "GAME_DATE": "2026-02-12", "MIN": 30},
            ]
        )
        filtered = self.client._filter_logs_by_as_of(frame, as_of_date=date(2026, 2, 10))
        self.assertEqual(len(filtered), 2)

    def test_build_player_baselines_from_logs_uses_latest_team_and_avg_minutes(self) -> None:
        logs = pd.DataFrame(
            [
                {
                    "PLAYER_ID": 1,
                    "PLAYER_NAME": "Player One",
                    "TEAM_ABBREVIATION": "CHI",
                    "GAME_DATE": "2026-02-07",
                    "MIN": 20,
                    "AST": 6,
                    "REB": 4,
                },
                {
                    "PLAYER_ID": 1,
                    "PLAYER_NAME": "Player One",
                    "TEAM_ABBREVIATION": "BOS",
                    "GAME_DATE": "2026-02-10",
                    "MIN": 30,
                    "AST": 8,
                    "REB": 5,
                },
                {
                    "PLAYER_ID": 2,
                    "PLAYER_NAME": "Player Two",
                    "TEAM_ABBREVIATION": "LAL",
                    "GAME_DATE": "2026-02-10",
                    "MIN": 10,
                    "AST": 2,
                    "REB": 9,
                },
            ]
        )

        baselines = self.client._build_player_baselines_from_logs(logs)
        self.assertEqual(len(baselines), 2)

        player_one = baselines[baselines["PLAYER_ID"] == 1].iloc[0]
        self.assertEqual(player_one["TEAM_ABBREVIATION"], "BOS")
        self.assertAlmostEqual(float(player_one["MIN"]), 25.0)
        self.assertAlmostEqual(float(player_one["AST"]), 7.0)
        self.assertAlmostEqual(float(player_one["REB"]), 4.5)

    def test_extract_max_game_date(self) -> None:
        logs = pd.DataFrame(
            [
                {"GAME_DATE": "2026-02-07"},
                {"GAME_DATE": "2026-02-10"},
                {"GAME_DATE": "2026-02-09"},
            ]
        )
        max_date = self.client._extract_max_game_date(logs)
        self.assertEqual(max_date, date(2026, 2, 10))

    def test_build_games_from_team_logs(self) -> None:
        team_logs = pd.DataFrame(
            [
                {
                    "GAME_ID": "001",
                    "TEAM_ABBREVIATION": "CHI",
                    "MATCHUP": "CHI @ BOS",
                    "GAME_DATE": "2026-02-11",
                },
                {
                    "GAME_ID": "001",
                    "TEAM_ABBREVIATION": "BOS",
                    "MATCHUP": "BOS vs. CHI",
                    "GAME_DATE": "2026-02-11",
                },
                {
                    "GAME_ID": "002",
                    "TEAM_ABBREVIATION": "NYK",
                    "MATCHUP": "NYK @ PHI",
                    "GAME_DATE": "2026-02-11",
                },
                {
                    "GAME_ID": "002",
                    "TEAM_ABBREVIATION": "PHI",
                    "MATCHUP": "PHI vs. NYK",
                    "GAME_DATE": "2026-02-11",
                },
            ]
        )
        games = self.client._build_games_from_team_logs(team_logs, slate_date=date(2026, 2, 11))
        self.assertEqual(len(games), 2)
        by_id = {game.game_id: game for game in games}
        self.assertEqual(by_id["001"].away_team, "CHI")
        self.assertEqual(by_id["001"].home_team, "BOS")
        self.assertEqual(by_id["002"].away_team, "NYK")
        self.assertEqual(by_id["002"].home_team, "PHI")

    def test_dedupe_games_by_matchup(self) -> None:
        games = [
            self.client._build_games_from_team_logs(
                pd.DataFrame(
                    [
                        {
                            "GAME_ID": "003",
                            "TEAM_ABBREVIATION": "BOS",
                            "MATCHUP": "BOS @ LAL",
                            "GAME_DATE": "2026-02-22",
                        },
                        {
                            "GAME_ID": "003",
                            "TEAM_ABBREVIATION": "LAL",
                            "MATCHUP": "LAL vs. BOS",
                            "GAME_DATE": "2026-02-22",
                        },
                    ]
                ),
                slate_date=date(2026, 2, 22),
            )[0],
            self.client._build_games_from_team_logs(
                pd.DataFrame(
                    [
                        {
                            "GAME_ID": "123",
                            "TEAM_ABBREVIATION": "BOS",
                            "MATCHUP": "BOS @ LAL",
                            "GAME_DATE": "2026-02-22",
                        },
                        {
                            "GAME_ID": "123",
                            "TEAM_ABBREVIATION": "LAL",
                            "MATCHUP": "LAL vs. BOS",
                            "GAME_DATE": "2026-02-22",
                        },
                    ]
                ),
                slate_date=date(2026, 2, 22),
            )[0],
        ]

        deduped = NBADataService._dedupe_games_by_matchup(games)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].away_team, "BOS")
        self.assertEqual(deduped[0].home_team, "LAL")

    def test_build_rotation_pool_filters_to_team_roster_ids(self) -> None:
        baselines = pd.DataFrame(
            [
                {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "BOS", "MIN": 22.0, "AST": 5, "REB": 4},
                {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "BOS", "MIN": 24.0, "AST": 3, "REB": 8},
                {"PLAYER_ID": 3, "PLAYER_NAME": "C", "TEAM_ABBREVIATION": "CHI", "MIN": 26.0, "AST": 2, "REB": 9},
            ]
        )
        rotation_pool, player_positions = self.client._build_rotation_pool(
            baselines_df=baselines,
            player_minutes={1: 22.0, 2: 24.0, 3: 26.0},
            roster_positions={
                1: [PositionGroup.guards],
                2: [PositionGroup.forwards],
                3: [PositionGroup.centers],
            },
            team_roster_player_ids={
                "BOS": {1},
                "CHI": {3},
            },
            team_filter={"BOS", "CHI"},
        )
        ids = sorted({int(row["player_id"]) for row in rotation_pool})
        self.assertEqual(ids, [1, 3])
        self.assertEqual(sorted(player_positions.keys()), [1, 3])

    def test_build_rotation_pool_keeps_team_when_roster_ids_unavailable(self) -> None:
        baselines = pd.DataFrame(
            [
                {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "BOS", "MIN": 22.0, "AST": 5, "REB": 4},
                {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "BOS", "MIN": 24.0, "AST": 3, "REB": 8},
            ]
        )
        rotation_pool, _ = self.client._build_rotation_pool(
            baselines_df=baselines,
            player_minutes={1: 22.0, 2: 24.0},
            roster_positions={
                1: [PositionGroup.guards],
                2: [PositionGroup.forwards],
            },
            team_roster_player_ids={},
            team_filter={"BOS"},
        )
        ids = sorted({int(row["player_id"]) for row in rotation_pool})
        self.assertEqual(ids, [1, 2])

    def test_build_player_cards_filters_to_team_roster_ids(self) -> None:
        baselines = pd.DataFrame(
            [
                {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "BOS", "MIN": 22.0, "PTS": 12.0},
                {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "BOS", "MIN": 24.0, "PTS": 14.0},
            ]
        )
        cards = self.client._build_player_cards(
            baselines_df=baselines,
            player_positions={1: [PositionGroup.guards], 2: [PositionGroup.forwards]},
            team_roster_player_ids={"BOS": {1}},
            as_of_date=date(2026, 2, 11),
            season="2025-26",
            team_filter={"BOS"},
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].player_id, 1)


if __name__ == "__main__":
    unittest.main()

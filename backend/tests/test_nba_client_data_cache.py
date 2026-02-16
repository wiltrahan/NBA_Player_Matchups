from __future__ import annotations

from datetime import date
import unittest

import pandas as pd

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


if __name__ == "__main__":
    unittest.main()

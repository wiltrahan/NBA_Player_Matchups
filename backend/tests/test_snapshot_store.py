from __future__ import annotations

from datetime import date
import tempfile
import unittest
from pathlib import Path

from app.models import (
    Game,
    MatchupResponse,
    MatchupTier,
    PlayerCardResponse,
    PlayerMatchup,
    PositionGroup,
    Window,
)
from app.services.snapshot_store import SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def test_upsert_get_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "snapshots.db"
            store = SnapshotStore(db_path=str(db_path))
            store.initialize()

            response = MatchupResponse(
                slate_date=date(2026, 2, 11),
                as_of_date=date(2026, 2, 10),
                window=Window.season,
                games=[Game(game_id="1", away_team="CHI", home_team="BOS")],
                injuries=[],
                players=[
                    PlayerMatchup(
                        player_id=1,
                        player_name="Test Player",
                        team="BOS",
                        opponent="CHI",
                        position_group=PositionGroup.guards,
                        avg_minutes=31.2,
                        environment_score=62.3,
                        stat_ranks={"PTS": 5},
                        stat_tiers={"PTS": MatchupTier.green},
                    )
                ],
            )

            store.upsert(response)
            loaded = store.get(slate_date=date(2026, 2, 11), window=Window.season)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.players[0].player_name, "Test Player")

            # Ensure upsert replaces same key.
            response.players[0].player_name = "Updated Name"
            store.upsert(response)
            loaded_again = store.get(slate_date=date(2026, 2, 11), window=Window.season)
            assert loaded_again is not None
            self.assertEqual(loaded_again.players[0].player_name, "Updated Name")

            removed = store.delete_slate(date(2026, 2, 11))
            self.assertEqual(removed, 1)
            self.assertIsNone(store.get(slate_date=date(2026, 2, 11), window=Window.season))

    def test_player_card_upsert_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "snapshots.db"
            store = SnapshotStore(db_path=str(db_path))
            store.initialize()

            card = PlayerCardResponse(
                player_id=1,
                player_name="Test Player",
                team="BOS",
                season="2025-26",
                as_of_date=date(2026, 2, 10),
                position_group=PositionGroup.guards,
                mpg=30.5,
                ppg=20.1,
                assists_pg=6.2,
                rebounds_pg=4.8,
                steals_pg=1.1,
                blocks_pg=0.4,
                three_pa_pg=7.5,
                three_pm_pg=2.9,
                fta_pg=5.0,
                ftm_pg=4.2,
                fg_pct=0.478,
                three_p_pct=0.387,
                ft_pct=0.84,
                turnovers_pg=2.3,
                plus_minus_pg=5.2,
            )

            stored = store.upsert_player_cards([card])
            self.assertEqual(stored, 1)

            loaded = store.get_latest_player_card(player_id=1)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertAlmostEqual(loaded.ppg, 20.1)
            self.assertEqual(loaded.team, "BOS")


if __name__ == "__main__":
    unittest.main()

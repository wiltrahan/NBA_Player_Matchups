from __future__ import annotations

import unittest

from app.models import PositionGroup
from app.services.nba_client import NBADataService


class NBAClientPositionInferenceTests(unittest.TestCase):
    def test_infers_guard_from_height_inches(self) -> None:
        groups = NBADataService._infer_position_groups(76, None, None, None)
        self.assertEqual(groups, [PositionGroup.guards])

    def test_infers_forward_from_height_inches(self) -> None:
        groups = NBADataService._infer_position_groups(80, None, None, None)
        self.assertEqual(groups, [PositionGroup.forwards])

    def test_infers_center_from_height_inches(self) -> None:
        groups = NBADataService._infer_position_groups(83, None, None, None)
        self.assertEqual(groups, [PositionGroup.centers])

    def test_infers_from_height_text(self) -> None:
        groups = NBADataService._infer_position_groups(None, "6-11", None, None)
        self.assertEqual(groups, [PositionGroup.centers])

    def test_falls_back_to_ast_profile(self) -> None:
        groups = NBADataService._infer_position_groups(None, None, 7.1, 3.2)
        self.assertEqual(groups, [PositionGroup.guards])

    def test_falls_back_to_reb_profile(self) -> None:
        groups = NBADataService._infer_position_groups(None, None, 1.8, 9.4)
        self.assertEqual(groups, [PositionGroup.centers])

    def test_unknown_profile_returns_empty(self) -> None:
        groups = NBADataService._infer_position_groups(None, None, None, None)
        self.assertEqual(groups, [])


if __name__ == "__main__":
    unittest.main()

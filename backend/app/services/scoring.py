from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Tuple

from app.models import PositionGroup
from app.utils import SUPPORTED_STATS, normalize_score

TeamGroupStat = Dict[str, Dict[PositionGroup, Dict[str, float]]]
TeamGroupRank = Dict[str, Dict[PositionGroup, Dict[str, int]]]


def build_rank_tables(
    team_group_stats: TeamGroupStat,
    teams: Iterable[str],
) -> TeamGroupRank:
    ranks: TeamGroupRank = defaultdict(lambda: defaultdict(dict))

    groups = [PositionGroup.guards, PositionGroup.forwards, PositionGroup.centers]

    for group in groups:
        for stat in SUPPORTED_STATS:
            values: list[Tuple[str, float]] = []
            for team in teams:
                value = team_group_stats.get(team, {}).get(group, {}).get(stat, 0.0)
                values.append((team, value))

            values.sort(key=lambda item: item[1], reverse=True)
            for index, (team, _) in enumerate(values, start=1):
                ranks[team][group][stat] = index

    return ranks


def build_environment_scores(
    team_metrics: Dict[str, Dict[str, float]],
    teams: Iterable[str],
) -> Dict[str, float]:
    defense_values = [team_metrics.get(team, {}).get("def_rating", 0.0) for team in teams]
    pace_values = [team_metrics.get(team, {}).get("pace", 0.0) for team in teams]

    min_def = min(defense_values) if defense_values else 0.0
    max_def = max(defense_values) if defense_values else 0.0
    min_pace = min(pace_values) if pace_values else 0.0
    max_pace = max(pace_values) if pace_values else 0.0

    scores: Dict[str, float] = {}
    for team in teams:
        metrics = team_metrics.get(team, {})
        def_score = normalize_score(metrics.get("def_rating", 0.0), min_def, max_def)
        pace_score = normalize_score(metrics.get("pace", 0.0), min_pace, max_pace)
        scores[team] = round((0.6 * def_score) + (0.4 * pace_score), 2)

    return scores

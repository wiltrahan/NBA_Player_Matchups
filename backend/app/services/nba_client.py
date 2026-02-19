from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, List

import pandas as pd
from nba_api.stats.endpoints import (
    commonteamroster,
    leaguegamefinder,
    playergamelogs,
    scoreboardv2,
)
from nba_api.stats.static import teams as nba_teams

from app.models import Game, PlayerCardResponse, PositionGroup
from app.services.scoring import build_environment_scores, build_rank_tables
from app.utils import SUPPORTED_STATS, map_position_groups, parse_matchup_opponent, season_label_for_date


class NBADataService:
    def __init__(self, enable_roster_fetch: bool = False) -> None:
        self._logger = logging.getLogger(__name__)
        self._enable_roster_fetch = enable_roster_fetch
        self._scoreboard_timeout_seconds = float(os.getenv("NBA_SCOREBOARD_TIMEOUT_SECONDS", "15"))
        self._scoreboard_retries = max(1, int(os.getenv("NBA_SCOREBOARD_RETRIES", "4")))
        self._fallback_timeout_seconds = float(os.getenv("NBA_FALLBACK_TIMEOUT_SECONDS", "12"))
        self._teams = nba_teams.get_teams()
        self.id_to_abbr = {int(team["id"]): str(team["abbreviation"]).upper() for team in self._teams}
        self.abbr_to_id = {str(team["abbreviation"]).upper(): int(team["id"]) for team in self._teams}
        self.team_abbrs = sorted(self.id_to_abbr.values())
        self._roster_position_cache: dict[tuple[str, int], dict[int, list[PositionGroup]]] = {}
        self._roster_player_ids_cache: dict[tuple[str, int], set[int] | None] = {}
        self._season_player_logs_cache: dict[str, pd.DataFrame] = {}
        self._season_team_logs_cache: dict[str, pd.DataFrame] = {}
        self._raw_data_dir = Path(__file__).resolve().parents[2] / ".data" / "raw"

    def fetch_slate_games(self, slate_date: date) -> List[Game]:
        scoreboard_games = self._fetch_slate_games_from_scoreboard(slate_date)
        if scoreboard_games:
            return self._dedupe_games_by_matchup(scoreboard_games)

        fallback_games = self._fetch_slate_games_from_fallback(slate_date)
        if fallback_games:
            self._logger.info(
                "Using fallback slate games for %s (%d games).",
                slate_date.isoformat(),
                len(fallback_games),
            )
        return self._dedupe_games_by_matchup(fallback_games)

    def _fetch_slate_games_from_scoreboard(self, slate_date: date) -> list[Game]:
        last_error: Exception | None = None
        for attempt in range(1, self._scoreboard_retries + 1):
            try:
                board = scoreboardv2.ScoreboardV2(
                    game_date=slate_date.strftime("%m/%d/%Y"),
                    day_offset=0,
                    league_id="00",
                    timeout=self._scoreboard_timeout_seconds,
                )
                frames = board.get_data_frames()
                if not frames:
                    return []
                return self._games_from_scoreboard_frames(frames)
            except Exception as exc:
                last_error = exc
                self._logger.warning(
                    "Scoreboard fetch failed for %s (attempt %d/%d): %s",
                    slate_date.isoformat(),
                    attempt,
                    self._scoreboard_retries,
                    exc,
                )
        if last_error is not None:
            self._logger.warning(
                "Scoreboard fetch exhausted retries for %s: %s",
                slate_date.isoformat(),
                last_error,
            )
        return []

    def _games_from_scoreboard_frames(self, frames: list[pd.DataFrame]) -> list[Game]:
        headers = frames[0]
        line_scores = frames[1] if len(frames) > 1 else pd.DataFrame()

        team_lookup: Dict[tuple[str, int], str] = {}
        if not line_scores.empty:
            for row in line_scores.to_dict("records"):
                game_id = str(row.get("GAME_ID", ""))
                team_id = int(row.get("TEAM_ID", 0)) if row.get("TEAM_ID") is not None else 0
                abbr = str(row.get("TEAM_ABBREVIATION", "")).upper()
                if game_id and team_id and abbr:
                    team_lookup[(game_id, team_id)] = abbr

        games: list[Game] = []
        for row in headers.to_dict("records"):
            game_id = str(row.get("GAME_ID", "")).strip()
            home_id = int(row.get("HOME_TEAM_ID", 0) or 0)
            away_id = int(row.get("VISITOR_TEAM_ID", 0) or 0)

            home = (
                team_lookup.get((game_id, home_id))
                or self.id_to_abbr.get(home_id)
                or str(row.get("HOME_TEAM_ABBREVIATION", "")).upper()
            )
            away = (
                team_lookup.get((game_id, away_id))
                or self.id_to_abbr.get(away_id)
                or str(row.get("VISITOR_TEAM_ABBREVIATION", "")).upper()
            )

            if not game_id or not home or not away:
                continue

            games.append(
                Game(
                    game_id=game_id,
                    away_team=away,
                    home_team=home,
                    start_time_utc=(str(row.get("GAME_DATE_EST") or "") or None),
                )
            )
        return games

    def _fetch_slate_games_from_fallback(self, slate_date: date) -> list[Game]:
        season = season_label_for_date(slate_date)
        cached_team_logs = self._get_cached_team_logs_for_season(season)
        if not cached_team_logs.empty:
            games = self._build_games_from_team_logs(cached_team_logs, slate_date)
            if games:
                return games

        try:
            endpoint = leaguegamefinder.LeagueGameFinder(
                player_or_team_abbreviation="T",
                season_nullable=season,
                season_type_nullable="Regular Season",
                date_from_nullable=slate_date.strftime("%m/%d/%Y"),
                date_to_nullable=slate_date.strftime("%m/%d/%Y"),
                timeout=self._fallback_timeout_seconds,
            )
            frames = endpoint.get_data_frames()
            if not frames:
                return []
            team_logs = frames[0]
            return self._build_games_from_team_logs(team_logs, slate_date)
        except Exception as exc:
            self._logger.warning(
                "Fallback slate fetch failed for %s: %s",
                slate_date.isoformat(),
                exc,
            )
            return []

    def _get_cached_team_logs_for_season(self, season: str) -> pd.DataFrame:
        cached = self._season_team_logs_cache.get(season)
        if cached is not None:
            return cached
        loaded = self._read_cached_frame(self._raw_cache_path("team_logs", season))
        if loaded is not None:
            self._season_team_logs_cache[season] = loaded
            return loaded
        return pd.DataFrame()

    def _build_games_from_team_logs(self, team_logs_df: pd.DataFrame, slate_date: date) -> list[Game]:
        if team_logs_df.empty:
            return []

        game_col = self._pick_column(team_logs_df, ["GAME_ID"])
        team_col = self._pick_column(team_logs_df, ["TEAM_ABBREVIATION"])
        matchup_col = self._pick_column(team_logs_df, ["MATCHUP"])
        date_col = self._pick_column(team_logs_df, ["GAME_DATE", "GAME_DATE_EST"])
        if not all([game_col, team_col, matchup_col, date_col]):
            return []

        frame = team_logs_df[[game_col, team_col, matchup_col, date_col]].copy()
        frame["_parsed_date"] = pd.to_datetime(frame[date_col], errors="coerce").dt.date
        frame = frame[frame["_parsed_date"] == slate_date]
        if frame.empty:
            return []

        grouped: dict[str, dict[str, str]] = defaultdict(dict)
        for row in frame.to_dict("records"):
            game_id = str(row.get(game_col, "")).strip()
            team = str(row.get(team_col, "")).strip().upper()
            matchup = str(row.get(matchup_col, "")).upper()
            if not game_id or not team:
                continue
            grouped[game_id][team] = matchup

        games: list[Game] = []
        for game_id, team_matchups in sorted(grouped.items()):
            home_team: str | None = None
            away_team: str | None = None
            teams = list(team_matchups.keys())
            for team, matchup in team_matchups.items():
                if " VS." in matchup or " VS " in matchup:
                    home_team = team
                elif "@" in matchup:
                    away_team = team

            if not home_team and len(teams) == 2 and away_team in teams:
                home_team = teams[0] if teams[1] == away_team else teams[1]
            if not away_team and len(teams) == 2 and home_team in teams:
                away_team = teams[0] if teams[1] == home_team else teams[1]

            if not home_team or not away_team:
                continue

            games.append(
                Game(
                    game_id=game_id,
                    away_team=away_team,
                    home_team=home_team,
                    start_time_utc=None,
                )
            )

        return games

    @staticmethod
    def _dedupe_games_by_matchup(games: list[Game]) -> list[Game]:
        if not games:
            return []

        deduped: dict[tuple[str, str], Game] = {}
        for game in games:
            key = (game.away_team, game.home_team)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = game
                continue
            # Prefer rows with known start time, then lowest game id for deterministic output.
            if (not existing.start_time_utc and game.start_time_utc) or game.game_id < existing.game_id:
                deduped[key] = game

        return sorted(
            deduped.values(),
            key=lambda game: (game.start_time_utc or "", game.away_team, game.home_team, game.game_id),
        )

    def fetch_player_baselines(self, as_of_date: date, season: str) -> pd.DataFrame:
        player_logs = self.fetch_player_logs(as_of_date=as_of_date, season=season)
        return self._build_player_baselines_from_logs(player_logs)

    def fetch_player_logs(self, as_of_date: date, season: str) -> pd.DataFrame:
        season_logs = self._get_season_player_logs(season=season, as_of_date=as_of_date)
        return self._filter_logs_by_as_of(season_logs, as_of_date=as_of_date)

    def fetch_team_logs(self, as_of_date: date, season: str) -> pd.DataFrame:
        season_logs = self._get_season_team_logs(season=season, as_of_date=as_of_date)
        return self._filter_logs_by_as_of(season_logs, as_of_date=as_of_date)

    def _get_season_player_logs(self, season: str, as_of_date: date) -> pd.DataFrame:
        cached = self._season_player_logs_cache.get(season)
        if cached is None:
            cached = self._read_cached_frame(self._raw_cache_path("player_logs", season))
            if cached is not None:
                self._season_player_logs_cache[season] = cached

        if cached is not None:
            max_cached_date = self._extract_max_game_date(cached)
            if max_cached_date is not None and max_cached_date >= as_of_date:
                return cached

        fetched = self._fetch_player_logs_remote_full_season(season=season)
        if not fetched.empty:
            self._season_player_logs_cache[season] = fetched
            self._write_cached_frame(self._raw_cache_path("player_logs", season), fetched)
            return fetched

        return cached if cached is not None else pd.DataFrame()

    def _get_season_team_logs(self, season: str, as_of_date: date) -> pd.DataFrame:
        cached = self._season_team_logs_cache.get(season)
        if cached is None:
            cached = self._read_cached_frame(self._raw_cache_path("team_logs", season))
            if cached is not None:
                self._season_team_logs_cache[season] = cached

        if cached is not None:
            max_cached_date = self._extract_max_game_date(cached)
            if max_cached_date is not None and max_cached_date >= as_of_date:
                return cached

        fetched = self._fetch_team_logs_remote_full_season(season=season)
        if not fetched.empty:
            self._season_team_logs_cache[season] = fetched
            self._write_cached_frame(self._raw_cache_path("team_logs", season), fetched)
            return fetched

        return cached if cached is not None else pd.DataFrame()

    def _fetch_player_logs_remote_full_season(self, season: str) -> pd.DataFrame:
        try:
            endpoint = playergamelogs.PlayerGameLogs(
                season_nullable=season,
                season_type_nullable="Regular Season",
            )
            frames = endpoint.get_data_frames()
            return frames[0] if frames else pd.DataFrame()
        except Exception as exc:
            self._logger.warning("Player logs fetch failed for season=%s: %s", season, exc)
            return pd.DataFrame()

    def _fetch_team_logs_remote_full_season(self, season: str) -> pd.DataFrame:
        try:
            endpoint = leaguegamefinder.LeagueGameFinder(
                player_or_team_abbreviation="T",
                season_nullable=season,
                season_type_nullable="Regular Season",
            )
            frames = endpoint.get_data_frames()
            return frames[0] if frames else pd.DataFrame()
        except Exception as exc:
            self._logger.warning("Team logs fetch failed for season=%s: %s", season, exc)
            return pd.DataFrame()

    def _build_player_baselines_from_logs(self, player_logs: pd.DataFrame) -> pd.DataFrame:
        if player_logs.empty:
            return pd.DataFrame()

        player_id_col = self._pick_column(player_logs, ["PLAYER_ID"])
        player_name_col = self._pick_column(player_logs, ["PLAYER_NAME"])
        team_col = self._pick_column(player_logs, ["TEAM_ABBREVIATION"])
        min_col = self._pick_column(player_logs, ["MIN"])
        stat_column_map = {
            "MIN": self._pick_column(player_logs, ["MIN"]),
            "PTS": self._pick_column(player_logs, ["PTS"]),
            "AST": self._pick_column(player_logs, ["AST"]),
            "REB": self._pick_column(player_logs, ["REB"]),
            "STL": self._pick_column(player_logs, ["STL"]),
            "BLK": self._pick_column(player_logs, ["BLK"]),
            "FG3A": self._pick_column(player_logs, ["FG3A"]),
            "FG3M": self._pick_column(player_logs, ["FG3M"]),
            "FTA": self._pick_column(player_logs, ["FTA"]),
            "FTM": self._pick_column(player_logs, ["FTM"]),
            "FGA": self._pick_column(player_logs, ["FGA"]),
            "FGM": self._pick_column(player_logs, ["FGM"]),
            "TOV": self._pick_column(player_logs, ["TOV"]),
            "PLUS_MINUS": self._pick_column(player_logs, ["PLUS_MINUS"]),
        }
        date_col = self._pick_column(player_logs, ["GAME_DATE", "GAME_DATE_EST"])

        if not all([player_id_col, player_name_col, team_col, stat_column_map["MIN"], date_col]):
            return pd.DataFrame()

        base_cols = [player_id_col, player_name_col, team_col, date_col]
        for value in stat_column_map.values():
            if value:
                base_cols.append(value)

        frame = player_logs[base_cols].copy()
        frame["_parsed_date"] = pd.to_datetime(frame[date_col], errors="coerce")
        for value in stat_column_map.values():
            if value:
                frame[value] = pd.to_numeric(frame[value], errors="coerce")

        frame = frame.dropna(subset=[player_id_col, "_parsed_date", stat_column_map["MIN"]])
        if frame.empty:
            return pd.DataFrame()

        latest_team = (
            frame.sort_values("_parsed_date")
            .drop_duplicates(subset=[player_id_col], keep="last")[[player_id_col, player_name_col, team_col]]
            .set_index(player_id_col)
        )
        grouped = frame.groupby(player_id_col).agg({date_col: "count"})
        grouped = grouped.rename(columns={date_col: "_GP"})
        for name, column in stat_column_map.items():
            if column:
                grouped[f"_{name}_TOTAL"] = frame.groupby(player_id_col)[column].sum(min_count=1)
            else:
                grouped[f"_{name}_TOTAL"] = 0.0

        grouped["_GP"] = grouped["_GP"].clip(lower=1)
        for name in stat_column_map:
            grouped[name] = grouped[f"_{name}_TOTAL"] / grouped["_GP"]

        grouped["FG_PCT"] = grouped.apply(
            lambda row: float(row["_FGM_TOTAL"] / row["_FGA_TOTAL"]) if row["_FGA_TOTAL"] > 0 else 0.0,
            axis=1,
        )
        grouped["FG3_PCT"] = grouped.apply(
            lambda row: float(row["_FG3M_TOTAL"] / row["_FG3A_TOTAL"]) if row["_FG3A_TOTAL"] > 0 else 0.0,
            axis=1,
        )
        grouped["FT_PCT"] = grouped.apply(
            lambda row: float(row["_FTM_TOTAL"] / row["_FTA_TOTAL"]) if row["_FTA_TOTAL"] > 0 else 0.0,
            axis=1,
        )

        merged = latest_team.join(grouped, how="inner").reset_index()
        renamed = merged.rename(
            columns={
                player_id_col: "PLAYER_ID",
                player_name_col: "PLAYER_NAME",
                team_col: "TEAM_ABBREVIATION",
            }
        )
        for name in [
            "MIN",
            "PTS",
            "AST",
            "REB",
            "STL",
            "BLK",
            "FG3A",
            "FG3M",
            "FTA",
            "FTM",
            "FG_PCT",
            "FG3_PCT",
            "FT_PCT",
            "TOV",
            "PLUS_MINUS",
        ]:
            if name not in renamed.columns:
                renamed[name] = 0.0

        return renamed[
            [
                "PLAYER_ID",
                "PLAYER_NAME",
                "TEAM_ABBREVIATION",
                "MIN",
                "PTS",
                "AST",
                "REB",
                "STL",
                "BLK",
                "FG3A",
                "FG3M",
                "FTA",
                "FTM",
                "FG_PCT",
                "FG3_PCT",
                "FT_PCT",
                "TOV",
                "PLUS_MINUS",
            ]
        ]

    def _filter_logs_by_as_of(self, logs_df: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
        if logs_df.empty:
            return logs_df
        date_col = self._pick_column(logs_df, ["GAME_DATE", "GAME_DATE_EST"])
        if not date_col:
            return logs_df

        frame = logs_df.copy()
        frame["_parsed_date"] = pd.to_datetime(frame[date_col], errors="coerce").dt.date
        frame = frame[frame["_parsed_date"].notna()]
        frame = frame[frame["_parsed_date"] <= as_of_date]
        return frame.drop(columns=["_parsed_date"])

    def _extract_max_game_date(self, logs_df: pd.DataFrame) -> date | None:
        if logs_df.empty:
            return None
        date_col = self._pick_column(logs_df, ["GAME_DATE", "GAME_DATE_EST"])
        if not date_col:
            return None
        parsed = pd.to_datetime(logs_df[date_col], errors="coerce").dt.date
        parsed = parsed[parsed.notna()]
        if parsed.empty:
            return None
        return max(parsed)

    def _raw_cache_path(self, prefix: str, season: str) -> Path:
        season_token = season.replace("/", "-")
        return self._raw_data_dir / f"{prefix}_{season_token}.pkl"

    def _read_cached_frame(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        try:
            loaded = pd.read_pickle(path)
            if isinstance(loaded, pd.DataFrame):
                self._logger.info("Loaded raw cache: %s (%d rows)", path.name, len(loaded))
                return loaded
        except Exception:
            return None
        return None

    def _write_cached_frame(self, path: Path, frame: pd.DataFrame) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_pickle(path)
        except Exception as exc:
            self._logger.warning("Failed writing raw cache %s: %s", path.name, exc)

    def build_snapshot(self, as_of_date: date, season: str, slate_teams: set[str] | None = None) -> dict:
        started = perf_counter()
        player_logs = self.fetch_player_logs(as_of_date=as_of_date, season=season)
        player_logs_elapsed = perf_counter() - started
        player_baselines = self._build_player_baselines_from_logs(player_logs)
        baselines_elapsed = perf_counter() - started
        team_logs = self.fetch_team_logs(as_of_date=as_of_date, season=season)
        team_logs_elapsed = perf_counter() - started
        player_minutes = self._build_player_minutes_map(player_logs)
        roster_positions = self._build_roster_position_map(season=season, team_abbr_filter=slate_teams)
        team_roster_player_ids = self._build_team_roster_player_id_map(season=season, team_abbr_filter=slate_teams)
        roster_team_by_player_id = self._build_roster_team_by_player_id(team_roster_player_ids)
        roster_elapsed = perf_counter() - started

        rotation_pool, position_map = self._build_rotation_pool(
            baselines_df=player_baselines,
            player_minutes=player_minutes,
            roster_positions=roster_positions,
            team_roster_player_ids=team_roster_player_ids,
            roster_team_by_player_id=roster_team_by_player_id,
            team_filter=slate_teams,
        )
        player_cards = self._build_player_cards(
            baselines_df=player_baselines,
            player_positions=position_map,
            team_roster_player_ids=team_roster_player_ids,
            roster_team_by_player_id=roster_team_by_player_id,
            as_of_date=as_of_date,
            season=season,
            team_filter=slate_teams,
        )
        rotation_elapsed = perf_counter() - started
        team_game_ids_last10 = self._build_team_last10_game_ids(team_logs)

        season_stats, last10_stats = self._build_dvp_tables(
            player_logs=player_logs,
            player_positions=position_map,
            team_last10_games=team_game_ids_last10,
        )
        dvp_elapsed = perf_counter() - started

        season_ranks = build_rank_tables(team_group_stats=season_stats, teams=self.team_abbrs)
        last10_ranks = build_rank_tables(team_group_stats=last10_stats, teams=self.team_abbrs)

        season_team_metrics, last10_team_metrics = self._build_team_environment_metrics(team_logs)
        season_environment = build_environment_scores(season_team_metrics, self.team_abbrs)
        last10_environment = build_environment_scores(last10_team_metrics, self.team_abbrs)
        final_elapsed = perf_counter() - started

        self._logger.info(
            (
                "Snapshot timing season=%s as_of=%s teams=%d total=%.2fs "
                "(baselines=%.2fs player_logs=%.2fs team_logs=%.2fs roster=%.2fs rotation=%.2fs dvp=%.2fs)"
            ),
            season,
            as_of_date.isoformat(),
            len(slate_teams or []),
            final_elapsed,
            baselines_elapsed - player_logs_elapsed,
            player_logs_elapsed,
            team_logs_elapsed - baselines_elapsed,
            roster_elapsed - team_logs_elapsed,
            rotation_elapsed - roster_elapsed,
            dvp_elapsed - rotation_elapsed,
        )

        return {
            "rotation_pool": rotation_pool,
            "player_cards": player_cards,
            "season": {
                "ranks": season_ranks,
                "environment": season_environment,
            },
            "last10": {
                "ranks": last10_ranks,
                "environment": last10_environment,
            },
        }

    def _build_player_cards(
        self,
        baselines_df: pd.DataFrame,
        player_positions: dict[int, list[PositionGroup]],
        team_roster_player_ids: dict[str, set[int]] | None,
        roster_team_by_player_id: dict[int, str] | None,
        as_of_date: date,
        season: str,
        team_filter: set[str] | None = None,
    ) -> list[PlayerCardResponse]:
        if baselines_df.empty:
            return []

        id_col = self._pick_column(baselines_df, ["PLAYER_ID"])
        name_col = self._pick_column(baselines_df, ["PLAYER_NAME", "DISPLAY_FIRST_LAST"])
        team_col = self._pick_column(baselines_df, ["TEAM_ABBREVIATION", "TEAM_ABBREV"])
        if not all([id_col, name_col, team_col]):
            return []

        stat_map = {
            "mpg": self._pick_column(baselines_df, ["MIN"]),
            "ppg": self._pick_column(baselines_df, ["PTS"]),
            "assists_pg": self._pick_column(baselines_df, ["AST"]),
            "rebounds_pg": self._pick_column(baselines_df, ["REB"]),
            "steals_pg": self._pick_column(baselines_df, ["STL"]),
            "blocks_pg": self._pick_column(baselines_df, ["BLK"]),
            "three_pa_pg": self._pick_column(baselines_df, ["FG3A"]),
            "three_pm_pg": self._pick_column(baselines_df, ["FG3M"]),
            "fta_pg": self._pick_column(baselines_df, ["FTA"]),
            "ftm_pg": self._pick_column(baselines_df, ["FTM"]),
            "fg_pct": self._pick_column(baselines_df, ["FG_PCT"]),
            "three_p_pct": self._pick_column(baselines_df, ["FG3_PCT"]),
            "ft_pct": self._pick_column(baselines_df, ["FT_PCT"]),
            "turnovers_pg": self._pick_column(baselines_df, ["TOV"]),
            "plus_minus_pg": self._pick_column(baselines_df, ["PLUS_MINUS"]),
        }

        cards: list[PlayerCardResponse] = []
        for row in baselines_df.to_dict("records"):
            player_id = int(row.get(id_col, 0) or 0)
            if not player_id:
                continue
            player_name = str(row.get(name_col, "")).strip()
            team = (
                (roster_team_by_player_id or {}).get(player_id)
                or str(row.get(team_col, "")).strip().upper()
            )
            if team_filter and team not in team_filter:
                continue
            roster_ids = (team_roster_player_ids or {}).get(team)
            if roster_ids is not None and player_id not in roster_ids:
                continue
            if not player_name or not team:
                continue

            position_group = player_positions.get(player_id, [PositionGroup.guards])[0]
            values = {}
            for key, col in stat_map.items():
                raw = row.get(col, 0.0) if col else 0.0
                values[key] = round(float(raw or 0.0), 3)

            cards.append(
                PlayerCardResponse(
                    player_id=player_id,
                    player_name=player_name,
                    team=team,
                    season=season,
                    as_of_date=as_of_date,
                    position_group=position_group,
                    mpg=values["mpg"],
                    ppg=values["ppg"],
                    assists_pg=values["assists_pg"],
                    rebounds_pg=values["rebounds_pg"],
                    steals_pg=values["steals_pg"],
                    blocks_pg=values["blocks_pg"],
                    three_pa_pg=values["three_pa_pg"],
                    three_pm_pg=values["three_pm_pg"],
                    fta_pg=values["fta_pg"],
                    ftm_pg=values["ftm_pg"],
                    fg_pct=values["fg_pct"],
                    three_p_pct=values["three_p_pct"],
                    ft_pct=values["ft_pct"],
                    turnovers_pg=values["turnovers_pg"],
                    plus_minus_pg=values["plus_minus_pg"],
                )
            )

        return cards

    def _build_rotation_pool(
        self,
        baselines_df: pd.DataFrame,
        player_minutes: dict[int, float],
        roster_positions: dict[int, list[PositionGroup]],
        team_roster_player_ids: dict[str, set[int]] | None,
        roster_team_by_player_id: dict[int, str] | None,
        team_filter: set[str] | None = None,
    ) -> tuple[list[dict], dict[int, list[PositionGroup]]]:
        if baselines_df.empty:
            return [], {}

        position_col = self._pick_column(
            baselines_df,
            [
                "POSITION",
                "PLAYER_POSITION",
                "PLAYER_POSITION_ABBREVIATION",
                "POS",
            ],
        )
        player_id_col = self._pick_column(baselines_df, ["PLAYER_ID"])
        player_name_col = self._pick_column(baselines_df, ["PLAYER_NAME", "DISPLAY_FIRST_LAST"])
        team_col = self._pick_column(baselines_df, ["TEAM_ABBREVIATION", "TEAM_ABBREV"])
        min_col = self._pick_column(baselines_df, ["MIN"])
        height_inches_col = self._pick_column(baselines_df, ["PLAYER_HEIGHT_INCHES", "HEIGHT_INCHES"])
        height_col = self._pick_column(baselines_df, ["PLAYER_HEIGHT", "HEIGHT"])
        ast_col = self._pick_column(baselines_df, ["AST"])
        reb_col = self._pick_column(baselines_df, ["REB"])

        if not all([player_id_col, player_name_col, team_col]):
            self._logger.warning(
                "Rotation pool columns missing. Available columns: %s",
                list(baselines_df.columns),
            )
            return [], {}

        rotation_pool: list[dict] = []
        player_positions: dict[int, list[PositionGroup]] = {}
        inferred_position_count = 0
        fallback_position_count = 0

        for row in baselines_df.to_dict("records"):
            player_id = int(row.get(player_id_col, 0) or 0)
            player_name = str(row.get(player_name_col, "")).strip()
            team = (
                (roster_team_by_player_id or {}).get(player_id)
                or str(row.get(team_col, "")).strip().upper()
            )
            if team_filter and team not in team_filter:
                continue
            roster_ids = (team_roster_player_ids or {}).get(team)
            if roster_ids is not None and player_id not in roster_ids:
                continue
            baseline_minutes = float(row.get(min_col, 0.0) or 0.0) if min_col else 0.0
            avg_minutes = float(player_minutes.get(player_id, baseline_minutes))
            raw_position = str(row.get(position_col, "")) if position_col else ""
            positions = map_position_groups(raw_position)
            if not positions:
                positions = roster_positions.get(player_id, [])
            if not positions:
                height_inches = row.get(height_inches_col) if height_inches_col else None
                height_text = row.get(height_col) if height_col else None
                ast_value = row.get(ast_col) if ast_col else None
                reb_value = row.get(reb_col) if reb_col else None
                positions = self._infer_position_groups(
                    height_inches=height_inches,
                    height_text=height_text,
                    ast_value=ast_value,
                    reb_value=reb_value,
                )
                if positions:
                    inferred_position_count += 1

            # Fallback for datasets that omit position metadata.
            if not positions:
                positions = [PositionGroup.guards]
                fallback_position_count += 1

            # Only enforce a minutes threshold when a minutes column exists.
            if avg_minutes < 5.0:
                continue

            if not player_id or not player_name or not team or not positions:
                continue

            player_positions[player_id] = positions
            for position_group in positions:
                rotation_pool.append(
                    {
                        "player_id": player_id,
                        "player_name": player_name,
                        "team": team,
                        "avg_minutes": round(avg_minutes, 2),
                        "position_group": position_group,
                    }
                )

        if inferred_position_count:
            self._logger.info(
                "Inferred position groups for %d players using local profile heuristics.",
                inferred_position_count,
            )

        if fallback_position_count:
            self._logger.warning(
                "Applied default Guard position fallback for %d players due to missing position metadata.",
                fallback_position_count,
            )

        return rotation_pool, player_positions

    @staticmethod
    def _build_roster_team_by_player_id(team_roster_player_ids: dict[str, set[int]] | None) -> dict[int, str]:
        if not team_roster_player_ids:
            return {}
        roster_team_by_player_id: dict[int, str] = {}
        for team_abbr, player_ids in team_roster_player_ids.items():
            for player_id in player_ids:
                roster_team_by_player_id[int(player_id)] = team_abbr
        return roster_team_by_player_id

    def _build_player_minutes_map(self, player_logs_df: pd.DataFrame) -> dict[int, float]:
        if player_logs_df.empty:
            return {}

        player_id_col = self._pick_column(player_logs_df, ["PLAYER_ID"])
        min_col = self._pick_column(player_logs_df, ["MIN"])
        if not player_id_col or not min_col:
            return {}

        frame = player_logs_df[[player_id_col, min_col]].copy()
        frame[min_col] = pd.to_numeric(frame[min_col], errors="coerce")
        frame = frame.dropna(subset=[min_col])
        if frame.empty:
            return {}

        grouped = frame.groupby(player_id_col)[min_col].mean()
        return {int(player_id): float(minutes) for player_id, minutes in grouped.items()}

    def _build_roster_position_map(
        self,
        season: str,
        team_abbr_filter: set[str] | None = None,
    ) -> dict[int, list[PositionGroup]]:
        if not self._enable_roster_fetch:
            return {}

        team_ids: list[int]
        if team_abbr_filter:
            team_ids = [self.abbr_to_id[abbr] for abbr in sorted(team_abbr_filter) if abbr in self.abbr_to_id]
        else:
            team_ids = [int(team["id"]) for team in self._teams]
        self._ensure_roster_cache(season=season, team_ids=team_ids)

        result: dict[int, list[PositionGroup]] = {}
        for team_id in team_ids:
            positions = self._roster_position_cache.get((season, team_id), {})
            result.update(positions)
        return result

    def _build_team_roster_player_id_map(
        self,
        season: str,
        team_abbr_filter: set[str] | None = None,
    ) -> dict[str, set[int]]:
        if not self._enable_roster_fetch:
            return {}

        team_ids: list[int]
        if team_abbr_filter:
            team_ids = [self.abbr_to_id[abbr] for abbr in sorted(team_abbr_filter) if abbr in self.abbr_to_id]
        else:
            team_ids = [int(team["id"]) for team in self._teams]
        self._ensure_roster_cache(season=season, team_ids=team_ids)

        result: dict[str, set[int]] = {}
        for team_id in team_ids:
            player_ids = self._roster_player_ids_cache.get((season, team_id))
            team_abbr = self.id_to_abbr.get(team_id)
            if team_abbr and player_ids:
                result[team_abbr] = set(player_ids)
        return result

    def _ensure_roster_cache(self, season: str, team_ids: list[int]) -> None:
        if not team_ids:
            return

        uncached_team_ids: list[int] = []
        for team_id in team_ids:
            cache_key = (season, team_id)
            positions_cached = cache_key in self._roster_position_cache
            player_ids_cached = cache_key in self._roster_player_ids_cache
            if positions_cached and player_ids_cached:
                continue
            uncached_team_ids.append(team_id)

        if not uncached_team_ids:
            return

        max_workers = min(8, len(uncached_team_ids))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._fetch_team_roster_data, team_id, season): team_id
                for team_id in uncached_team_ids
            }

            for future in as_completed(futures):
                team_id = futures[future]
                cache_key = (season, team_id)
                try:
                    team_player_positions, player_ids = future.result()
                except Exception as exc:
                    self._logger.warning(
                        "Roster fetch failed for team_id=%s season=%s: %s",
                        team_id,
                        season,
                        exc,
                    )
                    team_player_positions, player_ids = {}, None

                self._roster_position_cache[cache_key] = team_player_positions
                self._roster_player_ids_cache[cache_key] = player_ids

    def _fetch_team_roster_data(self, team_id: int, season: str) -> tuple[dict[int, list[PositionGroup]], set[int]]:
        endpoint = commonteamroster.CommonTeamRoster(team_id=team_id, season=season, timeout=6)
        frames = endpoint.get_data_frames()
        if not frames:
            return {}, set()
        roster_df = frames[0]
        if roster_df.empty:
            return {}, set()

        player_id_col = self._pick_column(roster_df, ["PLAYER_ID"])
        position_col = self._pick_column(roster_df, ["POSITION", "POS"])
        if not player_id_col:
            return {}, set()

        team_player_positions: dict[int, list[PositionGroup]] = {}
        team_player_ids: set[int] = set()
        for row in roster_df.to_dict("records"):
            player_id = int(row.get(player_id_col, 0) or 0)
            if not player_id:
                continue
            team_player_ids.add(player_id)
            if position_col:
                position_text = str(row.get(position_col, ""))
                mapped = map_position_groups(position_text)
                if mapped:
                    team_player_positions[player_id] = mapped

        return team_player_positions, team_player_ids

    @staticmethod
    def _infer_position_groups(
        height_inches: object | None,
        height_text: object | None,
        ast_value: object | None,
        reb_value: object | None,
    ) -> list[PositionGroup]:
        parsed_height = NBADataService._parse_height_inches(height_inches, height_text)
        if parsed_height is not None:
            if parsed_height <= 77:
                return [PositionGroup.guards]
            if parsed_height >= 82:
                return [PositionGroup.centers]
            return [PositionGroup.forwards]

        ast_num = NBADataService._safe_float(ast_value)
        reb_num = NBADataService._safe_float(reb_value)
        if ast_num is None and reb_num is None:
            return []

        # Guard-forward split fallback when no roster/position metadata is available.
        if ast_num is not None and ast_num >= 4.0:
            return [PositionGroup.guards]
        if reb_num is not None and reb_num >= 7.0:
            return [PositionGroup.centers]
        return [PositionGroup.forwards]

    @staticmethod
    def _parse_height_inches(height_inches: object | None, height_text: object | None) -> int | None:
        numeric = NBADataService._safe_float(height_inches)
        if numeric is not None:
            return int(round(numeric))

        if isinstance(height_text, str):
            text = height_text.strip()
            if "-" in text:
                parts = text.split("-")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    feet = int(parts[0])
                    inches = int(parts[1])
                    return (feet * 12) + inches
            if text.isdigit():
                return int(text)
        return None

    @staticmethod
    def _safe_float(value: object | None) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_team_last10_game_ids(self, team_logs_df: pd.DataFrame) -> dict[str, set[str]]:
        if team_logs_df.empty:
            return defaultdict(set)

        team_col = self._pick_column(team_logs_df, ["TEAM_ABBREVIATION"])
        game_id_col = self._pick_column(team_logs_df, ["GAME_ID"])
        date_col = self._pick_column(team_logs_df, ["GAME_DATE", "GAME_DATE_EST"])

        if not all([team_col, game_id_col, date_col]):
            return defaultdict(set)

        frame = team_logs_df[[team_col, game_id_col, date_col]].copy()
        frame["_parsed_date"] = pd.to_datetime(frame[date_col], errors="coerce")
        frame = frame.dropna(subset=["_parsed_date"])

        result: dict[str, set[str]] = defaultdict(set)
        for team, subset in frame.groupby(team_col):
            sorted_subset = subset.sort_values("_parsed_date", ascending=False).head(10)
            result[str(team).upper()] = {str(game_id) for game_id in sorted_subset[game_id_col].astype(str).tolist()}

        return result

    def _build_team_environment_metrics(self, team_logs_df: pd.DataFrame) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
        if team_logs_df.empty:
            return {}, {}

        required = ["GAME_ID", "TEAM_ABBREVIATION", "GAME_DATE", "FGA", "FTA", "OREB", "TOV", "PTS"]
        present = {col.upper(): col for col in team_logs_df.columns}
        if not all(column in present for column in required):
            return {}, {}

        team_logs_df = team_logs_df.copy()
        team_logs_df["_parsed_date"] = pd.to_datetime(team_logs_df[present["GAME_DATE"]], errors="coerce")
        team_logs_df = team_logs_df.dropna(subset=["_parsed_date"])

        game_col = present["GAME_ID"]
        team_col = present["TEAM_ABBREVIATION"]
        fga_col = present["FGA"]
        fta_col = present["FTA"]
        oreb_col = present["OREB"]
        tov_col = present["TOV"]
        pts_col = present["PTS"]

        by_game: dict[str, list[dict]] = defaultdict(list)
        records = team_logs_df.to_dict("records")
        for row in records:
            by_game[str(row[game_col])].append(row)

        per_team_games: dict[str, list[dict]] = defaultdict(list)

        for row in records:
            game_id = str(row[game_col])
            team = str(row[team_col]).upper()
            date_value = row["_parsed_date"]
            opponents = [candidate for candidate in by_game[game_id] if str(candidate[team_col]).upper() != team]
            if not opponents:
                continue

            opp = opponents[0]
            team_poss = float(row[fga_col]) + 0.44 * float(row[fta_col]) - float(row[oreb_col]) + float(row[tov_col])
            opp_poss = float(opp[fga_col]) + 0.44 * float(opp[fta_col]) - float(opp[oreb_col]) + float(opp[tov_col])
            possessions = 0.5 * (team_poss + opp_poss)
            if possessions <= 0:
                continue

            def_rating = (float(opp[pts_col]) / possessions) * 100.0
            per_team_games[team].append(
                {
                    "game_id": game_id,
                    "date": date_value,
                    "def_rating": def_rating,
                    "pace": possessions,
                }
            )

        season_metrics: dict[str, dict[str, float]] = {}
        last10_metrics: dict[str, dict[str, float]] = {}

        for team, rows in per_team_games.items():
            if not rows:
                continue
            sorted_rows = sorted(rows, key=lambda item: item["date"], reverse=True)

            season_def = sum(row["def_rating"] for row in sorted_rows) / len(sorted_rows)
            season_pace = sum(row["pace"] for row in sorted_rows) / len(sorted_rows)
            season_metrics[team] = {"def_rating": season_def, "pace": season_pace}

            recent = sorted_rows[:10]
            last10_def = sum(row["def_rating"] for row in recent) / len(recent)
            last10_pace = sum(row["pace"] for row in recent) / len(recent)
            last10_metrics[team] = {"def_rating": last10_def, "pace": last10_pace}

        return season_metrics, last10_metrics

    def _build_dvp_tables(
        self,
        player_logs: pd.DataFrame,
        player_positions: dict[int, list[PositionGroup]],
        team_last10_games: dict[str, set[str]],
    ) -> tuple[dict, dict]:
        if player_logs.empty or not player_positions:
            return {}, {}

        player_id_col = self._pick_column(player_logs, ["PLAYER_ID"])
        matchup_col = self._pick_column(player_logs, ["MATCHUP"])
        game_id_col = self._pick_column(player_logs, ["GAME_ID"])

        if not all([player_id_col, matchup_col, game_id_col]):
            return {}, {}

        stat_cols = {stat: self._pick_column(player_logs, [stat]) for stat in SUPPORTED_STATS}
        if not all(stat_cols.values()):
            return {}, {}

        season_game_totals = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
        last10_game_totals = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))

        for row in player_logs.to_dict("records"):
            player_id = int(row.get(player_id_col, 0) or 0)
            groups = player_positions.get(player_id)
            if not groups:
                continue

            opponent = parse_matchup_opponent(str(row.get(matchup_col) or ""))
            if not opponent:
                continue

            game_id = str(row.get(game_id_col, ""))
            if not game_id:
                continue

            for group in groups:
                for stat, stat_col in stat_cols.items():
                    value = float(row.get(stat_col, 0.0) or 0.0)
                    season_game_totals[opponent][group][game_id][stat] += value
                    if game_id in team_last10_games.get(opponent, set()):
                        last10_game_totals[opponent][group][game_id][stat] += value

        season_stats = self._average_team_group_stats(season_game_totals)
        last10_stats = self._average_team_group_stats(last10_game_totals)
        return season_stats, last10_stats

    def _average_team_group_stats(self, game_totals: dict) -> dict:
        result = defaultdict(lambda: defaultdict(dict))
        for team, group_map in game_totals.items():
            for group, game_map in group_map.items():
                games_count = len(game_map)
                if games_count == 0:
                    continue
                for stat in SUPPORTED_STATS:
                    total = sum(float(values.get(stat, 0.0)) for values in game_map.values())
                    result[team][group][stat] = round(total / games_count, 3)
        return result

    @staticmethod
    def _pick_column(df: pd.DataFrame, names: Iterable[str]) -> str | None:
        columns = {column.upper(): column for column in df.columns}
        for name in names:
            if name.upper() in columns:
                return columns[name.upper()]
        return None

from __future__ import annotations

from datetime import UTC, datetime, date
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from app.models import MatchupResponse, PlayerCardResponse, PlayerCardWindow, Window


class SnapshotStore:
    def __init__(self, db_path: str | None = None, database_url: str | None = None) -> None:
        if database_url:
            self._database_url = database_url
            self._backend = "postgres" if self._is_postgres_url(database_url) else "sqlite_url"
            self._db_path = self._sqlite_path_from_url(database_url) if self._backend == "sqlite_url" else None
        else:
            if not db_path:
                raise ValueError("SnapshotStore requires either db_path or database_url")
            self._backend = "sqlite_path"
            self._db_path = Path(db_path)
            self._database_url = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._lock:
            if self._backend.startswith("sqlite"):
                self._initialize_sqlite()
            else:
                self._initialize_postgres()

    def get(self, slate_date: date, window: Window) -> MatchupResponse | None:
        if self._backend.startswith("sqlite"):
            row = self._sqlite_get_snapshot_row(slate_date=slate_date, window=window)
        else:
            row = self._postgres_get_snapshot_row(slate_date=slate_date, window=window)

        if row is None:
            return None

        payload_raw = row[0]
        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            return MatchupResponse.model_validate(payload)
        except Exception:
            return None

    def upsert(self, matchup_response: MatchupResponse) -> None:
        payload = json.dumps(matchup_response.model_dump(mode="json"))
        now = datetime.now(UTC).isoformat()
        if self._backend.startswith("sqlite"):
            self._sqlite_upsert_snapshot(
                slate_date=matchup_response.slate_date,
                window=matchup_response.window,
                payload=payload,
                updated_at=now,
            )
        else:
            self._postgres_upsert_snapshot(
                slate_date=matchup_response.slate_date,
                window=matchup_response.window,
                payload=payload,
                updated_at=now,
            )

    def delete_slate(self, slate_date: date) -> int:
        if self._backend.startswith("sqlite"):
            return self._sqlite_delete_slate(slate_date)
        return self._postgres_delete_slate(slate_date)

    def upsert_player_cards(self, cards: list[PlayerCardResponse]) -> int:
        if not cards:
            return 0
        if self._backend.startswith("sqlite"):
            return self._sqlite_upsert_player_cards(cards)
        return self._postgres_upsert_player_cards(cards)

    def get_latest_player_card(
        self,
        player_id: int,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> PlayerCardResponse | None:
        if self._backend.startswith("sqlite"):
            row = self._sqlite_get_latest_player_card_row(player_id=player_id, window=window)
        else:
            row = self._postgres_get_latest_player_card_row(player_id=player_id, window=window)

        if row is None:
            return None

        return self._row_to_player_card(row)

    def get_player_card_as_of(
        self,
        player_id: int,
        as_of_date: date,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> PlayerCardResponse | None:
        if self._backend.startswith("sqlite"):
            row = self._sqlite_get_player_card_as_of_row(player_id=player_id, as_of_date=as_of_date, window=window)
        else:
            row = self._postgres_get_player_card_as_of_row(player_id=player_id, as_of_date=as_of_date, window=window)

        if row is None:
            return None

        return self._row_to_player_card(row)

    @staticmethod
    def _row_to_player_card(row: tuple[Any, ...] | Any) -> PlayerCardResponse:
        return PlayerCardResponse(
            player_id=int(row[0]),
            player_name=str(row[1]),
            team=str(row[2]),
            season=str(row[3]),
            as_of_date=date.fromisoformat(str(row[4])),
            window=PlayerCardWindow(str(row[5])),
            position_group=str(row[6]),
            mpg=float(row[7]),
            ppg=float(row[8]),
            assists_pg=float(row[9]),
            rebounds_pg=float(row[10]),
            steals_pg=float(row[11]),
            blocks_pg=float(row[12]),
            three_pa_pg=float(row[13]),
            three_pm_pg=float(row[14]),
            fta_pg=float(row[15]),
            ftm_pg=float(row[16]),
            fg_pct=float(row[17]),
            three_p_pct=float(row[18]),
            ft_pct=float(row[19]),
            turnovers_pg=float(row[20]),
            plus_minus_pg=float(row[21]),
        )

    def _initialize_sqlite(self) -> None:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._sqlite_connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS matchup_snapshots (
                        slate_date TEXT NOT NULL,
                        window_key TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (slate_date, window_key)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_matchup_snapshots_date
                    ON matchup_snapshots (slate_date)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS player_cards_windowed (
                        player_id INTEGER NOT NULL,
                        player_name TEXT NOT NULL,
                        team TEXT NOT NULL,
                        season TEXT NOT NULL,
                        as_of_date TEXT NOT NULL,
                        window_key TEXT NOT NULL,
                        position_group TEXT NOT NULL,
                        mpg REAL NOT NULL,
                        ppg REAL NOT NULL,
                        assists_pg REAL NOT NULL,
                        rebounds_pg REAL NOT NULL,
                        steals_pg REAL NOT NULL,
                        blocks_pg REAL NOT NULL,
                        three_pa_pg REAL NOT NULL,
                        three_pm_pg REAL NOT NULL,
                        fta_pg REAL NOT NULL,
                        ftm_pg REAL NOT NULL,
                        fg_pct REAL NOT NULL,
                        three_p_pct REAL NOT NULL,
                        ft_pct REAL NOT NULL,
                        turnovers_pg REAL NOT NULL,
                        plus_minus_pg REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (player_id, season, as_of_date, window_key)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_player_cards_windowed_lookup
                    ON player_cards_windowed (player_id, window_key, season, as_of_date)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS player_cards (
                        player_id INTEGER NOT NULL,
                        player_name TEXT NOT NULL,
                        team TEXT NOT NULL,
                        season TEXT NOT NULL,
                        as_of_date TEXT NOT NULL,
                        position_group TEXT NOT NULL,
                        mpg REAL NOT NULL,
                        ppg REAL NOT NULL,
                        assists_pg REAL NOT NULL,
                        rebounds_pg REAL NOT NULL,
                        steals_pg REAL NOT NULL,
                        blocks_pg REAL NOT NULL,
                        three_pa_pg REAL NOT NULL,
                        three_pm_pg REAL NOT NULL,
                        fta_pg REAL NOT NULL,
                        ftm_pg REAL NOT NULL,
                        fg_pct REAL NOT NULL,
                        three_p_pct REAL NOT NULL,
                        ft_pct REAL NOT NULL,
                        turnovers_pg REAL NOT NULL,
                        plus_minus_pg REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (player_id, season, as_of_date)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_player_cards_lookup
                    ON player_cards (player_id, season, as_of_date)
                    """
                )
                conn.commit()

    def _initialize_postgres(self) -> None:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS matchup_snapshots (
                            slate_date DATE NOT NULL,
                            window_key TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL,
                            PRIMARY KEY (slate_date, window_key)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_matchup_snapshots_date
                        ON matchup_snapshots (slate_date)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS player_cards_windowed (
                            player_id BIGINT NOT NULL,
                            player_name TEXT NOT NULL,
                            team TEXT NOT NULL,
                            season TEXT NOT NULL,
                            as_of_date DATE NOT NULL,
                            window_key TEXT NOT NULL,
                            position_group TEXT NOT NULL,
                            mpg DOUBLE PRECISION NOT NULL,
                            ppg DOUBLE PRECISION NOT NULL,
                            assists_pg DOUBLE PRECISION NOT NULL,
                            rebounds_pg DOUBLE PRECISION NOT NULL,
                            steals_pg DOUBLE PRECISION NOT NULL,
                            blocks_pg DOUBLE PRECISION NOT NULL,
                            three_pa_pg DOUBLE PRECISION NOT NULL,
                            three_pm_pg DOUBLE PRECISION NOT NULL,
                            fta_pg DOUBLE PRECISION NOT NULL,
                            ftm_pg DOUBLE PRECISION NOT NULL,
                            fg_pct DOUBLE PRECISION NOT NULL,
                            three_p_pct DOUBLE PRECISION NOT NULL,
                            ft_pct DOUBLE PRECISION NOT NULL,
                            turnovers_pg DOUBLE PRECISION NOT NULL,
                            plus_minus_pg DOUBLE PRECISION NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL,
                            PRIMARY KEY (player_id, season, as_of_date, window_key)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_player_cards_windowed_lookup
                        ON player_cards_windowed (player_id, window_key, season, as_of_date DESC)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS player_cards (
                            player_id BIGINT NOT NULL,
                            player_name TEXT NOT NULL,
                            team TEXT NOT NULL,
                            season TEXT NOT NULL,
                            as_of_date DATE NOT NULL,
                            position_group TEXT NOT NULL,
                            mpg DOUBLE PRECISION NOT NULL,
                            ppg DOUBLE PRECISION NOT NULL,
                            assists_pg DOUBLE PRECISION NOT NULL,
                            rebounds_pg DOUBLE PRECISION NOT NULL,
                            steals_pg DOUBLE PRECISION NOT NULL,
                            blocks_pg DOUBLE PRECISION NOT NULL,
                            three_pa_pg DOUBLE PRECISION NOT NULL,
                            three_pm_pg DOUBLE PRECISION NOT NULL,
                            fta_pg DOUBLE PRECISION NOT NULL,
                            ftm_pg DOUBLE PRECISION NOT NULL,
                            fg_pct DOUBLE PRECISION NOT NULL,
                            three_p_pct DOUBLE PRECISION NOT NULL,
                            ft_pct DOUBLE PRECISION NOT NULL,
                            turnovers_pg DOUBLE PRECISION NOT NULL,
                            plus_minus_pg DOUBLE PRECISION NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL,
                            PRIMARY KEY (player_id, season, as_of_date)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_player_cards_lookup
                        ON player_cards (player_id, season, as_of_date DESC)
                        """
                    )
                conn.commit()

    def _sqlite_get_snapshot_row(self, slate_date: date, window: Window) -> tuple[Any, ...] | None:
        with self._lock:
            with self._sqlite_connect() as conn:
                return conn.execute(
                    """
                    SELECT payload
                    FROM matchup_snapshots
                    WHERE slate_date = ? AND window_key = ?
                    """,
                    (slate_date.isoformat(), window.value),
                ).fetchone()

    def _sqlite_upsert_snapshot(self, slate_date: date, window: Window, payload: str, updated_at: str) -> None:
        with self._lock:
            with self._sqlite_connect() as conn:
                conn.execute(
                    """
                    INSERT INTO matchup_snapshots (slate_date, window_key, payload, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(slate_date, window_key)
                    DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                    """,
                    (slate_date.isoformat(), window.value, payload, updated_at),
                )
                conn.commit()

    def _sqlite_delete_slate(self, slate_date: date) -> int:
        with self._lock:
            with self._sqlite_connect() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM matchup_snapshots
                    WHERE slate_date = ?
                    """,
                    (slate_date.isoformat(),),
                )
                conn.commit()
                return int(cursor.rowcount or 0)

    def _sqlite_upsert_player_cards(self, cards: list[PlayerCardResponse]) -> int:
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                card.player_id,
                card.player_name,
                card.team,
                card.season,
                card.as_of_date.isoformat(),
                card.window.value,
                card.position_group,
                card.mpg,
                card.ppg,
                card.assists_pg,
                card.rebounds_pg,
                card.steals_pg,
                card.blocks_pg,
                card.three_pa_pg,
                card.three_pm_pg,
                card.fta_pg,
                card.ftm_pg,
                card.fg_pct,
                card.three_p_pct,
                card.ft_pct,
                card.turnovers_pg,
                card.plus_minus_pg,
                now,
            )
            for card in cards
        ]
        with self._lock:
            with self._sqlite_connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO player_cards_windowed (
                        player_id, player_name, team, season, as_of_date, window_key, position_group,
                        mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                        three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                        ft_pct, turnovers_pg, plus_minus_pg, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, season, as_of_date, window_key)
                    DO UPDATE SET
                        player_name = excluded.player_name,
                        team = excluded.team,
                        position_group = excluded.position_group,
                        mpg = excluded.mpg,
                        ppg = excluded.ppg,
                        assists_pg = excluded.assists_pg,
                        rebounds_pg = excluded.rebounds_pg,
                        steals_pg = excluded.steals_pg,
                        blocks_pg = excluded.blocks_pg,
                        three_pa_pg = excluded.three_pa_pg,
                        three_pm_pg = excluded.three_pm_pg,
                        fta_pg = excluded.fta_pg,
                        ftm_pg = excluded.ftm_pg,
                        fg_pct = excluded.fg_pct,
                        three_p_pct = excluded.three_p_pct,
                        ft_pct = excluded.ft_pct,
                        turnovers_pg = excluded.turnovers_pg,
                        plus_minus_pg = excluded.plus_minus_pg,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
                conn.commit()
        return len(rows)

    def _sqlite_get_latest_player_card_row(
        self,
        player_id: int,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> tuple[Any, ...] | None:
        with self._lock:
            with self._sqlite_connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        player_id, player_name, team, season, as_of_date, window_key, position_group,
                        mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                        three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                        ft_pct, turnovers_pg, plus_minus_pg
                    FROM player_cards_windowed
                    WHERE player_id = ? AND window_key = ?
                    ORDER BY as_of_date DESC, season DESC
                    LIMIT 1
                    """,
                    (player_id, window.value),
                ).fetchone()
                if row is not None or window != PlayerCardWindow.season:
                    return row
                # Backward compatibility: read legacy season cards table if windowed rows are absent.
                legacy_row = conn.execute(
                    """
                    SELECT
                        player_id, player_name, team, season, as_of_date, 'season' AS window_key, position_group,
                        mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                        three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                        ft_pct, turnovers_pg, plus_minus_pg
                    FROM player_cards
                    WHERE player_id = ?
                    ORDER BY as_of_date DESC, season DESC
                    LIMIT 1
                    """,
                    (player_id,),
                ).fetchone()
                return legacy_row

    def _sqlite_get_player_card_as_of_row(
        self,
        player_id: int,
        as_of_date: date,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> tuple[Any, ...] | None:
        with self._lock:
            with self._sqlite_connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        player_id, player_name, team, season, as_of_date, window_key, position_group,
                        mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                        three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                        ft_pct, turnovers_pg, plus_minus_pg
                    FROM player_cards_windowed
                    WHERE player_id = ? AND as_of_date <= ? AND window_key = ?
                    ORDER BY as_of_date DESC, season DESC
                    LIMIT 1
                    """,
                    (player_id, as_of_date.isoformat(), window.value),
                ).fetchone()
                if row is not None or window != PlayerCardWindow.season:
                    return row
                # Backward compatibility: read legacy season cards table if windowed rows are absent.
                legacy_row = conn.execute(
                    """
                    SELECT
                        player_id, player_name, team, season, as_of_date, 'season' AS window_key, position_group,
                        mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                        three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                        ft_pct, turnovers_pg, plus_minus_pg
                    FROM player_cards
                    WHERE player_id = ? AND as_of_date <= ?
                    ORDER BY as_of_date DESC, season DESC
                    LIMIT 1
                    """,
                    (player_id, as_of_date.isoformat()),
                ).fetchone()
                return legacy_row

    def _postgres_get_snapshot_row(self, slate_date: date, window: Window) -> Any | None:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT payload
                        FROM matchup_snapshots
                        WHERE slate_date = %s AND window_key = %s
                        """,
                        (slate_date.isoformat(), window.value),
                    )
                    return cursor.fetchone()

    def _postgres_upsert_snapshot(self, slate_date: date, window: Window, payload: str, updated_at: str) -> None:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO matchup_snapshots (slate_date, window_key, payload, updated_at)
                        VALUES (%s, %s, %s::jsonb, %s)
                        ON CONFLICT(slate_date, window_key)
                        DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                        """,
                        (slate_date.isoformat(), window.value, payload, updated_at),
                    )
                conn.commit()

    def _postgres_delete_slate(self, slate_date: date) -> int:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM matchup_snapshots
                        WHERE slate_date = %s
                        """,
                        (slate_date.isoformat(),),
                    )
                    deleted = int(cursor.rowcount or 0)
                conn.commit()
                return deleted

    def _postgres_upsert_player_cards(self, cards: list[PlayerCardResponse]) -> int:
        now = datetime.now(UTC)
        rows = [
            (
                card.player_id,
                card.player_name,
                card.team,
                card.season,
                card.as_of_date,
                card.window.value,
                card.position_group,
                card.mpg,
                card.ppg,
                card.assists_pg,
                card.rebounds_pg,
                card.steals_pg,
                card.blocks_pg,
                card.three_pa_pg,
                card.three_pm_pg,
                card.fta_pg,
                card.ftm_pg,
                card.fg_pct,
                card.three_p_pct,
                card.ft_pct,
                card.turnovers_pg,
                card.plus_minus_pg,
                now,
            )
            for card in cards
        ]
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO player_cards_windowed (
                            player_id, player_name, team, season, as_of_date, window_key, position_group,
                            mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                            three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                            ft_pct, turnovers_pg, plus_minus_pg, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(player_id, season, as_of_date, window_key)
                        DO UPDATE SET
                            player_name = excluded.player_name,
                            team = excluded.team,
                            position_group = excluded.position_group,
                            mpg = excluded.mpg,
                            ppg = excluded.ppg,
                            assists_pg = excluded.assists_pg,
                            rebounds_pg = excluded.rebounds_pg,
                            steals_pg = excluded.steals_pg,
                            blocks_pg = excluded.blocks_pg,
                            three_pa_pg = excluded.three_pa_pg,
                            three_pm_pg = excluded.three_pm_pg,
                            fta_pg = excluded.fta_pg,
                            ftm_pg = excluded.ftm_pg,
                            fg_pct = excluded.fg_pct,
                            three_p_pct = excluded.three_p_pct,
                            ft_pct = excluded.ft_pct,
                            turnovers_pg = excluded.turnovers_pg,
                            plus_minus_pg = excluded.plus_minus_pg,
                            updated_at = excluded.updated_at
                        """,
                        rows,
                    )
                conn.commit()
        return len(rows)

    def _postgres_get_latest_player_card_row(
        self,
        player_id: int,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> Any | None:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            player_id, player_name, team, season, as_of_date, window_key, position_group,
                            mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                            three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                            ft_pct, turnovers_pg, plus_minus_pg
                        FROM player_cards_windowed
                        WHERE player_id = %s AND window_key = %s
                        ORDER BY as_of_date DESC, season DESC
                        LIMIT 1
                        """,
                        (player_id, window.value),
                    )
                    row = cursor.fetchone()
                    if row is not None or window != PlayerCardWindow.season:
                        return row
                    # Backward compatibility: read legacy season cards table if windowed rows are absent.
                    cursor.execute(
                        """
                        SELECT
                            player_id, player_name, team, season, as_of_date, 'season' AS window_key, position_group,
                            mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                            three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                            ft_pct, turnovers_pg, plus_minus_pg
                        FROM player_cards
                        WHERE player_id = %s
                        ORDER BY as_of_date DESC, season DESC
                        LIMIT 1
                        """,
                        (player_id,),
                    )
                    return cursor.fetchone()

    def _postgres_get_player_card_as_of_row(
        self,
        player_id: int,
        as_of_date: date,
        window: PlayerCardWindow = PlayerCardWindow.season,
    ) -> Any | None:
        with self._lock:
            with self._postgres_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            player_id, player_name, team, season, as_of_date, window_key, position_group,
                            mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                            three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                            ft_pct, turnovers_pg, plus_minus_pg
                        FROM player_cards_windowed
                        WHERE player_id = %s AND as_of_date <= %s AND window_key = %s
                        ORDER BY as_of_date DESC, season DESC
                        LIMIT 1
                        """,
                        (player_id, as_of_date, window.value),
                    )
                    row = cursor.fetchone()
                    if row is not None or window != PlayerCardWindow.season:
                        return row
                    # Backward compatibility: read legacy season cards table if windowed rows are absent.
                    cursor.execute(
                        """
                        SELECT
                            player_id, player_name, team, season, as_of_date, 'season' AS window_key, position_group,
                            mpg, ppg, assists_pg, rebounds_pg, steals_pg, blocks_pg,
                            three_pa_pg, three_pm_pg, fta_pg, ftm_pg, fg_pct, three_p_pct,
                            ft_pct, turnovers_pg, plus_minus_pg
                        FROM player_cards
                        WHERE player_id = %s AND as_of_date <= %s
                        ORDER BY as_of_date DESC, season DESC
                        LIMIT 1
                        """,
                        (player_id, as_of_date),
                    )
                    return cursor.fetchone()

    def _sqlite_connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        return sqlite3.connect(str(self._db_path), timeout=20)

    def _postgres_connect(self):
        if not self._database_url:
            raise ValueError("PostgreSQL backend requires database_url")
        try:
            import psycopg
        except Exception as exc:
            raise RuntimeError(
                "psycopg is required for PostgreSQL. Install backend requirements."
            ) from exc
        return psycopg.connect(self._database_url, connect_timeout=5)

    @staticmethod
    def _is_postgres_url(url: str) -> bool:
        lowered = url.lower()
        return lowered.startswith("postgresql://") or lowered.startswith("postgres://")

    @staticmethod
    def _sqlite_path_from_url(url: str) -> Path:
        if not url.startswith("sqlite:///"):
            raise ValueError(f"Unsupported DATABASE_URL: {url}")
        raw_path = url.replace("sqlite:///", "", 1)
        return Path(raw_path)

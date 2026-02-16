"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchMatchups, fetchMeta, fetchPlayerCard, refreshSlate } from "@/lib/api";
import type { MatchupResponse, MetaResponse, PlayerCardResponse, Tier, WindowType } from "@/lib/types";

const STATS = ["PTS", "REB", "AST", "3PM", "STL", "BLK"];
const TEAM_ALIASES: Record<string, string[]> = {
  ATL: ["atl", "atlanta", "hawks", "atlanta hawks"],
  BKN: ["bkn", "brooklyn", "nets", "brooklyn nets"],
  BOS: ["bos", "boston", "celtics", "boston celtics", "boston celitcs"],
  CHA: ["cha", "charlotte", "hornets", "charlotte hornets"],
  CHI: ["chi", "chicago", "bulls", "chicago bulls"],
  CLE: ["cle", "cleveland", "cavaliers", "cleveland cavaliers", "cavs"],
  DAL: ["dal", "dallas", "mavericks", "dallas mavericks", "mavs"],
  DEN: ["den", "denver", "nuggets", "denver nuggets"],
  DET: ["det", "detroit", "pistons", "detroit pistons"],
  GSW: ["gsw", "golden state", "warriors", "golden state warriors"],
  HOU: ["hou", "houston", "rockets", "houston rockets"],
  IND: ["ind", "indiana", "pacers", "indiana pacers"],
  LAC: ["lac", "la clippers", "los angeles clippers", "clippers"],
  LAL: ["lal", "la lakers", "los angeles lakers", "lakers"],
  MEM: ["mem", "memphis", "grizzlies", "memphis grizzlies"],
  MIA: ["mia", "miami", "heat", "miami heat"],
  MIL: ["mil", "milwaukee", "bucks", "milwaukee bucks"],
  MIN: ["min", "minnesota", "timberwolves", "wolves", "minnesota timberwolves"],
  NOP: ["nop", "new orleans", "pelicans", "new orleans pelicans"],
  NYK: ["nyk", "new york", "knicks", "new york knicks"],
  OKC: ["okc", "oklahoma city", "thunder", "oklahoma city thunder"],
  ORL: ["orl", "orlando", "magic", "orlando magic"],
  PHI: ["phi", "philadelphia", "76ers", "sixers", "philadelphia 76ers"],
  PHX: ["phx", "phoenix", "suns", "phoenix suns"],
  POR: ["por", "portland", "trail blazers", "blazers", "portland trail blazers"],
  SAC: ["sac", "sacramento", "kings", "sacramento kings"],
  SAS: ["sas", "san antonio", "spurs", "san antonio spurs"],
  TOR: ["tor", "toronto", "raptors", "toronto raptors"],
  UTA: ["uta", "utah", "jazz", "utah jazz"],
  WAS: ["was", "washington", "wizards", "washington wizards"],
};
type SortDirection = "asc" | "desc";
type SortKey =
  | "player_name"
  | "team"
  | "opponent"
  | "position_group"
  | "avg_minutes"
  | "environment_score"
  | "PTS"
  | "REB"
  | "AST"
  | "3PM"
  | "STL"
  | "BLK";

function tierClass(tier: Tier): string {
  if (tier === "green") return "tier tier-green";
  if (tier === "yellow") return "tier tier-yellow";
  if (tier === "orange") return "tier tier-orange";
  return "tier tier-red";
}

function rankChip(rank: number): string {
  return `#${rank}`;
}

function normalizeSearchValue(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function matchesPlayerOrTeamSearch(playerName: string, teamAbbr: string, query: string): boolean {
  const normalizedQuery = normalizeSearchValue(query);
  if (!normalizedQuery) return true;
  const compactQuery = normalizedQuery.replace(/\s+/g, "");

  const normalizedName = normalizeSearchValue(playerName);
  if (normalizedName.includes(normalizedQuery) || normalizedName.replace(/\s+/g, "").includes(compactQuery)) {
    return true;
  }

  const aliases = TEAM_ALIASES[teamAbbr] ?? [teamAbbr];
  return aliases.some((alias) => {
    const normalizedAlias = normalizeSearchValue(alias);
    return (
      normalizedAlias.includes(normalizedQuery) ||
      normalizedAlias.replace(/\s+/g, "").includes(compactQuery)
    );
  });
}

export default function HomePage() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [data, setData] = useState<MatchupResponse | null>(null);
  const [date, setDate] = useState("");
  const [windowType, setWindowType] = useState<WindowType>("season");
  const [playerSearch, setPlayerSearch] = useState("");
  const [selectedMatchup, setSelectedMatchup] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("PTS");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cardLoading, setCardLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cardError, setCardError] = useState<string | null>(null);
  const [selectedCard, setSelectedCard] = useState<PlayerCardResponse | null>(null);

  useEffect(() => {
    const loadMeta = async () => {
      try {
        const metaResponse = await fetchMeta();
        setMeta(metaResponse);
        setDate(metaResponse.current_date_et);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load metadata.");
      }
    };
    void loadMeta();
  }, []);

  useEffect(() => {
    if (!date) return;

    const loadMatchups = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchMatchups({
          date,
          window: windowType,
        });
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load matchup data.");
      } finally {
        setLoading(false);
      }
    };

    void loadMatchups();
  }, [date, windowType]);

  useEffect(() => {
    if (!data || !selectedMatchup) return;
    const stillExists = data.games.some(
      (game) => `${game.away_team}-${game.home_team}` === selectedMatchup,
    );
    if (!stillExists) {
      setSelectedMatchup("");
    }
  }, [data, selectedMatchup]);

  const tablePlayers = useMemo(() => {
    if (!data) return [];
    const normalizedQuery = playerSearch.trim();

    const basePlayers = !selectedMatchup
      ? data.players
      : (() => {
          const [away, home] = selectedMatchup.split("-");
          return data.players.filter(
            (player) =>
              (player.team === away && player.opponent === home) ||
              (player.team === home && player.opponent === away),
          );
        })();

    if (!normalizedQuery) {
      return basePlayers;
    }

    return basePlayers.filter((player) =>
      matchesPlayerOrTeamSearch(player.player_name, player.team, normalizedQuery),
    );
  }, [data, selectedMatchup, playerSearch]);

  const sortedTablePlayers = useMemo(() => {
    const rows = [...tablePlayers];
    rows.sort((a, b) => {
      const compareString = (left: string, right: string): number => left.localeCompare(right);
      const compareNumber = (left: number, right: number): number => left - right;

      let value = 0;
      if (sortKey === "player_name") value = compareString(a.player_name, b.player_name);
      else if (sortKey === "team") value = compareString(a.team, b.team);
      else if (sortKey === "opponent") value = compareString(a.opponent, b.opponent);
      else if (sortKey === "position_group") value = compareString(a.position_group, b.position_group);
      else if (sortKey === "avg_minutes") value = compareNumber(a.avg_minutes, b.avg_minutes);
      else if (sortKey === "environment_score") value = compareNumber(a.environment_score, b.environment_score);
      else value = compareNumber(a.stat_ranks[sortKey] ?? 30, b.stat_ranks[sortKey] ?? 30);

      return sortDirection === "asc" ? value : -value;
    });
    return rows;
  }, [tablePlayers, sortDirection, sortKey]);

  const onSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection("asc");
  };

  const sortLabel = (key: SortKey): string => {
    if (sortKey !== key) return "";
    return sortDirection === "asc" ? " ▲" : " ▼";
  };

  const onRefresh = async () => {
    if (!date) return;
    setRefreshing(true);
    setError(null);
    try {
      await refreshSlate(date);
      const result = await fetchMatchups({
        date,
        window: windowType,
      });
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setRefreshing(false);
    }
  };

  const onPlayerClick = async (playerId: number) => {
    setCardLoading(true);
    setCardError(null);
    try {
      const card = await fetchPlayerCard(playerId);
      setSelectedCard(card);
    } catch (err) {
      setCardError(err instanceof Error ? err.message : "Failed to load player card.");
      setSelectedCard(null);
    } finally {
      setCardLoading(false);
    }
  };

  return (
    <main className="page">
      <section className="hero">
        <h1>NBA Matchup Finder</h1>
        <p>
          Daily matchup ranks grouped by Guards / Forwards / Centers.
        </p>
      </section>

      <section className="panel controls">
        <div className="control-row">
          <label>
            Date
            <input
              type="date"
              value={date}
              min={meta?.season_start}
              max={meta?.season_end}
              onChange={(event) => setDate(event.target.value)}
            />
          </label>

          <label>
            Window
            <select value={windowType} onChange={(event) => setWindowType(event.target.value as WindowType)}>
              <option value="season">Season</option>
              <option value="last10">Last 10</option>
            </select>
          </label>

          <label>
            Search
            <input
              type="text"
              value={playerSearch}
              onChange={(event) => setPlayerSearch(event.target.value)}
              placeholder="Player or Team"
            />
          </label>

          <label>
            Refresh
            <button type="button" onClick={onRefresh} disabled={refreshing || !date}>
              {refreshing ? "Refreshing..." : "Refresh Slate"}
            </button>
          </label>
        </div>
      </section>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="status">Loading matchup data...</p> : null}

      {!loading && data ? (
        <>
          <section className="panel slate-summary">
            <h2>
              Slate: {data.slate_date} ({data.games.length} games)
            </h2>
            <p>
              Built from data available through <strong>{data.as_of_date}</strong> with <strong>{data.window}</strong>{" "}
              window.
            </p>
            <div className="games">
              {data.games.map((game) => (
                <button
                  key={game.game_id}
                  type="button"
                  className={`game-pill ${selectedMatchup === `${game.away_team}-${game.home_team}` ? "active" : ""}`}
                  onClick={() => {
                    const key = `${game.away_team}-${game.home_team}`;
                    setSelectedMatchup((current) => (current === key ? "" : key));
                  }}
                >
                  {game.away_team} @ {game.home_team}
                </button>
              ))}
            </div>
          </section>

          <section className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("player_name")}>
                      Player{sortLabel("player_name")}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("team")}>
                      Team{sortLabel("team")}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("opponent")}>
                      Opp{sortLabel("opponent")}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("position_group")}>
                      Pos{sortLabel("position_group")}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("avg_minutes")}>
                      MPG{sortLabel("avg_minutes")}
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => onSort("environment_score")}>
                      Env{sortLabel("environment_score")}
                    </button>
                  </th>
                  {STATS.map((header) => (
                    <th key={header}>
                      <button type="button" className="sort-button" onClick={() => onSort(header as SortKey)}>
                        {header}
                        {sortLabel(header as SortKey)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedTablePlayers.map((player) => (
                  <tr
                    key={`${player.player_id}-${player.position_group}`}
                    className="player-row"
                    onClick={() => void onPlayerClick(player.player_id)}
                  >
                    <td>
                      {player.player_name}
                      {player.injury_status ? <span className="injury">{player.injury_status}</span> : null}
                    </td>
                    <td>{player.team}</td>
                    <td>{player.opponent}</td>
                    <td>{player.position_group}</td>
                    <td>{player.avg_minutes.toFixed(1)}</td>
                    <td>{player.environment_score.toFixed(1)}</td>
                    {STATS.map((name) => {
                      const tierValue = player.stat_tiers[name] ?? "red";
                      const rank = player.stat_ranks[name] ?? 30;
                      const allowed = player.stat_allowed[name] ?? 0;
                      return (
                        <td key={`${player.player_id}-${name}`}>
                          <span className={tierClass(tierValue)}>{rankChip(rank)}</span>
                          <small>{allowed.toFixed(1)} allowed</small>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {data.injuries.length > 0 ? (
            <section className="panel injuries">
              <h2>Injury Notes</h2>
              <div className="injury-grid">
                {data.injuries.slice(0, 60).map((injuryItem) => (
                  <p key={`${injuryItem.team}-${injuryItem.player_name}`}>
                    <strong>{injuryItem.team}</strong> {injuryItem.player_name}: {injuryItem.status}
                  </p>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : null}

      {cardLoading ? <p className="status">Loading player card...</p> : null}
      {cardError ? <p className="error">{cardError}</p> : null}

      {selectedCard ? (
        <section className="card-overlay" onClick={() => setSelectedCard(null)}>
          <article className="player-card panel" onClick={(event) => event.stopPropagation()}>
            <div className="player-card-header">
              <div>
                <h2>{selectedCard.player_name}</h2>
                <p>
                  {selectedCard.team} | {selectedCard.position_group} | Season {selectedCard.season}
                </p>
              </div>
              <button type="button" onClick={() => setSelectedCard(null)}>
                Close
              </button>
            </div>

            <div className="player-card-grid">
              <p>MPG: {selectedCard.mpg.toFixed(1)}</p>
              <p>PPG: {selectedCard.ppg.toFixed(1)}</p>
              <p>APG: {selectedCard.assists_pg.toFixed(1)}</p>
              <p>RPG: {selectedCard.rebounds_pg.toFixed(1)}</p>
              <p>SPG: {selectedCard.steals_pg.toFixed(1)}</p>
              <p>BPG: {selectedCard.blocks_pg.toFixed(1)}</p>
              <p>3PA/G: {selectedCard.three_pa_pg.toFixed(1)}</p>
              <p>3PM/G: {selectedCard.three_pm_pg.toFixed(1)}</p>
              <p>FTA/G: {selectedCard.fta_pg.toFixed(1)}</p>
              <p>FTM/G: {selectedCard.ftm_pg.toFixed(1)}</p>
              <p>FG%: {(selectedCard.fg_pct * 100).toFixed(1)}%</p>
              <p>3P%: {(selectedCard.three_p_pct * 100).toFixed(1)}%</p>
              <p>FT%: {(selectedCard.ft_pct * 100).toFixed(1)}%</p>
              <p>TOV/G: {selectedCard.turnovers_pg.toFixed(1)}</p>
              <p>+/-: {selectedCard.plus_minus_pg.toFixed(1)}</p>
              <p>As Of: {selectedCard.as_of_date}</p>
            </div>
          </article>
        </section>
      ) : null}
    </main>
  );
}

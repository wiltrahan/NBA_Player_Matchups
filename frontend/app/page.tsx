"use client";

import { type CSSProperties, useEffect, useMemo, useState } from "react";
import { fetchMatchups, fetchMeta, fetchPlayerCard, refreshSlate } from "@/lib/api";
import type { MatchupResponse, MetaResponse, PlayerCardResponse, WindowType } from "@/lib/types";
import { DensityToggle } from "./components/DensityToggle";
import { PageLayout } from "./components/PageLayout";
import { RankLegend } from "./components/RankLegend";
import { RankPill } from "./components/RankPill";
import { ThemeToggle } from "./components/ThemeToggle";
import { Button } from "./components/controls/Button";
import { Input } from "./components/controls/Input";
import { Select } from "./components/controls/Select";

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

const TEAM_COLORS: Record<string, string> = {
  ATL: "#e03a3e",
  BKN: "#7a7a7a",
  BOS: "#007a33",
  CHA: "#1d1160",
  CHI: "#ce1141",
  CLE: "#6f263d",
  DAL: "#00538c",
  DEN: "#0e2240",
  DET: "#c8102e",
  GSW: "#1d428a",
  HOU: "#ce1141",
  IND: "#002d62",
  LAC: "#c8102e",
  LAL: "#552583",
  MEM: "#5d76a9",
  MIA: "#98002e",
  MIL: "#00471b",
  MIN: "#0c2340",
  NOP: "#0c2340",
  NYK: "#006bb6",
  OKC: "#007ac1",
  ORL: "#0077c0",
  PHI: "#006bb6",
  PHX: "#1d1160",
  POR: "#e03a3e",
  SAC: "#5a2d81",
  SAS: "#7a7a7a",
  TOR: "#ce1141",
  UTA: "#002b5c",
  WAS: "#002b5c",
};
type SortDirection = "asc" | "desc";
type Density = "comfortable" | "compact";
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

const SKELETON_ROWS = 8;

function normalizeSearchValue(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function formatDateDisplay(value: string): string {
  const parts = value.split("-");
  if (parts.length !== 3) return value;
  const [year, month, day] = parts;
  if (!year || !month || !day) return value;
  return `${month}/${day}/${year}`;
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

function teamAccent(team: string): string {
  return TEAM_COLORS[team] ?? "#4f7ce5";
}

function isPositionEmphasis(positionGroup: string, statLabel: string): boolean {
  const byPosition: Record<string, string[]> = {
    Guards: ["APG", "3PA/G", "3PM/G", "FT%"],
    Forwards: ["PPG", "RPG", "FG%"],
    Centers: ["RPG", "BPG", "FG%", "FTA/G"],
  };
  return (byPosition[positionGroup] ?? []).includes(statLabel);
}

function statTooltip(label: string): string | undefined {
  const tips: Record<string, string> = {
    "TOV/G": "Turnovers per game.",
    "+/-": "Average on-court point differential.",
    "3PA/G": "Three-point attempts per game.",
    "3PM/G": "Three-pointers made per game.",
    "FTA/G": "Free throw attempts per game.",
    "FTM/G": "Free throws made per game.",
  };
  return tips[label];
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
  const [density, setDensity] = useState<Density>("comfortable");
  const [filtersExpanded, setFiltersExpanded] = useState(true);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cardLoading, setCardLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cardError, setCardError] = useState<string | null>(null);
  const [selectedCard, setSelectedCard] = useState<PlayerCardResponse | null>(null);
  const [activePlayerRowId, setActivePlayerRowId] = useState<number | null>(null);
  const [isCardClosing, setIsCardClosing] = useState(false);

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
    setActivePlayerRowId(playerId);
    setIsCardClosing(false);
    setCardLoading(true);
    setCardError(null);
    try {
      const card = await fetchPlayerCard(playerId);
      setSelectedCard(card);
    } catch (err) {
      setCardError(err instanceof Error ? err.message : "Failed to load player card.");
      setSelectedCard(null);
      setActivePlayerRowId(null);
    } finally {
      setCardLoading(false);
    }
  };

  const closePlayerCard = () => {
    if (!selectedCard || isCardClosing) return;
    setIsCardClosing(true);
    window.setTimeout(() => {
      setSelectedCard(null);
      setIsCardClosing(false);
      setActivePlayerRowId(null);
    }, 160);
  };

  const hasVisiblePlayers = sortedTablePlayers.length > 0;

  return (
    <>
      <PageLayout
        header={
          <div className="hero">
            <div className="hero-top">
              <div>
                <h1>NBA Matchup Finder</h1>
                <p>Daily matchup ranks grouped by Guards / Forwards / Centers.</p>
              </div>
              <div className="header-actions">
                <ThemeToggle />
                <Button type="button" onClick={onRefresh} disabled={refreshing || !date} loading={refreshing} variant="primary" className="refresh-button">
                  {refreshing ? "Refreshing..." : "Refresh Slate"}
                </Button>
              </div>
            </div>
          </div>
        }
        filters={
          <div className="controls">
            <div className="filters-header">
              <h2>Filter Bar</h2>
              <button
                type="button"
                className="filters-toggle"
                aria-expanded={filtersExpanded}
                aria-controls="filter-controls"
                onClick={() => setFiltersExpanded((current) => !current)}
              >
                {filtersExpanded ? "Hide" : "Show"}
              </button>
            </div>
            <div id="filter-controls" className={`control-row ${filtersExpanded ? "expanded" : "collapsed"}`}>
              <label>
                Date
                <Input
                  type="date"
                  value={date}
                  min={meta?.season_start}
                  max={meta?.season_end}
                  onChange={(event) => setDate(event.target.value)}
                />
              </label>

              <label>
                Window
                <Select value={windowType} onChange={(event) => setWindowType(event.target.value as WindowType)}>
                  <option value="season">Season</option>
                  <option value="last10">Last 10</option>
                </Select>
              </label>

              <label>
                Search
                <Input
                  type="text"
                  value={playerSearch}
                  onChange={(event) => setPlayerSearch(event.target.value)}
                  placeholder="Player or Team"
                  leadingIcon={
                    <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
                      <path
                        d="M13.7 12.3a5.75 5.75 0 1 0-1.4 1.4l3.6 3.6a1 1 0 0 0 1.4-1.4l-3.6-3.6ZM3.75 8.5a4.75 4.75 0 1 1 9.5 0 4.75 4.75 0 0 1-9.5 0Z"
                        fill="currentColor"
                      />
                    </svg>
                  }
                  trailingControl={
                    playerSearch ? (
                      <button
                        type="button"
                        className="input-clear"
                        onClick={() => setPlayerSearch("")}
                        aria-label="Clear search"
                      >
                        Clear
                      </button>
                    ) : null
                  }
                />
              </label>
            </div>
          </div>
        }
        slate={
          !loading && data ? (
            <div className="slate-summary">
              <h2>
                Slate: {formatDateDisplay(data.slate_date)} ({data.games.length} games)
              </h2>
              <p>
                Built from data available through <strong>{formatDateDisplay(data.as_of_date)}</strong> with{" "}
                <strong>{data.window}</strong> window.
              </p>
              <div className="chip-scroll">
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
              </div>
            </div>
          ) : (
            <div className="slate-summary">
              <h2>Slate</h2>
              <p>Choose a date and window to load matchups.</p>
            </div>
          )
        }
        content={
          <>
            {error ? (
              <p className="error">
                {error} Try selecting a different date window or refreshing the slate.
              </p>
            ) : null}
            <div className="table-toolbar">
              <h2>Player Matchups</h2>
              <DensityToggle value={density} onChange={setDensity} />
            </div>
            <RankLegend />
            {loading ? (
              <>
                <p className="status">Loading matchup data...</p>
                <div className={`table-wrap desktop-table ${density === "compact" ? "table-compact" : "table-comfortable"}`}>
                  <table>
                    <thead>
                      <tr>
                        <th>Player</th>
                        <th>Team</th>
                        <th>Opp</th>
                        <th>Pos</th>
                        <th className="num-col">MPG</th>
                        <th className="num-col">Env</th>
                        {STATS.map((header) => (
                          <th key={header} className="num-col">
                            {header}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Array.from({ length: SKELETON_ROWS }).map((_, index) => (
                        <tr key={`skeleton-row-${index}`} className="skeleton-row">
                          <td><span className="skeleton-block skeleton-text-long" /></td>
                          <td><span className="skeleton-block skeleton-text-short" /></td>
                          <td><span className="skeleton-block skeleton-text-short" /></td>
                          <td><span className="skeleton-block skeleton-text-short" /></td>
                          <td className="num-cell"><span className="skeleton-block skeleton-chip" /></td>
                          <td className="num-cell"><span className="skeleton-block skeleton-chip" /></td>
                          {STATS.map((stat) => (
                            <td key={`skeleton-${index}-${stat}`} className="num-cell">
                              <span className="skeleton-block skeleton-pill" />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mobile-cards">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <article key={`mobile-skeleton-${index}`} className="mobile-player-card skeleton-card">
                      <span className="skeleton-block skeleton-text-long" />
                      <span className="skeleton-block skeleton-text-short" />
                      <div className="mobile-meta">
                        <span className="skeleton-block skeleton-chip" />
                        <span className="skeleton-block skeleton-chip" />
                        <span className="skeleton-block skeleton-chip" />
                      </div>
                      <div className="mobile-stat-grid">
                        {STATS.map((stat) => (
                          <p key={`mobile-skeleton-stat-${index}-${stat}`}>
                            <span className="skeleton-block skeleton-text-short" />
                            <span className="skeleton-block skeleton-pill" />
                          </p>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : null}
            {!loading && data && hasVisiblePlayers ? (
              <>
                <div className={`table-wrap desktop-table ${density === "compact" ? "table-compact" : "table-comfortable"}`}>
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
                        <th className="num-col">
                          <button type="button" className="sort-button" onClick={() => onSort("avg_minutes")}>
                            MPG{sortLabel("avg_minutes")}
                          </button>
                        </th>
                        <th className="num-col">
                          <button type="button" className="sort-button" onClick={() => onSort("environment_score")}>
                            Env{sortLabel("environment_score")}
                          </button>
                        </th>
                        {STATS.map((header) => (
                          <th key={header} className="num-col">
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
                          className={`player-row ${activePlayerRowId === player.player_id ? "is-active" : ""}`}
                          onClick={() => void onPlayerClick(player.player_id)}
                        >
                          <td>
                            {player.player_name}
                            {player.injury_status ? <span className="injury">{player.injury_status}</span> : null}
                          </td>
                          <td>{player.team}</td>
                          <td>{player.opponent}</td>
                          <td>{player.position_group}</td>
                          <td className="num-cell">{player.avg_minutes.toFixed(1)}</td>
                          <td className="num-cell">{player.environment_score.toFixed(1)}</td>
                          {STATS.map((name) => {
                            const tierValue = player.stat_tiers[name] ?? "red";
                            const rank = player.stat_ranks[name] ?? 30;
                            const allowed = player.stat_allowed[name] ?? 0;
                            return (
                              <td key={`${player.player_id}-${name}`} className="num-cell">
                                <RankPill tier={tierValue} rank={rank} allowed={allowed} />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="mobile-cards">
                  {sortedTablePlayers.map((player) => (
                    <article
                      key={`${player.player_id}-${player.position_group}-mobile`}
                      className={`mobile-player-card ${activePlayerRowId === player.player_id ? "is-active" : ""}`}
                      onClick={() => void onPlayerClick(player.player_id)}
                    >
                      <div className="mobile-player-top">
                        <h3>
                          {player.player_name}
                          {player.injury_status ? <span className="injury">{player.injury_status}</span> : null}
                        </h3>
                        <p>
                          {player.team} vs {player.opponent}
                        </p>
                      </div>
                      <div className="mobile-meta">
                        <span>{player.position_group}</span>
                        <span>MPG {player.avg_minutes.toFixed(1)}</span>
                        <span>ENV {player.environment_score.toFixed(1)}</span>
                      </div>
                      <div className="mobile-stat-grid">
                        {STATS.map((name) => {
                          const tierValue = player.stat_tiers[name] ?? "red";
                          const rank = player.stat_ranks[name] ?? 30;
                          const allowed = player.stat_allowed[name] ?? 0;
                          return (
                            <p key={`${player.player_id}-${name}-mobile`}>
                              <strong>{name}</strong>
                              <RankPill tier={tierValue} rank={rank} allowed={allowed} />
                            </p>
                          );
                        })}
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : null}
            {!loading && data && !hasVisiblePlayers ? (
              <div className="empty-state">
                <h3>No players match this filter</h3>
                <p>Clear the matchup or search filters to see the full slate.</p>
              </div>
            ) : null}
          </>
        }
        injuries={
          !loading && data && data.injuries.length > 0 ? (
            <>
              <h2>Injury Notes</h2>
              <div className="injury-grid">
                {data.injuries.slice(0, 60).map((injuryItem) => (
                  <p key={`${injuryItem.team}-${injuryItem.player_name}`}>
                    <strong>{injuryItem.team}</strong> {injuryItem.player_name}: {injuryItem.status}
                  </p>
                ))}
              </div>
            </>
          ) : undefined
        }
      />

      {cardLoading ? <p className="status">Loading player card...</p> : null}
      {cardError ? <p className="error">{cardError}</p> : null}

      <div className="mobile-sticky-refresh">
        <Button
          type="button"
          onClick={onRefresh}
          disabled={refreshing || !date}
          loading={refreshing}
          variant="primary"
          className="mobile-refresh-button"
        >
          {refreshing ? "Refreshing..." : "Refresh Slate"}
        </Button>
      </div>

      {selectedCard ? (
        <section className={`card-overlay ${isCardClosing ? "is-closing" : "is-open"}`} onClick={closePlayerCard}>
          <article
            className="player-card panel"
            style={{ "--team-accent": teamAccent(selectedCard.team) } as CSSProperties}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="player-card-header">
              <div className="player-card-identity">
                <h2>{selectedCard.player_name}</h2>
                <div className="player-card-meta">
                  <span>{selectedCard.team}</span>
                  <span>{selectedCard.position_group}</span>
                  <span>Season {selectedCard.season}</span>
                </div>
              </div>
              <Button type="button" variant="secondary" onClick={closePlayerCard} className="player-card-close">
                Close
              </Button>
            </div>

            <div className="player-card-lead-grid">
              <div className={`player-kpi ${isPositionEmphasis(selectedCard.position_group, "MPG") ? "is-emphasis" : ""}`}>
                <span>MPG</span>
                <strong>{selectedCard.mpg.toFixed(1)}</strong>
              </div>
              <div className={`player-kpi ${isPositionEmphasis(selectedCard.position_group, "PPG") ? "is-emphasis" : ""}`}>
                <span>PPG</span>
                <strong>{selectedCard.ppg.toFixed(1)}</strong>
              </div>
              <div className={`player-kpi ${isPositionEmphasis(selectedCard.position_group, "APG") ? "is-emphasis" : ""}`}>
                <span>APG</span>
                <strong>{selectedCard.assists_pg.toFixed(1)}</strong>
              </div>
              <div className={`player-kpi ${isPositionEmphasis(selectedCard.position_group, "RPG") ? "is-emphasis" : ""}`}>
                <span>RPG</span>
                <strong>{selectedCard.rebounds_pg.toFixed(1)}</strong>
              </div>
            </div>

            <div className="player-card-sections">
              <section className="player-card-block player-card-block-scoring">
                <h3>Scoring</h3>
                <div className="player-card-grid">
                  <p className={isPositionEmphasis(selectedCard.position_group, "PPG") ? "is-emphasis" : ""}><span title={statTooltip("PPG")}>PPG</span><strong>{selectedCard.ppg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "3PM/G") ? "is-emphasis" : ""}><span title={statTooltip("3PM/G")}>3PM/G</span><strong>{selectedCard.three_pm_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "FTM/G") ? "is-emphasis" : ""}><span title={statTooltip("FTM/G")}>FTM/G</span><strong>{selectedCard.ftm_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "+/-") ? "is-emphasis" : ""}><span title={statTooltip("+/-")}>+/-</span><strong>{selectedCard.plus_minus_pg.toFixed(1)}</strong></p>
                </div>
              </section>

              <section className="player-card-block player-card-block-efficiency">
                <h3>Shooting Efficiency</h3>
                <div className="player-card-grid player-card-grid-wide">
                  <p className={isPositionEmphasis(selectedCard.position_group, "FG%") ? "is-emphasis" : ""}><span>FG%</span><strong>{(selectedCard.fg_pct * 100).toFixed(1)}%</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "3P%") ? "is-emphasis" : ""}><span>3P%</span><strong>{(selectedCard.three_p_pct * 100).toFixed(1)}%</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "FT%") ? "is-emphasis" : ""}><span>FT%</span><strong>{(selectedCard.ft_pct * 100).toFixed(1)}%</strong></p>
                </div>
              </section>

              <section className="player-card-block player-card-block-usage">
                <h3>Usage / Volume</h3>
                <div className="player-card-grid">
                  <p className={isPositionEmphasis(selectedCard.position_group, "MPG") ? "is-emphasis" : ""}><span>MPG</span><strong>{selectedCard.mpg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "3PA/G") ? "is-emphasis" : ""}><span title={statTooltip("3PA/G")}>3PA/G</span><strong>{selectedCard.three_pa_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "FTA/G") ? "is-emphasis" : ""}><span title={statTooltip("FTA/G")}>FTA/G</span><strong>{selectedCard.fta_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "TOV/G") ? "is-emphasis" : ""}><span title={statTooltip("TOV/G")}>TOV/G</span><strong>{selectedCard.turnovers_pg.toFixed(1)}</strong></p>
                </div>
              </section>

              <section className="player-card-block player-card-block-defense">
                <h3>Defense / Other</h3>
                <div className="player-card-grid player-card-grid-wide">
                  <p className={isPositionEmphasis(selectedCard.position_group, "SPG") ? "is-emphasis" : ""}><span>SPG</span><strong>{selectedCard.steals_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "BPG") ? "is-emphasis" : ""}><span>BPG</span><strong>{selectedCard.blocks_pg.toFixed(1)}</strong></p>
                  <p className={isPositionEmphasis(selectedCard.position_group, "RPG") ? "is-emphasis" : ""}><span>RPG</span><strong>{selectedCard.rebounds_pg.toFixed(1)}</strong></p>
                  <p><span>As Of</span><strong>{selectedCard.as_of_date}</strong></p>
                </div>
              </section>
            </div>
          </article>
        </section>
      ) : null}
    </>
  );
}

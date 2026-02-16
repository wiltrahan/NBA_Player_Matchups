export type WindowType = "season" | "last10";

export type PositionGroup = "Guards" | "Forwards" | "Centers";

export type Tier = "green" | "yellow" | "orange" | "red";

export interface Game {
  game_id: string;
  start_time_utc?: string | null;
  away_team: string;
  home_team: string;
}

export interface InjuryTag {
  player_name: string;
  team: string;
  status: string;
  comment?: string | null;
}

export interface PlayerMatchup {
  player_id: number;
  player_name: string;
  team: string;
  opponent: string;
  position_group: PositionGroup;
  avg_minutes: number;
  injury_status?: string | null;
  environment_score: number;
  stat_ranks: Record<string, number>;
  stat_allowed: Record<string, number>;
  stat_tiers: Record<string, Tier>;
}

export interface MatchupResponse {
  slate_date: string;
  as_of_date: string;
  window: WindowType;
  games: Game[];
  injuries: InjuryTag[];
  players: PlayerMatchup[];
}

export interface MetaResponse {
  season_label: string;
  current_date_et: string;
  season_start: string;
  season_end: string;
}

export interface PlayerCardResponse {
  player_id: number;
  player_name: string;
  team: string;
  season: string;
  as_of_date: string;
  position_group: PositionGroup;
  mpg: number;
  ppg: number;
  assists_pg: number;
  rebounds_pg: number;
  steals_pg: number;
  blocks_pg: number;
  three_pa_pg: number;
  three_pm_pg: number;
  fta_pg: number;
  ftm_pg: number;
  fg_pct: number;
  three_p_pct: number;
  ft_pct: number;
  turnovers_pg: number;
  plus_minus_pg: number;
}

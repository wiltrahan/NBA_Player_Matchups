import type {
  Game,
  MatchupResponse,
  PlayerCardResponse,
  PlayerMatchup,
  PositionGroup,
  Tier,
} from "./types";

const PANEL_STATS = ["PTS", "REB", "AST", "3PM", "STL", "BLK"] as const;
const POSITION_GROUPS: PositionGroup[] = ["Guards", "Forwards", "Centers"];

type PanelStat = (typeof PANEL_STATS)[number];

export type DefenseRankValue = {
  rank: number;
  tier: Tier;
};

export type MatchupPanelData = {
  positionGroup: PositionGroup;
  teamAbbr: string;
  opponentAbbr: string;
  defenseRanks: Record<PanelStat, DefenseRankValue | null>;
  players: MatchupPanelRow[];
};

export type MatchupPanels = {
  homePanels: MatchupPanelData[];
  awayPanels: MatchupPanelData[];
};

type SelectedGame = Pick<Game, "home_team" | "away_team"> | null | undefined;
type PlayerCardLookup = Record<number, PlayerCardResponse | undefined>;

export type MatchupPanelRow = {
  playerId: number;
  playerName: string;
  injuryStatus?: string | null;
  mpg: number;
  ppg: number | null;
  apg: number | null;
  rpg: number | null;
};

function normalizePlayers(matchupData: MatchupResponse | PlayerMatchup[]): PlayerMatchup[] {
  if (Array.isArray(matchupData)) return matchupData;
  return matchupData.players;
}

export function mapPlayerToPanelRow(
  player: PlayerMatchup,
  playerCard?: PlayerCardResponse,
): MatchupPanelRow {
  return {
    playerId: player.player_id,
    playerName: player.player_name,
    injuryStatus: player.injury_status,
    mpg: playerCard?.mpg ?? player.avg_minutes,
    ppg: typeof playerCard?.ppg === "number" ? playerCard.ppg : null,
    apg: typeof playerCard?.assists_pg === "number" ? playerCard.assists_pg : null,
    rpg: typeof playerCard?.rebounds_pg === "number" ? playerCard.rebounds_pg : null,
  };
}

function buildPanel(
  teamAbbr: string,
  opponentAbbr: string,
  positionGroup: PositionGroup,
  players: PlayerMatchup[],
  playerCardsById: PlayerCardLookup,
): MatchupPanelData {
  const panelPlayersRaw = players
    .filter(
      (player) =>
        player.team === teamAbbr &&
        player.opponent === opponentAbbr &&
        player.position_group === positionGroup,
    )
    .sort(
      (left, right) =>
        right.avg_minutes - left.avg_minutes || left.player_name.localeCompare(right.player_name),
    );

  const sample = panelPlayersRaw[0] ?? null;
  const panelPlayers = panelPlayersRaw.map((player) =>
    mapPlayerToPanelRow(player, playerCardsById[player.player_id]),
  );
  const defenseRanks = PANEL_STATS.reduce<Record<PanelStat, DefenseRankValue | null>>((acc, stat) => {
    if (!sample) {
      acc[stat] = null;
      return acc;
    }

    const rank = sample.stat_ranks[stat];
    if (typeof rank !== "number") {
      acc[stat] = null;
      return acc;
    }

    acc[stat] = {
      rank,
      tier: sample.stat_tiers[stat] ?? "red",
    };
    return acc;
  }, {} as Record<PanelStat, DefenseRankValue | null>);

  return {
    positionGroup,
    teamAbbr,
    opponentAbbr,
    defenseRanks,
    players: panelPlayers,
  };
}

export function buildMatchupPanels(
  selectedGame: SelectedGame,
  matchupData: MatchupResponse | PlayerMatchup[],
  playerCardsById: PlayerCardLookup = {},
): MatchupPanels {
  if (!selectedGame) {
    return { homePanels: [], awayPanels: [] };
  }

  const players = normalizePlayers(matchupData);

  const homePanels = POSITION_GROUPS.map((positionGroup) =>
    buildPanel(selectedGame.home_team, selectedGame.away_team, positionGroup, players, playerCardsById),
  );

  const awayPanels = POSITION_GROUPS.map((positionGroup) =>
    buildPanel(selectedGame.away_team, selectedGame.home_team, positionGroup, players, playerCardsById),
  );

  return { homePanels, awayPanels };
}

import { RankPill } from "../RankPill";
import { InjuryStatusBadge } from "../injuries/InjuryStatusBadge";
import type { MatchupPanelData } from "@/lib/matchup_panels";

type MatchupPanelProps = {
  panel: MatchupPanelData;
  activePlayerRowId: number | null;
  onPlayerClick: (playerId: number) => void;
};

const STATS = ["PTS", "REB", "AST", "3PM", "STL", "BLK"] as const;

type InjuryBadge = {
  label: string;
  tone: "danger" | "warning" | "success";
};

function resolveInjuryBadge(status?: string | null): InjuryBadge | null {
  const normalized = (status ?? "").toUpperCase();
  if (!normalized) return null;
  if (normalized.includes("OUT") || normalized.includes("SUSPENSION")) {
    return { label: "+", tone: "danger" };
  }
  if (normalized.includes("DOUBT")) {
    return { label: "D", tone: "danger" };
  }
  if (normalized.includes("QUESTION") || normalized.includes("GTD") || normalized.includes("DAY-TO-DAY")) {
    return { label: "Q", tone: "warning" };
  }
  if (normalized.includes("PROBABLE")) {
    return { label: "P", tone: "success" };
  }
  return null;
}

export function MatchupPanel({
  panel,
  activePlayerRowId,
  onPlayerClick,
}: MatchupPanelProps) {
  const { positionGroup, opponentAbbr, defenseRanks, players } = panel;
  const formatPanelStat = (value: number | null): string => {
    if (value == null || Number.isNaN(value)) return "—";
    return value.toFixed(1);
  };

  return (
    <section className="panel matchup-panel">
      <header className="matchup-panel-header matchup-panel__header">
        <h3>{positionGroup} vs {opponentAbbr}</h3>
      </header>

      <div className="matchup-panel-content">
        <div className="matchup-panel__ranks">
          <div className="matchup-rank-strip">
            <div className="matchup-rank-strip-inner">
              <table className="matchup-rank-table" aria-label={`${positionGroup} defensive rank strip`}>
                <thead>
                  <tr>
                    {STATS.map((stat) => (
                      <th key={`${panel.teamAbbr}-${positionGroup}-${stat}-label`} scope="col">
                        {stat}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    {STATS.map((stat) => {
                      const rankData = defenseRanks[stat];
                      return (
                        <td key={`${panel.teamAbbr}-${positionGroup}-${stat}-value`}>
                          {rankData ? (
                            <RankPill tier={rankData.tier} rank={rankData.rank} />
                          ) : (
                            <div className="matchup-rank-empty">
                              <span>—</span>
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="matchup-panel__table">
          <div className="matchup-scroll-area matchup-player-table-wrap">
            <table className="matchup-player-table" aria-label={`${positionGroup} players`}>
              <thead>
                <tr>
                  <th scope="col">Player</th>
                  <th scope="col" className="num num-col">MPG</th>
                  <th scope="col" className="num num-col">PPG</th>
                  <th scope="col" className="num num-col">APG</th>
                  <th scope="col" className="num num-col">RPG</th>
                </tr>
              </thead>
              <tbody>
                {players.length > 0 ? (
                  players.map((player) => {
                    const badge = resolveInjuryBadge(player.injuryStatus);
                    return (
                      <tr
                        key={`${player.playerId}-${positionGroup}-panel`}
                        className={`player-row matchup-player-row matchup-row ${activePlayerRowId === player.playerId ? "is-active" : ""}`}
                        onClick={() => onPlayerClick(player.playerId)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onPlayerClick(player.playerId);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <td>
                          <span className="matchup-player-name">
                            {player.playerName}
                            {badge ? (
                              <InjuryStatusBadge
                                label={badge.label}
                                tone={badge.tone}
                                tooltip={player.injuryHoverText ?? player.injuryStatus ?? "Injury"}
                              />
                            ) : null}
                          </span>
                        </td>
                        <td className="num num-cell">{formatPanelStat(player.mpg)}</td>
                        <td className="num num-cell">{formatPanelStat(player.ppg)}</td>
                        <td className="num num-cell">{formatPanelStat(player.apg)}</td>
                        <td className="num num-cell">{formatPanelStat(player.rpg)}</td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td className="matchup-empty" colSpan={5}>No players in this position group.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

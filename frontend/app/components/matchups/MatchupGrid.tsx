import type { MatchupPanels } from "@/lib/matchup_panels";
import { MatchupPanel } from "./MatchupPanel";

type MatchupGridProps = {
  panels: MatchupPanels;
  activePlayerRowId: number | null;
  onPlayerClick: (playerId: number) => void;
};

export function MatchupGrid({
  panels,
  activePlayerRowId,
  onPlayerClick,
}: MatchupGridProps) {
  return (
    <div className="matchup-grid-wrap">
      <div className="matchup-grid-row">
        {panels.homePanels.map((panel) => (
          <MatchupPanel
            key={`home-${panel.teamAbbr}-${panel.positionGroup}`}
            panel={panel}
            activePlayerRowId={activePlayerRowId}
            onPlayerClick={onPlayerClick}
          />
        ))}
      </div>

      <div className="matchup-grid-row">
        {panels.awayPanels.map((panel) => (
          <MatchupPanel
            key={`away-${panel.teamAbbr}-${panel.positionGroup}`}
            panel={panel}
            activePlayerRowId={activePlayerRowId}
            onPlayerClick={onPlayerClick}
          />
        ))}
      </div>
    </div>
  );
}

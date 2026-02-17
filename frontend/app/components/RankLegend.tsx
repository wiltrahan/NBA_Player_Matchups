export function RankLegend() {
  return (
    <div className="rank-legend" aria-label="Rank tier legend">
      <span className="rank-legend-label">Tier legend</span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-green" /> 1-6 favorable
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-yellow" /> 7-12 solid
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-orange" /> 13-20 neutral
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-red" /> 21-30 tough
      </span>
    </div>
  );
}

export function RankLegend() {
  return (
    <div className="rank-legend" aria-label="Rank tier legend">
      <span className="rank-legend-label">Tier legend</span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-green" /> 25-30 favorable
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-yellow" /> 19-24 solid
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-orange" /> 11-18 neutral
      </span>
      <span className="rank-legend-item">
        <span className="rank-dot rank-dot-red" /> 1-10 tough
      </span>
    </div>
  );
}

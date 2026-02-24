const MAX_STAT_RANK = 30;

export function toDisplayedDefenseRank(rank: number): number {
  if (!Number.isFinite(rank)) return 1;
  const normalized = Math.trunc(rank);
  if (normalized < 1 || normalized > MAX_STAT_RANK) return normalized;
  return MAX_STAT_RANK + 1 - normalized;
}

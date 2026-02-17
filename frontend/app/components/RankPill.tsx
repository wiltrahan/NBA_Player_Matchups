import type { Tier } from "@/lib/types";

type RankPillProps = {
  rank: number;
  allowed: number;
  tier: Tier;
};

export function RankPill({ rank, allowed, tier }: RankPillProps) {
  return (
    <div className="rank-pill-wrap">
      <span className={`rank-pill rank-pill-${tier}`}>#{rank}</span>
      <span className="rank-pill-subtle">{allowed.toFixed(1)} allowed</span>
    </div>
  );
}

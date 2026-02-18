import type { Tier } from "@/lib/types";

type RankPillProps = {
  rank: number;
  tier: Tier;
};

export function RankPill({ rank, tier }: RankPillProps) {
  return (
    <div className="rank-pill-wrap">
      <span className={`rank-pill rank-pill-${tier}`}>#{rank}</span>
    </div>
  );
}

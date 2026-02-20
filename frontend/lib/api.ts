import type {
  GameLinesResponse,
  MatchupResponse,
  MetaResponse,
  PlayerCardResponse,
  PlayerCardWindow,
  WindowType,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type MatchupQuery = {
  date: string;
  window: WindowType;
};

async function buildError(prefix: string, response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload?.detail) {
      return new Error(`${prefix}: ${payload.detail}`);
    }
  } catch {
    // no-op; fallback to status only
  }
  return new Error(`${prefix}: ${response.status}`);
}

export async function fetchMeta(): Promise<MetaResponse> {
  const response = await fetch(`${API_BASE}/api/meta`, { cache: "no-store" });
  if (!response.ok) {
    throw await buildError("Meta request failed", response);
  }
  return (await response.json()) as MetaResponse;
}

export async function fetchMatchups(query: MatchupQuery): Promise<MatchupResponse> {
  const params = new URLSearchParams({
    date: query.date,
    window: query.window,
  });

  const response = await fetch(`${API_BASE}/api/matchups?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw await buildError("Matchups request failed", response);
  }
  return (await response.json()) as MatchupResponse;
}

export async function fetchGameLines(date: string): Promise<GameLinesResponse> {
  const params = new URLSearchParams({ date });
  const response = await fetch(`${API_BASE}/api/game-lines?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw await buildError("Game lines request failed", response);
  }
  return (await response.json()) as GameLinesResponse;
}

export async function refreshSlate(date: string): Promise<void> {
  const params = new URLSearchParams({ date, recompute: "true" });
  const response = await fetch(`${API_BASE}/api/refresh?${params.toString()}`, {
    method: "POST",
    cache: "no-store",
  });

  if (!response.ok) {
    throw await buildError("Refresh failed", response);
  }
}

export async function fetchPlayerCard(
  playerId: number,
  date?: string,
  window: PlayerCardWindow = "season",
): Promise<PlayerCardResponse> {
  const params = new URLSearchParams({
    player_id: String(playerId),
    window,
  });
  if (date) {
    params.set("date", date);
  }
  const response = await fetch(`${API_BASE}/api/player-card?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw await buildError("Player card request failed", response);
  }
  return (await response.json()) as PlayerCardResponse;
}

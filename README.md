# NBA Player Matchups

Local app for NBA daily matchup analysis.

## Stack

- Frontend: Next.js (React)
- Backend: FastAPI (Python)
- Data: `nba_api` + NBA injury report endpoint
- Storage: PostgreSQL (via `DATABASE_URL`) or SQLite fallback + in-memory cache

## What v1 does

- Select a slate date (current season)
- Load all games for that date
- Compare opposing defense by position group: Guards / Forwards / Centers
- Show matchup ranks for: PTS, REB, AST, 3PM, STL, BLK
- Support windows: Season and Last 10
- Show Game Environment Score (60% defensive rating, 40% pace)
- Display injury tags (informational)
- Provide sortable table view
- Clickable slate matchup pills to filter the table to one game

## Run locally

1. Start backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Optional PostgreSQL via Docker:

```bash
export POSTGRES_PASSWORD=change-me-local
docker compose up -d postgres
cd backend
source .venv/bin/activate
export DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5433/nba_matchups
uvicorn app.main:app --reload --port 8000
```

2. Start frontend:

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

3. Open `http://localhost:3000`.

## Notes

- `Refresh Slate` clears cached slate data; the next matchup request recomputes only what is needed.
- Matchup payloads are persisted by `slate_date + window` in PostgreSQL when `DATABASE_URL` is set, otherwise local SQLite at `backend/.data/matchup_snapshots.db`.
- Raw season logs are cached in `backend/.data/raw/` to speed up date switching.
- Team position assignment uses local inference (height + profile stats) by default for speed/reliability.
- Rankings use `1 = best matchup` (most allowed) and `30 = toughest`.
- Tiers: Green (1-6), Yellow (7-12), Orange (13-20), Red (21-30).

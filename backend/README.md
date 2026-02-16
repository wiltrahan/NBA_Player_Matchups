# Backend (FastAPI)

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## PostgreSQL (Docker)

```bash
cd ..
docker compose up -d postgres
```

Then set `DATABASE_URL` (example in `backend/.env.example`):

```bash
cd backend
source .venv/bin/activate
export POSTGRES_PASSWORD=change-me-local
export DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5433/nba_matchups
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /health`
- `GET /api/meta`
- `GET /api/matchups?date=YYYY-MM-DD&window=season|last10`
- `POST /api/refresh?date=YYYY-MM-DD` (optional `recompute=true` for eager rebuild)

## Persistence

- Snapshot DB file: `backend/.data/matchup_snapshots.db`
- Key: `slate_date + window`
- Optional override: `MATCHUP_DB_PATH=/custom/path/matchup_snapshots.db`
- Raw season cache files: `backend/.data/raw/player_logs_<season>.pkl`, `backend/.data/raw/team_logs_<season>.pkl`
- `DATABASE_URL` takes precedence over local SQLite file storage

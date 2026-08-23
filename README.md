# mlai

AI-powered investment intelligence platform — Indian equities first (Nifty 500), market-agnostic core for future expansion. Codename `mlai`; no final brand name is hard-coded anywhere in the code.

**Start here:** [`architecture/claude/SUMMARISER.md`](architecture/claude/SUMMARISER.md) — one-page orientation. Full plan in [`architecture/claude/Build_plan.md`](architecture/claude/Build_plan.md).

## Repository layout

```
backend/    FastAPI (Python 3.12) — api → services → engines | providers → db
frontend/   Next.js (App Router, TypeScript, Tailwind, shadcn/ui)
architecture/claude/   Living planning docs (source of truth — read before building a feature)
```

## Local development

### Backend

```bash
cd backend
uv sync --group dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Runs at `http://localhost:8000`; health check at `/api/v1/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Runs at `http://localhost:3000`.

### Database

```bash
docker compose up -d
```

Starts local Postgres (`postgresql://mlai:mlai@localhost:5432/mlai`).

## Principles

Read [`architecture/claude/product_principles.md`](architecture/claude/product_principles.md) before contributing. In short: evidence over opinion, never fabricate data, engines stay pure, providers stay swappable, secrets never reach the frontend.

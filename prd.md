# PRD

## 7. Non-functional Requirements

## Local Development (Docker)

Use `docker compose up --build` to start Postgres with pgvector, the FastAPI backend, and the Vite frontend. Apply database migrations separately with `docker compose exec backend alembic upgrade head`. Docker environment variables live in `.env`; copy `.env.example` for dummy local defaults and keep real secrets out of git.

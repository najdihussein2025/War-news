# Dev stack (`war-news-dev`) — isolated, test-DB only

The dev stack runs the **current checkout** against a throwaway database
`war_news_dev_test`. It shares nothing with the deployment stack (`war-news`,
database `war_news_dev`). Never run pytest, scripts, migrations, rebuilds or `exec`
against the deployment stack.

| | Deployment (`war-news`) | Dev (`war-news-dev`) |
|---|---|---|
| Compose file | `docker-compose.yml` | `docker-compose.dev.yml` (standalone, used alone) |
| Env file | `.env.main` | `.env.dev` (loaded explicitly by the file and the wrapper) |
| Database | `war_news_dev` (live data) | `war_news_dev_test` |
| Host ports | db 5433, api 8000, ui 5173 | db 5434, api 8001, ui 5174 (bound to 127.0.0.1) |
| Volumes / network / containers | `war-news_*` | `war-news-dev_*` |
| Source | baked into the image | bind mount of this checkout at `/app` |

## What was wrong before (diagnosis from the files; I could not inspect your machine)

1. `docker-compose.dev.yml` was an **override** file. `docker compose -p war-news-dev --env-file .env.dev ...`
   without `-f docker-compose.yml -f docker-compose.dev.yml` loads only `docker-compose.yml`:
   no `.:/app` mount at all, so `/app` was whatever `COPY . .` captured at the last image
   build — a stale tree without `tests/`. `--env-file` only feeds `${...}` interpolation; it
   never selects compose files.
2. When the override *was* passed, `.:/app` resolves relative to the **project directory**
   (the folder of the first `-f` file, or the current directory). Running from a different
   copy of the repo (a mapped `Z:` drive vs the UNC path, an old clone) mounts that copy.
3. `docker-compose.yml` has `env_file: .env`; the override *appended* `.env.dev`, so the
   deployment `.env` was still loaded into dev containers, and a missing `--env-file` made
   `${POSTGRES_HOST_PORT}` fall back to the project's `.env` (5433, the deployment port).

## What changed

- `docker-compose.dev.yml` is now standalone: `name: war-news-dev`, `env_file: .env.dev` only,
  `DATABASE_URL`/`POSTGRES_DB` forced to `war_news_dev_test` in `environment:` (which beats any
  env file), literal dev ports, and `./` mounts relative to the file itself. No drive letters.
- `scripts/dev.ps1` runs every compose call with `-p war-news-dev`, the file, `--env-file` and
  `--project-directory` computed from the script's own location.
- `tests/conftest.py` aborts the whole pytest session unless the database name ends in `_test`
  and the host/port is not a deployment/native-Postgres address. No override flag exists.
- `tests/test_pipeline_jobs.py` no longer commits an unscoped `DELETE`; `tests/summary_db.py`
  refuses to `TRUNCATE` anything not ending in `_test`.
- The deployment compose file is unchanged.
- External collectors (`cnrs-poll-worker`, `red-alert-collector`) only start with `--profile collectors`.

The old dev database `war_news_devtest` does not end in `_test`, so it is no longer used.
Because the project name changed, Docker creates fresh volumes: the new DB starts empty.

## Commands (PowerShell, from the repo root)

Prerequisite: `.env.dev` exists (gitignored) with `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`CNRS_WEBHOOK_SECRET` and the other required secrets.

```powershell
# Check what will run (no containers started)
.\scripts\dev.ps1 config --quiet

# Start / rebuild
.\scripts\dev.ps1 up -d --build
.\scripts\dev.ps1 ps

# Verify isolation: the repo is mounted, tests exist, DB is the _test one
.\scripts\dev.ps1 exec backend ls /app/tests
.\scripts\dev.ps1 exec backend sh -c 'echo $DATABASE_URL | sed "s/:[^:@]*@/:***@/"'
```

### First-time schema (YOU run this; Claude never runs migrations)

```powershell
.\scripts\dev.ps1 up -d db redis
.\scripts\dev.ps1 exec db psql -U postgres -d war_news_dev_test -c "SELECT current_database();"
.\scripts\dev.ps1 run --rm backend alembic heads
.\scripts\dev.ps1 run --rm backend alembic upgrade head
.\scripts\dev.ps1 up -d --build
```

(`docker/db/init` creates the `vector`, `pgcrypto` and `pg_trgm` extensions on a fresh volume.
If `alembic heads` prints two heads, see the Step 3 notes in the final report before upgrading.)

### Run the tests

```powershell
.\scripts\dev.ps1 exec backend pytest tests -q
.\scripts\dev.ps1 exec backend pytest tests/test_db_guard.py -q
.\scripts\dev.ps1 exec backend python scripts/check_stale_service_imports.py
```

If the guard fires, pytest prints `ABORTING TEST SESSION: ...` and exits before collecting any test.

### Reset the dev stack's data (dev volumes only)

```powershell
.\scripts\dev.ps1 down -v
```

`down -v` removes only `war-news-dev_pgdata` / `war-news-dev_redisdata`.

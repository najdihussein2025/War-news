# Summary bulletin Phase 0–1 implementation — 2026-10-08

## Completed

- Fast-forwarded `dev` to existing `main` tip `91214b8` after user authorization; no merge commit, commit, or push was made.
- Removed `Data/` from `.dockerignore`, added the dev rebuild command to `RUNBOOK.md`, and added `SUMMARY_FLOW_MODE` / reconciliation-delay settings (`shadow` in `.env.dev`, `off` in `.env.main`).
- Added SQLAlchemy models and generated (not applied) migration `20261008_0076_add_summary_bulletin_flow.py` for summary bulletins, items, and one review task per summary.
- Added deterministic shadow intake, invoked before Tier 1 when mode is `shadow`; it intentionally continues Tier 1 unchanged. `live` explicitly raises `NotImplementedError`.
- Added strict-intake contract tests, an operator knowledge rule, aliases mirrored to the YAML/JSON seed data, and manual SQL seed `scripts/sql/summary_aliases_2026-10-08.sql`.

## Manual actions required

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml build backend pipeline-worker live-sweep-worker
docker compose exec backend alembic upgrade head
```

The second command intentionally was **not** run. The SQL alias script intentionally was **not** run.

## Alias confirmation required

The manual SQL contains confident mappings for عيتا الجبل, الطيبة, يحمر الشقيف, and دوحه كفرمان. It leaves مزرعة بسطرة, سدانة, علمان الشومرية, and صريين commented out under `NEEDS CONFIRMATION`.

## Verification

`docker compose exec backend pytest -q` remains **1690 passed, 13 failed**. The failures are pre-existing stale-container missing `Data/*` assets; a rebuild is needed for the `.dockerignore` correction and new summary tests to be present.

No commits or pushes were made.

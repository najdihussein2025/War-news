# Summary bulletin flow — Phases 2–6 — 2026-10-08

Work done on `dev`, not pushed, in commits prefixed `summary-flow:`.

## Commits per phase

**Step A (Phase 0–1, committed this session before Phase 2):**
- `fcc6dde` dockerignore, runbook rebuild command, flow-mode settings
- `7ab9c27` summary bulletin models and migration 0076
- `ea52267` shadow intake hooked before Tier 1
- `1a0a159` summary village aliases (seed data and manual SQL)
- `b116a44` strict intake contract tests
- `32c0ad8` summary bulletin knowledge rule and phase 0–1 audit

**Phase 2 — reconciliation + live switch:**
- `65ea078` migration 0077 (incident origin, shadow_result, header mappings, summary_handled status)
- `3e5bcd3` condition families, reconciliation engine, summary incident creation and live enrichment
- `732c767` reconcile worker, live routing, false-positive guard, learned header mappings

**Phase 3 — LLM cross-check:**
- `cbad78b` LLM cross-check tests, rules and changelog (the module and prompt themselves rode in `732c767`, since intake already imported them)

**Phase 4 — API + UI:**
- `88ca285` summaries API (list/detail/resolve/dismiss) and incident origin fields
- `dcbf8be` summaries UI (review list, detail with highlighted evidence, resolve form, origin badge)

**Phase 5 — backfill:**
- `35ebb0a` backfill script to reprocess old summaries (dry run + `--apply`)

**Phase 6 — golden set + go-live:**
- `693131a` golden-fixture labeling helper, shadow report, go-live checklist
- `.env.dev` set to `SUMMARY_FLOW_MODE=live` (not committed — gitignored; see below)

## Migrations and exact dev-stack commands

Two migrations are generated, not applied: `20261008_0076` (Phase 0–1, summary tables)
and `20261008_0077` (Phase 2, incident origin / shadow_result / header mappings /
`summary_handled` status).

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml build backend pipeline-worker live-sweep-worker summary-reconcile-worker
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec backend alembic upgrade head
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d summary-reconcile-worker
```

The alias SQL (`scripts/sql/summary_aliases_2026-10-08.sql`) still needs the four
NEEDS CONFIRMATION rows resolved before it is run against `war_news_test` /
`war_news_devtest`.

## Condition families (for review)

`app/news/services/summaries/condition_families.yaml`, matched by `conditions.action_en`
(not by numeric id, since those differ between databases — the dev-test DB only goes up
to id 45 and lacks the production "Bombs" id 46 used by the header YAML):

| Family | Members |
|---|---|
| strike | Bombs, Warning Raid |
| artillery | Artillery Shelling, Tank Fire, Phosphorus Bombs, Fissile Shells |
| flares | Flare Bomb, Decoy Flares |
| grenades | Grenades, Hand Grenades, Sound Bombs |
| sweeping | Sweeping Operations, Aerial Sweep |

A name that does not exist in the connected `conditions` table is ignored, never guessed.
**Please review these groupings** — they decide when a summary line counts as "already
reported" vs. a distinct event.

## Test counts per phase (dev container, scratch-DB where a real PostgreSQL was needed)

- Phase 2 (reconciliation + routing): 27 (`test_summary_reconcile.py`) + 21
  (`test_summary_routing.py`) + 5 (`test_summary_enrichment.py`) + 7
  (`test_summary_worker.py`) = 60 passing.
- Phase 3 (cross-check): 21 (`test_summary_crosscheck.py`).
- Phase 4 (API + UI): 19 (`test_summaries_api.py`) + 8 backend/frontend component tests
  (`summaryComponents.test.tsx`, `logic.test.ts`) = 27.
- Phase 5 (backfill): 6 (`test_reprocess_summaries.py`).
- Phase 6 (golden tooling): 5 (`test_summary_label_helper.py`) + 2
  (`test_summary_shadow_report.py`) = 7.

**Final full-suite count, dev container:** `1840 passed, 5 failed, 19 skipped` (Python),
all 5 failures pre-existing and unrelated (pipeline-health role check, pipeline-jobs SQL,
one summary-detector recon-corpus case, one village-alias recon-corpus case — all present
before this session's changes). Frontend: `96 passed` (20 test files), including the new
summary tests, plus `tsc --noEmit` clean.

## What I stopped on or changed from the prompt, and why

- **Phase 3's module/prompt landed one commit early.** `intake_service.py` was edited in
  the same pass as Phase 2's routing commit (`732c767`) because the false-positive guard
  and the cross-check call sit in the same function; splitting them would have meant
  editing the same lines twice. The cross-check's own tests, rules and changelog are a
  separate commit (`cbad78b`) as the prompt asked.
- **No frontend test framework gap.** The prompt said "if none exists, report that and
  skip" — one exists (Vitest + React Server rendering), so Phase 4 frontend tests were
  written rather than skipped.
- **Condition-family membership is by `action_en`, not numeric id**, because the id for
  "Bombs" differs between `war_news_devtest` (where it doesn't exist at all — only ids
  1–45) and `war_news_dev` (id 46). This was a recon finding, not a deviation requested,
  but it is worth flagging since it means a future renamed condition breaks a family
  silently (logged in the YAML's comment).
- **`.env.dev` → `SUMMARY_FLOW_MODE=live` was not committed.** `.env.dev` and `.env.main`
  are both gitignored; git refused to stage it. The value is set on disk as asked, but a
  rebuild + migration apply (above) is still needed before it does anything, and nothing
  about this reached git history.
- **Did not run `alembic upgrade head`, the alias SQL, or any rebuild** — all exact
  commands are printed above/in `RUNBOOK.md` for you to run.

## What only you can do

- Confirm the 4 NEEDS CONFIRMATION aliases in `scripts/sql/summary_aliases_2026-10-08.sql`
  (مزرعة بسطرة, سدانة, علمان الشومرية, صريين).
- Label golden fixtures: `python -m scripts.summary_label_helper --list` /
  `--show MESSAGE_ID` / `--approve MESSAGE_ID` (21 pending in
  `tests/fixtures/summaries/pending/`, 1 approved so far — the checklist wants 20 approved
  before go-live).
- Pick the cross-check model (`SUMMARY_CROSSCHECK_MODEL`, currently `gpt-oss:20b`) after
  `nvidia-smi` on the box that will run it.
- Review the shadow report once real shadow traffic exists:
  `python -m scripts.summary_shadow_report --since ... --until ...`.
- Flip `.env.main` to `SUMMARY_FLOW_MODE=live` / `SUMMARY_CROSSCHECK_ENABLED=true` when the
  go-live checklist in `RUNBOOK.md` is satisfied.
- Review the condition-family groupings above.

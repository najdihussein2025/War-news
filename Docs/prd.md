# prd.md — Lebanon War News App

## 1. Summary

An internal, login-only web application that automates collection of
Lebanese war-news events from multiple sources (Telegram channels, the CNRS
inspected-posts API, and future sources), standardizes them against
controlled reference data, prevents duplicate records, and routes new
records through a human review step before they become official,
exportable data.

No public pages exist. Every route requires authentication.

## 2. Users & roles

No self-signup. Every account is created by a Super Admin.

| Capability | Super Admin | Admin |
|---|---|---|
| Log in to panel | ✅ | ✅ |
| View/CRUD news records | ✅ | ✅ |
| Review pending/automated news for mistakes | ✅ | ✅ |
| Export database | ✅ | ✅ |
| View logs (audit, login, ingestion) | ✅ | ✅ |
| Create/manage user accounts | ✅ | ❌ |
| Manage sources (add/pause a Telegram channel or API feed) | ✅ | to confirm |

**Open question:** should `admin` be able to manage sources, or is that
Super-Admin-only like account management? Not yet decided.

## 3. Data sources

Sources are modeled generically (`sources` table, `type` enum) so adding a
new one is a new row, not a new table or a new code path per source.

- **Telegram** — access method (Bot API vs. MTProto/Telethon) not yet
  decided; depends on whether monitored channels are owned by us or
  external public channels. MTProto is likely required for monitoring
  channels we don't administer.
- **CNRS inspected-posts API** — `https://lebanon.cnrs.edu.lb/api/v1/inspected-posts`,
  cursor-paginated (`after_id`), Bearer-token authenticated. Has a
  `model_backend=local_llm` variant that returns posts already processed by
  CNRS's own LLM — likely higher-trust, possibly pre-extracted fields.
  Registered as two `sources` rows sharing one base URL with different
  `config`.
- **Additional sources** — to be added once identified. No architectural
  change needed, per the `sources` design.

## 4. Reference data (controlled vocabularies)

Loaded from Excel templates provided by the user, imported once into
Postgres (see `db.md` for exact schema):

- **Villages** (`ACS.xlsx`, 1,560 rows) — location names (EN/AR), district,
  governorate, map coordinates.
- **Conditions/actions** (`War_Actions_updated.xlsx`, 44 rows) — the
  standardized Arabic→English action vocabulary.

These drive both the manual-entry dropdowns and the automated parser's
matching logic.

## 5. Core workflow

```
Source (Telegram / API / manual)
  -> raw_messages (untouched original payload, never mutated)
  -> parser & matcher (matches village + condition against reference data)
  -> duplicate check (exact hash + soft incident-key match)
  -> pending_review (admin confirms or edits)
  -> incidents (official record; feeds panel, export, logs)
```

**Duplicate prevention is the top priority requirement.** It is enforced at
two levels:
1. Exact duplicates: a unique constraint on a normalized content hash
   (`incidents.exact_hash`), enforced at the database level, not just in
   application logic.
2. Soft/potential duplicates: a looser match on village + condition +
   normalized date window (`incidents.incident_key`), surfaced to the
   reviewer rather than auto-merged.

Raw text parsing is not expected to be 100% accurate, especially given
free-text Arabic input — this is why every automated record lands in
`pending_review` status before becoming an official record, rather than
being published automatically.

## 6. Feature list

### Auth & accounts
- Login page (only public-facing route besides the auth check itself).
- No signup route. Accounts created by Super Admin only.
- Session/token-based auth; audit every login attempt (success and failure).

### News management
- Review queue: list of `pending_review` incidents, with duplicate-match
  indicators.
- Full CRUD on incidents (both roles) — primarily used to correct
  auto-parsed mistakes, per the original requirement.
- Incident detail/edit view exposing the full `incident_details` field set,
  grouped by category (matching `db.md` groupings) rather than as one flat
  form.
- DID-field logic enforced in the UI: a `*_did` field is locked/cleared
  when its controlling flag is 0, and required (`D`/`ID` only) when the
  flag is 1.

### Sources
- View configured sources and their ingestion health (last run, last
  cursor, error state).
- Pause/resume a source.

### Logs
- Audit log (account/source changes).
- Login log.
- Ingestion log (per-run fetch/parse/flag/fail counts).
- Incident-scoped update history on each record's detail page.

### Export
- Trigger a database export; track status/row count/file path in
  `export_logs`. Exact target format (workbook vs. other) not yet decided.

## 7. Non-functional requirements

- **PostgreSQL**, not SQLite — supports proper concurrent multi-admin
  writes and row-level locking, which the shared-login, multi-editor
  workflow requires.
- **No baseline+overlay hack.** That pattern existed in the prior
  SQLite+Excel design only because SQLite couldn't safely co-own data with
  a live Excel file. With Postgres, historical data is imported once and
  Postgres is the single source of truth from then on.
- **Secrets never committed or stored in the database.** API keys (e.g. the
  CNRS Bearer token) live only in environment variables; the DB stores the
  env var *name* (`sources.auth_secret_ref`), never the value.
- **Soft delete only** on incidents — full audit trail must survive any
  "delete."
- **Every CRUD action is attributable** to a user (`created_by`,
  `updated_by`/`performed_by`, `reviewed_by` fields throughout).

## 8. Architecture

### Backend
Existing FastAPI project structure (clean architecture):
```
app/
├── actions/        # use-case entry points (e.g. ingest_article_action.py, dedup_check_action.py)
├── api/             # route definitions
├── core/            # config, security, settings
├── dtos/            # request/response schemas
├── interfaces/       # abstract contracts
├── models/           # SQLAlchemy models
├── repositories/      # data access
├── services/          # business logic
├── sources/           # per-source ingestion adapters (telegram, cnrs api, ...)
alembic/               # migrations
```
PostgreSQL via SQLAlchemy + Alembic.

### Frontend
Separate `frontend/` folder (sibling to the backend root), feature-based
structure:
```
frontend/src/
├── app/               # routing, providers, guards
├── features/          # auth, news, sources, accounts, logs, export
├── components/         # shared presentational components
├── stores/              # zustand — auth/session state
├── lib/                  # apiClient, formatters
└── types/                 # generated from backend OpenAPI schema
```
React + TypeScript + Vite, TanStack Query for server state, Zustand for
client state, React Router with role-based route guards, Tailwind for
styling. No signup UI; every protected route redirects to `/login` when
unauthenticated, and role-gated routes (e.g. account management) redirect
or hide for `admin`.

## 9. Out of scope (for now)

- Public-facing pages of any kind.
- Self-service signup.
- GIS/map visualization (villages already carry coordinates, so this is a
  plausible future addition, not a current requirement).

## 10. Open questions

Tracked here so they aren't lost; resolve before the relevant feature is
built, not before the project starts.

1. Telegram ingestion method: Bot API vs. MTProto — depends on channel
   ownership.
2. Whether `admin` (not just `super_admin`) can manage sources.
3. Export target format.
4. Five `db.md` schema items needing confirmation against the real
   workbook (`source_link_2`, `mjnoub`, `genocide`, `injuries_extra`,
   `note_extra`).
5. Full list of sources beyond Telegram and the CNRS API, once available.

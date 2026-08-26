# PRD - Lebanon War News App

## 1. Summary

An internal, login-only web application for collecting, filtering, extracting,
deduplicating, reviewing, editing, importing, and exporting Lebanon war-news
records.

The current production flow centers on CNRS webhook/poll ingestion and a
background pipeline. Messages are stored first as immutable raw messages, then
classified for relevance, deduplicated before extraction, extracted by the
local LLM, matched against controlled village/action reference data, and
materialized into incident rows when the match is usable. Air-activity-only
items are routed into a separate air-violations workflow instead of becoming
standard incidents.

No public application pages exist. The login page is the only unauthenticated
UI route.

## 2. Users and Roles

No self-signup exists. Super Admin users create and manage accounts.

| Capability | Super Admin | Admin |
|---|---|---|
| Log in to panel | Yes | Yes |
| View incidents and air violations | Yes | Yes |
| Create/edit/delete incidents | Yes | Yes |
| Edit incident detail fields | Yes | Yes |
| Import incident workbook | Yes | No |
| Import air-violation workbook | Yes | No |
| Export air-violation workbook | Yes | Yes |
| View logs | Yes | Yes |
| Trigger manual pipeline sweep | Yes | No |
| Create/manage user accounts | Yes | No |
| View/pause/resume configured sources | Yes | Yes |

Authentication uses server-side session records with hashed bearer tokens.
Login attempts are written to `login_logs`; account and operational changes are
written to `audit_logs` where implemented.

## 3. Data Sources

Sources are modeled generically in `sources`, with normalized content-origin
metadata in `source_platform` and optional source/account blocking in
`content_source_blocks`.

Implemented source paths:

- CNRS webhook: `POST /webhooks/cnrs-posts`; stores incoming CNRS inspected
  posts, then enqueues the pipeline sweep without a manual lock.
- CNRS poll worker: periodically fetches recent inspected posts and stores new
  rows.
- Red Alert collector: long-running worker path for red-alert ingestion.
- Air-violation webhook: `POST /webhooks/air-violations`; validates a shared
  secret and creates an `air_violations` row directly.
- Workbook import: Super Admin-only imports for incidents and air violations.
- Manual API entry: authenticated create/update/delete endpoints for incidents
  and air violations.

Telegram and other source types remain supported by the generic `source_type`
enum, but the active code path is currently CNRS/webhook/poll plus operational
workers.

Secrets must stay in environment variables. Database rows may store only a
secret reference name such as `auth_secret_ref`, not the secret value.

## 4. Reference Data

Reference data is imported into Postgres and is the matching source of truth:

- `villages`: imported from ACS village data via `Data/Villages.json`.
- `conditions`: imported from war-action data via `Data/Conditions.json`.
- `channel_trust_tiers`: ranks channels as `official`, `trusted`, or `detail`
  for clustering and representative-message selection.

Village and condition tables support fuzzy matching through trigram indexes.
The UI uses the same reference data for filters, dropdowns, and verification.

## 5. Current Pipeline Flow

```text
CNRS webhook/poll/manual source
  -> raw_messages
  -> relevance_filter
  -> pre_extraction_dedup
  -> tier1_extraction
  -> matching
  -> fast_path
  -> tier2_detail_fill
  -> embedding
  -> clustering
  -> materialization
  -> duplicate_match_reconciliation
```

Important behavior:

- Raw messages keep the original text and payload, plus derived JSON fields
  such as `filter_result`, `cnrs_classification`, `extraction_result`, and
  `match_result`.
- Relevance filtering marks irrelevant rows as rejected and lets relevant or
  uncertain rows proceed.
- Pre-extraction dedup compares recent parsed messages with pg_trgm similarity
  and marks clear raw-message duplicates before spending LLM work.
- Tier-1 extraction records core event/casualty data and presence categories.
  Transient LLM errors are retried up to the configured cap.
- Matching resolves extracted villages and conditions to reference IDs. One
  message can produce multiple matched village entries.
- Fast path creates minimal incident rows for materializable village/condition
  matches and sets `details_pending = true`.
- Fast path checks recent same-village/same-condition incidents. Confident
  duplicates are linked to the canonical incident instead of inserted again.
- Condition IDs `35`, `36`, `38`, and `45` are treated as air-violation
  conditions and are terminalized with `routed_air_violation` instead of
  materialized as incidents.
- Tier-2 detail fill completes pending detail categories for fast-path
  incidents.
- Embedding and clustering group related raw messages, select a representative
  using channel trust tiers, and soft-delete subsumed duplicate incidents where
  needed.
- Materialization creates one incident per eligible matched village or merges
  into an existing incident when semantic duplicate matching is above the high
  threshold.

Pipeline sweeps are resilient: a failed item or stage is logged and later
stages still run. Webhook-triggered sweeps rely on row-level claiming with
`FOR UPDATE SKIP LOCKED`; manual/admin sweeps use an advisory lock.

## 6. Duplicate Strategy

Duplicate prevention happens at several layers:

- Raw-message uniqueness: `UNIQUE (source_id, external_message_id)`.
- Pre-extraction text similarity: recent raw messages can be marked
  `duplicate` and linked through `duplicate_of_id`.
- Fast-path incident window: confident same-village/same-condition matches
  inside the configured time window become duplicate links.
- Exact incident hash: active incidents have a partial unique index on
  `exact_hash`.
- Semantic incident dedup: embedding similarity can merge a candidate into an
  existing incident or mark it with `duplicate_flag`.
- Review records: `duplicate_matches` keeps pending/confirmed/false-positive
  duplicate relationships, including raw-message-only fast-path matches.

Human review is now a correction and adjudication layer, not a required gate
for every automated incident before insertion.

## 7. Main Features

### Auth and Accounts

- Login/logout/current-user endpoints.
- Super Admin account creation and management.
- User-level and IP-level lockout/throttling.
- Login logs for success and failure.

### Incidents

- Authenticated list/detail/create/update/delete.
- Filters for village, condition, source type, date range, duplicate-only,
  flagged-only, and verification status.
- Super Admin workbook import.
- Detail editing through grouped category sections.
- DID fields accept only `D`, `ID`, or null and are normalized by application
  logic against their controlling flags.
- Incident updates are captured in `incident_updates`.

### Air Violations

- Separate CRUD/list/detail endpoints under `/api/air-violations`.
- Direct trusted webhook ingestion.
- Super Admin workbook import.
- Admin workbook export.
- Intended for warplane/surveillance/helicopter-style air activity without the
  full incident-detail schema.

### Sources and Content Origins

- List source rows and content-source origins.
- Pause/resume configured sources.
- Block/unblock content source accounts through `content_source_blocks`.
- Track ingestion health in `ingestion_logs`.

### Logs and Operations

- Login, ingestion, and audit log views.
- Super Admin manual pipeline sweep endpoint: `POST /api/pipeline/sweep`.
- Dedicated Docker services for backend, frontend, pipeline worker,
  live-sweep worker, CNRS poll worker, and red-alert collector.

## 8. Non-Functional Requirements

- PostgreSQL with pgvector is the source of truth.
- Alembic migrations define schema evolution.
- LLM work must not hold database sessions while waiting on Ollama responses.
- Concurrent workers must use row-level claiming and configured Ollama
  concurrency limits.
- Incidents use soft delete through `is_deleted`.
- Real secrets stay out of git and out of database values.
- Auditability matters: user actions, ingestion runs, duplicate relationships,
  and incident updates should be attributable where the code path supports it.

## 9. Architecture

### Backend

FastAPI, SQLAlchemy, Alembic, PostgreSQL/pgvector, and a feature-oriented clean
architecture:

```text
app/
  accounts/      identity, roles, sessions, login throttling
  api/           routers, dependencies, route composition
  core/          config, DB setup, scheduler, Ollama concurrency, scripts
  llm/           relevance and extraction classifiers/services
  logs/          login, ingestion, and audit logs
  news/          raw messages, incidents, matching, dedup, pipeline, exports
  sources/       source definitions, CNRS/webhook adapters, content origins
alembic/         migrations
scripts/         operational backfills, diagnostics, load/repro tools
```

### Frontend

React, TypeScript, Vite, TanStack Query, Zustand, React Router, and Tailwind:

```text
frontend/src/
  app/           routing, providers, shell, error boundary
  components/    shared UI primitives
  features/      auth, accounts, dashboard, news, airViolations, sources, logs
  hooks/         shared hooks
  lib/           API client, formatters, date helpers
  stores/        auth/session state
  types/         API-facing shared types
```

## 10. Local Development

Use Docker Compose for the normal local stack:

```powershell
docker compose up --build
docker compose exec backend alembic upgrade head
```

Copy `.env.example` to `.env` for local defaults and keep real credentials out
of git.

## 11. Out of Scope For Now

- Public-facing pages.
- Self-service signup.
- GIS/map visualization.
- A finalized Telegram collection strategy.

## 12. Open Questions

1. Which Telegram method should be used if Telegram ingestion is activated:
   Bot API or MTProto/Telethon?
2. Should admins be allowed to import incident workbooks, or should imports
   remain Super Admin-only?
3. Is there a required export workbook for standard incidents, or only the
   current air-violations export?
4. Confirm meanings and UI treatment for legacy workbook fields:
   `source_link_2`, `mjnoub`, `genocide`, `injuries_extra`, `note_extra`,
   and `note_extra_2`.

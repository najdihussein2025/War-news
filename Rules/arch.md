---
description: War News 2026 DDD FastAPI architecture (FastAPI, SQLAlchemy, Alembic, Python 3.11+, Pytest)
alwaysApply: true
---

# War News 2026 DDD FastAPI architecture

You are an expert in FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL/pgvector, and Domain-Driven Design (DDD).

This project follows strict DDD architecture rules for an internal Lebanon conflict-incident monitoring system called War News 2026.

## Core principles

- Use concise, production-grade Python.
- Follow PEP 8 / PEP 257 standards; format with `black` and lint with `ruff`.
- Always use full type hints (`from __future__ import annotations` where useful). No untyped function signatures.
- Target Python 3.11+: use `dataclasses`, `Enum`, `match` statements, `Protocol`, structural typing where helpful.
- One class = one responsibility.
- Prefer composition over inheritance.
- No business logic outside the layer it belongs to — see below.

## Layer architecture

Follow this strict hierarchy, matching the existing repo layout:

- **Presentation** → `app/api/` (FastAPI routers)
- **Application** → `app/actions/news/` and `app/services/news/`
- **Domain** → `app/models/news/` (SQLAlchemy models), `app/dtos/news/` (DTOs & value objects), domain events
- **Infrastructure** → `app/core/` and `app/repositories/news/`
- **Database** → `alembic/`

All new files must live under the `/news` subfolder within each layer (`app/models/news/`, `app/dtos/news/`, `app/repositories/news/`, `app/services/news/`, `app/actions/news/`), matching the convention already established in this repo. `app/sources/` holds per-source ingestion adapters (e.g. `CNRSSourceProvider`) and sits alongside, not inside, the layers above.

## DDD rules

### Actions (`app/actions/news/`)

- One public method only: `execute()` (sync) or `async def execute()` (async).
- Accept DTOs only as input — never a raw dict, ORM model, or FastAPI `Request`.
- Never access FastAPI `Request`, `Depends(get_current_user)`, or session/auth objects directly. Auth/session context is resolved in the API layer and passed in as part of the DTO or as an explicit parameter (e.g. `performed_by: UUID`).
- Never touch the DB session directly — go through a repository (injected via constructor, typed against its interface).
- Fire domain events only at the end of `execute()`, after the unit of work has succeeded.
- Naming: `CreateIncidentAction`, `MarkDuplicateAction`, `IngestCNRSBatchAction` — file `create_incident_action.py`.

### DTOs (`app/dtos/news/`)

- Implement as frozen/immutable `pydantic.BaseModel` (`model_config = ConfigDict(frozen=True)`) or `@dataclass(frozen=True, kw_only=True)`.
- Constructor-only — no methods beyond `pydantic` validators (`@field_validator`) needed for parsing/coercion. No business logic.
- Separate `*RequestDTO` (API input), `*ResponseDTO` (API output), and internal action-input DTOs where the shapes diverge — don't reuse the SQLAlchemy model as a DTO.
- Naming: `CreateIncidentData`, `IncidentResponseData`.

### Value objects (`app/dtos/news/` or a dedicated `app/domain/news/value_objects/`)

- Immutable — `@dataclass(frozen=True)`.
- Validate inside `__post_init__`; raise a domain-specific exception (not a bare `ValueError`) on invalid state.
- No FastAPI, SQLAlchemy, or Pydantic dependency — pure Python only, so they're framework-agnostic and trivially unit-testable.
- Implement `__eq__` (or rely on dataclass-generated equality) and `__str__`/`__repr__`.
- Example candidates in this domain: `IncidentKey` (village + date + time-window + action), `ExactHash`, `DidValue`.

### Repositories (`app/repositories/news/`)

- Handle database queries only — no business logic, no dedup/confidence-scoring logic, no field-mapping logic.
- Always defined against an interface first: `app/interfaces/` holds `Protocol`- or `ABC`-based contracts, e.g. `IncidentRepositoryInterface`, `RawMessageRepositoryInterface`.
- Concrete implementations live in `app/repositories/news/` (e.g. `SqlAlchemyIncidentRepository`) and are bound to their interface via FastAPI's dependency-injection (`Depends(get_incident_repository)`), not instantiated ad hoc inside services/actions.
- Repository methods return domain models or DTOs, never raw SQLAlchemy `Row` objects, to keep the ORM out of upper layers.

### Domain events

- Cross-domain communication (e.g. ingestion → dedup → incident publish) MUST go through events, not direct cross-service calls.
- A domain's service/action must never import and call another domain's service directly — publish an event (`IncidentCreated`, `DuplicateFlagged`) and let a listener in the other domain react.
- Keep the event bus mechanism simple and explicit (in-process dispatcher is fine for now — no need for a message broker unless/until the Celery+Redis decision is confirmed).

### Policies / authorization

- All authorization logic belongs in a dedicated policy module (`app/core/policies/` or `app/services/news/policies/`), not scattered across routers or actions.
- Every action/route that mutates or exposes data is authorized explicitly before it runs — e.g. `SourcePolicy.can_manage(user)`.
- Policies are pure functions/classes over `(user, resource)` — no DB writes, no side effects.

### RBAC (intentional — no permissions package)

War News 2026 does **not** use a package like `casbin` or `fastapi-permissions`. Role enforcement is:

- **`role_name` enum** (`super_admin`, `admin`) on the `users`/`roles` tables.
- **FastAPI dependency guards** — e.g. `require_role(RoleName.super_admin)` used as a route dependency, analogous to Laravel panel middleware.
- **Policies** (see above) — centralized, explicit, called before the action executes.

Do not reintroduce a permissions package without an explicit architecture decision from Najdi.

## API layer rules (equivalent of "Filament rules")

- Routers (`app/api/`) must stay thin: parse/validate input into a DTO, call exactly one action or service, serialize the result. No branching business logic in a route handler.
- No raw SQLAlchemy queries inside `app/api/`.
- No business logic in Pydantic request/response schemas beyond field-level validation.
- Use: routers → HTTP contract only, services → orchestration, actions → single use-case execution.

## Models (`app/models/news/`)

SQLAlchemy models may contain ONLY: column definitions, relationships, `__tablename__`, and simple scopes (query helpers as classmethods that just add a filter — no business rules).

Never place business logic (dedup scoring, DID-field rules, casualty merge logic, etc.) in models.

## Security rules

- Encrypt sensitive fields at rest where applicable (e.g. anything beyond what's already covered by DB-level access control).
- Enforce data scoping consistently: e.g. only `super_admin` manages users/sources per current role rules — enforced via policy, not ad hoc `if` checks in routers.
- UUID primary keys on exportable/public-facing entities (`users`, `incidents`), per `db.md` conventions — never expose sequential `BIGSERIAL` IDs externally.
- Audit sensitive access via `audit_logs`/`login_logs` (once implemented) rather than ad hoc print/log statements.
- Validate all ingested/uploaded content strictly (raw message payloads, exports) before it touches the DB.

## System error logging

Every uncaught exception MUST be logged to the project's structured logging backend so operators can observe ingestion/API failures.

- Wire a global exception handler via FastAPI's `app.exception_handler(Exception)` (or middleware), analogous to Laravel's `bootstrap/app.php` `->withExceptions(...)`.
- Logging MUST be wrapped in its own `try/except` — a failure to log MUST never mask or replace the original exception or break the HTTP response.
- Skip/downgrade logging for expected framework noise: `HTTPException` with status `< 500`, validation errors (422), auth failures (401/403) — log these at `info`/`warning`, not `error`.
- Services/repositories/listeners MUST NOT swallow exceptions silently — let them propagate to the global handler so they're recorded.
- Never expose raw stack traces in API responses; return a sanitized error body and log the detail server-side only.

## Performance rules

- Always eager-load relationships needed by a response (`selectinload`/`joinedload`) — avoid N+1 queries, especially across the 191-column `incident_details` join.
- Cache expensive aggregate/dashboard queries (e.g. incident counts by village/date range).
- Use a background job mechanism (Celery+Redis, once confirmed) for ingestion runs, embedding generation, and exports — never block an API request on a long-running ingestion/dedup pass.

## Testing

- Use `pytest` (+ `pytest-asyncio` for async code).
- Unit test value objects and actions in isolation (mock repository interfaces — never hit a real DB in a unit test).
- Integration/feature test full domain workflows against a test Postgres instance (e.g. via `pytest-postgresql` or a Dockerized test DB), covering ingestion → dedup → incident creation.
- Test unhappy paths heavily: malformed CNRS payloads, ambiguous dedup cases, DID-field rule violations, unauthorized access.

## Forbidden

- No business logic in `app/api/` routers.
- No business logic in SQLAlchemy models or event listeners.
- No direct cross-domain service calls — use events.
- No raw SQL inside the API/presentation layer.
- No untyped function signatures or missing return types.
- No repository instantiated directly inside an action/service — always via the interface + DI.

## Naming conventions

- Actions → `CreateIncidentAction` (file: `create_incident_action.py`)
- Services → `IncidentService`
- DTOs → `CreateIncidentData` / `IncidentResponseData`
- Events → `IncidentCreated`, `DuplicateFlagged`
- Listeners → `SendIngestionAlertListener`
- Repositories → `IncidentRepository` implementing `IncidentRepositoryInterface`
- Interfaces (`app/interfaces/`) → `IncidentRepositoryInterface`, `RawMessageRepositoryInterface`

## Before generating code

Always verify:

- full type hints present, no `Any` unless genuinely unavoidable
- DTOs are frozen/immutable
- value objects have no framework dependency
- an interface exists in `app/interfaces/` before a repository is implemented
- policy check exists before a mutating action runs
- no layer violations (router → action/service → repository, never router → repository, never action → another domain's service)
- events fired at the end of `execute()`, not mid-method
- no duplicated logic between the ingestion sources and the incident domain
- file placed under the correct `/news` subfolder per layer
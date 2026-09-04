# Village Role Extraction Fix

- Date: `2026-09-03`
- Status: `PARTIALLY COMMITTED / VERIFIED LOCALLY`

## Commits

- `ac1e1b6` - Add `VillageRole`, `VillageRoleEntry`, and legacy-compatible `village_roles` extraction DTO support.
- `9ec9a37` - Carry village roles through matching and materialize incidents only for `target` villages, including fast-path protection and origin-note handling for new incidents.

Working-tree review found that the extractor, duplicate-merge repository hook, combined prompt, and matching-service test also contain uncommitted casualty-transition/backstop work. That work has no explanatory recent commit or stash entry, so it was intentionally left unstaged rather than mixed into these commits. The remaining village-role hunks in those files are still present in the working tree and require a clean follow-up isolation pass before they can be committed safely.

## Local Verification

```powershell
python -m pytest tests\test_casualty_transition_extraction.py tests\test_matching_service.py tests\test_incident_materialization_service.py tests\test_village_role_materialization.py
```

Result: `51 passed, 2 warnings`.

## Database Access And Historical Report

The supported connection path in this environment is through the application/container network:

```powershell
docker compose exec -T backend python -c "... SELECT 1 ..."
```

This succeeded. Direct `localhost:5432` access with the attempted host credentials is therefore not the configured path here.

Read-only query result for active multi-incident messages with explicit origin-position wording (Arabic terms for "stationed"):

| raw_message_id | active incidents | villages |
| --- | ---: | --- |
| 3340 | 2 | Biyad, Mansouri Sour |

`raw_message_id=3353` is present in the database and contains the expected Biyad-origin/Mansouri-target wording, but it now has one active incident (`Biyad`) rather than the previously reported pair. No data was modified.

## Follow-up Audit: raw_message_id=3353

Finding: **concerning regression risk**. The only active incident for `raw_message_id=3353` is `Biyad`, the firing-position village. There is no active `Mansouri Sour` incident for that message, despite the source text explicitly describing the strike against Mansouri. The actual target incident is therefore missing from the Incidents page while the origin-only incident remains visible.

The surviving incident is `d372c0c5-e879-48f4-a51a-586bb9be420f`, created at `2026-09-03 10:23:09+03:00`; it is not soft-deleted and has no update timestamp after creation. There are no `incident_updates` and no `duplicate_matches` linked to this incident or raw message. The available audit data therefore does not support attributing the outcome to the duplicate-review commits, clustering, or a manual reviewer action; it appears to have been materialized as Biyad initially.

## Follow-up Reconciliation: Casualty Transition Backstop

The orphaned casualty-transition hunks match the documented "Revision + Backstop Results" scope in `casualty-transition-live-validation.md`:

- `casualty_transition_backstop.py` implements the documented normalized keyword scanner.
- `IncidentRepository.merge_existing()` reuses the documented review path and writes `possible_missed_casualty_transition` with matched keywords when extraction missed a plausible transition.
- Focused merge and scanner tests match the report's stated coverage.

Committed the safely isolated scanner, merge integration, validation assets, documentation, and tests as `e2b4431` (`Add casualty-transition backstop merge review`). The prompt-revision hunks remain unstaged because they are interleaved with uncommitted village-role prompt changes. `test_matching_service.py` is village-role coverage, not casualty-transition work, and also remains unstaged.

Verification after commit:

- `pytest tests\test_casualty_transition_extraction.py tests\test_casualty_transition_merge.py tests\test_casualty_transition_backstop.py`: `16 passed`.
- `pytest tests\test_casualty_transition_extraction.py tests\test_matching_service.py tests\test_incident_materialization_service.py tests\test_village_role_materialization.py`: `51 passed`.

## Live Ollama Validation

Status: `BLOCKED`

The configured LAN endpoint `192.168.40.25:11435` remains unreachable from this environment. This is unrelated to database access.

# Phase 5 Incident Materialization Recon Report

**Date:** 2026-08-17  
**Scope:** Read-only investigation of the work required to materialize Phase 4
cluster representatives into `incidents` and `incident_details`.

## Executive summary

The ingestion pipeline currently stops after extraction, matching, embedding,
and clustering:

```text
raw message
  -> relevance filtering
  -> extraction_result
  -> match_result
  -> content_embedding
  -> duplicate clustering
  -> representative raw message
  -> [Phase 5 is not implemented]
```

The database schema for `incidents` and `incident_details` exists, and there is
a partial `IncidentRepository.create_with_detail()` method. However, that method
accepts the obsolete `ExtractedCandidate` DTO, has no callers, and maps only a
small subset of the current extraction result.

Before Phase 5 can be implemented safely, the project needs decisions on:

1. Auto-publishing versus a persisted review/status lifecycle.
2. Whether low-confidence village or condition matches may be inserted.
3. Whether the first implementation is casualty-only or must populate all
   category-specific detail fields.
4. How category flags, names, casualties, and `D`/`ID` values map into the flat
   `incident_details` schema.
5. Whether the existing exact-hash algorithm is sufficient.
6. Whether legacy incident-level soft deduplication remains necessary after
   Phase 4 clustering.

## Live database findings

At investigation time:

- `incidents`: **0 rows**
- Fully processed representative raw messages: **35**
- Representatives with both `matched_village_id` and
  `matched_condition_id`: **5**
- Representatives missing `matched_village_id`: **17**
- Representatives missing `matched_condition_id`: **28**
- Representatives missing `message_datetime`: **0**

Only messages with non-null village and condition IDs can currently satisfy the
non-null foreign keys on `incidents`.

Observed representative match-status combinations:

```text
village unmatched              + condition unmatched:               15
village matched_low_confidence + condition unmatched:                9
village matched                + condition unmatched:                4
village matched_low_confidence + condition matched_low_confidence:   2
village matched                + condition matched:                  2
village unmatched              + condition matched_low_confidence:   1
village matched                + condition matched_low_confidence:   1
village unmatched              + condition matched:                  1
```

This means Phase 5 needs an explicit match-confidence eligibility policy rather
than checking only for non-null IDs.

## Existing incident creation code

### `IncidentRepository.create_with_detail`

Location:

```text
app/news/repositories/incident_repository.py
```

The method currently:

- Requires `RawMessage.message_datetime`.
- Builds an exact hash.
- Creates an `Incident`.
- Sets:
  - `village_id`
  - `condition_id`
  - `source_id`
  - `raw_message_id`
  - `event_date`
  - `event_time`
  - `khabar`
  - `khabar_embedding`
  - `deaths`
  - `injuries`
  - `exact_hash`
  - `duplicate_flag`
  - `created_by=None`
- Creates one `IncidentDetail`.
- Maps only:
  - `male_d`
  - `male_i`
  - `female_d`
  - `female_i`
  - `children_d`
  - `children_i`
- Flushes both records without committing.

The method expects `ExtractedCandidate`, but the active extraction pipeline
persists `ExtractionResult`. No converter between these DTOs exists, and
`create_with_detail()` currently has no caller.

### Empty actions

These files remain empty:

```text
app/news/actions/publish_or_moderate_action.py
app/news/actions/dedup_check_action.py
```

There is no active action, service, route, or script that reads a representative
raw message and inserts an incident.

## Current extraction shape

The active DTO is defined in:

```text
app/llm/dtos/extraction_dto.py
```

`ExtractionResult` contains:

```json
{
  "is_relevant": true,
  "village": "string or null",
  "action_description": "string or null",
  "categories": {
    "category_key": {
      "did": "D, ID, or null",
      "name": "string or null",
      "casualties": {
        "total_deaths": null,
        "total_injuries": null,
        "deaths": null,
        "injuries": null,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      }
    }
  },
  "casualties": {
    "total_deaths": null,
    "total_injuries": null,
    "deaths": null,
    "injuries": null,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "model": "string",
  "extracted_at": "ISO-8601 datetime"
}
```

The 15 category keys are:

- `casualty_demographics`
- `lebanese_army`
- `unifil`
- `municipality`
- `school_university`
- `religious_cultural`
- `hospital`
- `health_center`
- `emergency_civil_defense`
- `press`
- `government_building`
- `road_bridge`
- `vehicles`
- `crossings_other`
- `warning_classification`

Each category has only `did`, `name`, and generic casualty counts. The extraction
schema does not provide most of the specialized fields required by
`incident_details`.

## Existing mappings

### Extraction persistence

`RawMessageRepository.save_extraction_result()` serializes
`ExtractionResult` into `raw_messages.extraction_result`.

### Reference matching

`MatchingService` maps:

- `ExtractionResult.village` to `matched_village_id`
- `ExtractionResult.action_description` to `matched_condition_id`

It does not use categories or casualties.

### Directly defensible Phase 5 mappings

The following mappings are structurally clear:

```text
RawMessage.id                              -> Incident.raw_message_id
RawMessage.source_id                       -> Incident.source_id
RawMessage.message_datetime.date           -> Incident.event_date
RawMessage.message_datetime.time           -> Incident.event_time
RawMessage.raw_text                        -> Incident.khabar
RawMessage.content_embedding               -> Incident.khabar_embedding
match_result.matched_village_id            -> Incident.village_id
match_result.matched_condition_id          -> Incident.condition_id

casualties.total_deaths                    -> Incident.total_deaths
casualties.total_injuries                  -> Incident.total_injuries
casualties.deaths                          -> Incident.deaths
casualties.injuries                        -> Incident.injuries

casualties.male_deaths                     -> IncidentDetail.male_d
casualties.male_injuries                   -> IncidentDetail.male_i
casualties.female_deaths                   -> IncidentDetail.female_d
casualties.female_injuries                 -> IncidentDetail.female_i
casualties.children_deaths                 -> IncidentDetail.children_d
casualties.children_injuries               -> IncidentDetail.children_i
```

No runtime implementation currently performs these mappings from
`ExtractionResult`.

## Category mapping gap

The flat `incident_details` schema contains many specialized fields that cannot
be derived safely from the current generic category shape.

Examples:

- `school_university` cannot distinguish a school from a university.
- `religious_cultural` cannot distinguish church, mosque, cemetery, religious
  building, or archaeological site.
- `road_bridge` cannot distinguish road from bridge or provide blocked status.
- `vehicles` cannot identify vehicle subtype, count, or construction equipment.
- `crossings_other` combines crossings, water, electricity, agriculture, drones,
  and miscellaneous infrastructure.
- Hospital and school damage levels are not extracted.
- Evacuation counts and operational status are not extracted.
- Warning classification does not produce the multiple booleans expected by the
  detail table.

A limited mapper could set category root flags, `D`/`ID`, names, and generic
casualties for categories with an unambiguous destination. Doing that for
combined categories would require business rules or a richer extraction schema.

## D/ID rules

The ORM documents this application-layer rule:

- A `*_did` field must be null when its controlling flag is false or null.
- A `*_did` field must be `D` or `ID` when its controlling flag is true.

The database does not enforce this with constraints, and no application
validator currently exists.

Open questions:

1. Does category presence always set the controlling flag to true?
2. What happens when a category exists but `did` is null?
3. How should combined categories select the correct controlling flag?
4. Should invalid combinations reject the incident or omit that category?

## Exact-hash findings

Exact-hash generation already exists:

```text
normalized_text = collapse whitespace in raw message text
hash_input = normalized_text | village_id | condition_id | event_date
exact_hash = SHA-256(hash_input)
```

The database has a partial unique index:

```text
unique exact_hash where is_deleted = false
```

Strengths:

- Deterministic.
- Includes location, condition, and date.
- Database-enforced for active incidents.

Open questions and limitations:

- Text normalization only collapses whitespace.
- Arabic characters, punctuation, diacritics, and presentation variants are not
  normalized.
- The hash uses full `raw_text`, while Phase 4 embeddings are generated from
  boilerplate-stripped text. Hash and semantic dedup therefore intentionally
  operate on different text representations.
- There is no repository pre-check such as `find_by_exact_hash()`.
- The current repository path does not catch and translate the
  database `IntegrityError` raised by a duplicate active hash.
- There is no idempotent “return existing incident” behavior when the unique
  index rejects an insert.
- `exact_hash` is nullable, although the existing creation method populates it.
- `incident_key` exists but has no generation or usage logic.

## `created_by` findings

The original assumption that `created_by` is non-null is incorrect.

The live database, migration, ORM model, and `Docs/db.md` all define:

```text
created_by UUID NULL
  references users(id)
  on delete set null
```

`IncidentRepository.create_with_detail()` explicitly sets `created_by=None`.
Therefore, the absence of a logged-in user does not block automated inserts.

There is no system-user or service-account pattern. The only live user observed
during recon was:

```text
username: superadmin
role: super_admin
```

Adding a system account is an audit-policy choice, not a schema prerequisite.

## Incident status discrepancy

### PRD behavior

`Docs/prd.md` says:

- Every automated record enters `pending_review`.
- An administrator confirms or edits it.
- A review queue exposes pending incidents and duplicate indicators.

### Later frontend behavior

Later frontend history:

- Removed the review queue page.
- Added copy saying incidents are auto-published after parsing and deduplication.
- Uses mock statuses `approved`, `rejected`, and `archived`.
- Attributes automated records to “Auto-published.”

### Backend and live-schema reality

The live `incidents` table has no:

- `status`
- `reviewed_by`
- `reviewed_at`

There is no `incident_status` enum in the live database, migration history, or
backend model. The publish/moderation action is empty.

The current backend therefore treats an incident's existence as its only
publication state.

### Required decision

Choose one before Phase 5:

1. **Auto-publish by existence**
   - Insert the representative directly.
   - Do not add lifecycle fields.
   - Aligns with the current backend schema and later frontend direction.

2. **Persist a lifecycle**
   - Add a migration and ORM fields.
   - Define initial automated status (`pending_review` or `approved`).
   - Define reviewer and transition behavior.
   - Reconcile the frontend status contract with the backend.

## Legacy incident-level deduplication

The repository and `DedupMatchingService` contain an older incident-level soft
deduplication design:

- Search incidents by village and date window.
- Compare condition, embedding similarity, and time closeness.
- Merge high-confidence duplicates.
- Flag medium-confidence possible duplicates.
- Create `duplicate_matches`.

The service defines low and high thresholds, but no current action applies
them. The implied middle-band behavior—create an incident with
`duplicate_flag=true` and a pending `duplicate_match`—is not orchestrated.
`create_duplicate_match()` and the incident merge path have no active callers.

Phase 4 now clusters raw messages before Phase 5. It must be decided whether:

- Phase 4 completely replaces this incident-level mechanism, or
- Phase 5 still needs incident-level deduplication for idempotency, historical
  incidents, or clusters processed in separate runs.

The exact-hash unique index should remain as a final database guard either way.

## Missing orchestration and audit wiring

There are no Phase 5 builders in `app/api/factories/action_factory.py`.
`IncidentRepository` and `DedupMatchingService` are not composed into an
application action.

There is also no:

- Incident creation script or scheduler step.
- Incident creation API route.
- Active caller for `IncidentRepository.create_with_detail()`.
- Test coverage for `IncidentRepository`, exact-hash behavior, incident
  insertion, or the legacy incident dedup service.
- `IncidentUpdate` entry using `UpdateAction.create` when a new incident is
  inserted.

The existing merge logic audits edits but only merges deaths, injuries, totals,
and appended text notes. It does not merge category-specific
`IncidentDetail` fields.

## Fully unbuilt Phase 5 components

- Representative eligibility policy.
- `ExtractionResult` validation and materialization action.
- Current extraction-to-incident mapper.
- Category-to-detail mapper.
- D/ID invariant validation.
- Transaction boundary for one incident plus its detail.
- Exact-hash uniqueness conflict behavior.
- Batch runner or route for materialization.
- Idempotency behavior when a representative was already materialized.
- Status/publication behavior.
- Factory and dependency wiring.
- Creation audit-history behavior.
- Tests covering insertion, mapping, rollback, duplicate hashes, and reruns.

## Recommended discussion order

1. Confirm auto-publish versus persisted status.
2. Define eligible village and condition match statuses.
3. Choose initial mapping scope:
   - core incident plus casualties only, or
   - richer extraction and complete category mapping.
4. Define category and D/ID mapping rules.
5. Confirm exact-hash normalization and uniqueness-conflict behavior.
6. Decide whether legacy incident-level soft deduplication remains active.
7. Design the Phase 5 action, repository transaction, tests, and runner.

## Conclusion

Phase 5 is not blocked by the incident tables or by `created_by`. It is blocked
primarily by unresolved publication policy and the structural mismatch between
the generic extraction categories and the highly specialized
`incident_details` schema.

A safe minimal Phase 5 could insert only representatives with accepted,
non-null village and condition IDs, map the core incident fields and top-level
casualties, create a detail row with demographic casualties, and leave
unsupported category fields null. A complete Phase 5 requires expanding the
extraction contract and defining explicit category-level mapping rules first.

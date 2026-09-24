# Casualty scope and merge rules

## casualty_scope values

| Value | When to use |
|-------|-------------|
| `per_village_exact` | Explicit count tied to one target village in its clause |
| `bulletin_aggregate` | One shared toll covers 2+ target villages without per-village numbers |
| `unspecified` | No casualty-to-village tie, no usable numbers, or no casualties |

## Evidence requirements

- `casualty_scope_evidence` = full literal sentence/clause justifying the scope.
- Must include both the number and whether it attaches to one village or a list.
- Null when scope is `unspecified` or no adequate clause exists.

## Backstop validation (deterministic)

- `bulletin_aggregate` requires ≥2 matched village names in evidence span.
- `per_village_exact` requires matched village to have explicit deaths/injuries in `village_roles`.
- Unsupported scope claims → downgrade to `unspecified` + review flag.

## casualty_transitions (follow-ups)

Use when text says a previously injured person died:
- «توفى أحد الجرحى» → `[{"from_status":"injured","to_status":"deceased","count":1}]`
- «بقي 3 جرحى وتوفي واحد» → same transition; do not require restating injury count in casualties.
- NOT for first reports or plain additive updates («5 جرحى جدد»).

## merge_existing logic

When merging into an existing incident:
1. Parse `casualty_transitions` from extraction.
2. Require keyword backstop in source text before applying transitions (prevents confusing separate casualty groups with transitions).
3. Apply `injured→deceased` arithmetic: decrement injuries, increment deaths (min of requested vs available).
4. Flag for review if backstop matched but LLM emitted no transitions.
5. Idempotent per raw_message_id for multi-village duplicate merge paths.

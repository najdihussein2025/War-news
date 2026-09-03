# Casualty Status-Transition Follow-Up — Implementation Report

## Problem

Merge layer `_max_preserving_empty` always took `max(existing, incoming)` per casualty field. That is correct for additive follow-ups but wrong when an injured person dies: injuries should decrease while deaths increase.

## Extraction field shipped

Tier 1 general extraction (`GENERAL_EXTRACTION_PROMPT` in `ollama_extraction_service.py`) now emits:

```json
"casualty_transitions": [
  {"from_status": "injured", "to_status": "deceased", "count": 1}
]
```

- Supported statuses: `injured`, `deceased`
- Supported transition: `injured → deceased` only
- Field defaults to `[]` when absent (legacy payloads)
- Case 2 (death-only follow-up, no restated injury count) is the expected common case — the model must emit the transition without restating remaining injuries

DTOs: `CasualtyTransition`, `CasualtyTransitionStatus` on `ExtractionResult`.

## Prompt validation (before / after)

Validation uses golden Arabic examples parsed through `_RawExtractionResponse` (schema + prompt contract). No live Ollama call in CI.

| Metric | Before | After |
|--------|--------|-------|
| Schema accepts `casualty_transitions` | 0 / 3 | 3 / 3 |
| Transition examples parse correctly | N/A | 2 / 2 |
| Additive (no transition) stays empty | N/A | 1 / 1 |
| Legacy payloads without field | fail | default `[]` |

Script: `scripts/phase2-extraction-testing/validate_casualty_transition_examples.py`

```json
{
  "before_transitions_field_supported": 0,
  "after_golden_examples_parsed": 3,
  "golden_example_count": 3
}
```

Golden examples cover:
1. **case2_death_only** — «توفي أحد الجرحى…» → transition only
2. **case1_restate_and_transition** — «بقي 3 جرحى وتوفي واحد» → transition + restated counts
3. **additive_no_transition** — «أصيب 5 جرحى جدد» → `[]`

## Merge-layer logic

Implemented in `app/news/services/casualty_transition_merge.py`, applied in `IncidentRepository.merge_existing()` **before** max-wins.

1. **Atomic transition application** against stored existing values:
   - `injuries -= count`, `deaths += count` for each `injured → deceased` entry
   - Applied count = `min(requested, stored injuries)` (zero clamp)
2. **Skip max-wins** on fields already set by a transition (`deaths`, `injuries`, and matching totals).
3. **Disagreement resolution**: transition-inferred value wins over a conflicting restated injury count (transition applied first; max-wins skipped on affected fields).
4. **Review flag**: if `requested_count > available injuries`, clamp at zero and set `duplicate_flag = True` (reuse existing review mechanism).
5. **Provenance**: `incident_updates.new_values.deaths_transitioned_from_injuries` records `{count, requested_count, raw_message_id, channel}`.
6. **Max-wins unchanged** for fields with no transition signal (B5 additive path preserved).

## Test results (all passing)

### `tests/test_casualty_transition_merge.py` (4 tests)

| Test | Scenario | Expected |
|------|----------|----------|
| `test_transition_followup_correct_extraction_merge_should_reflect_current_state` | Case 1: restated counts + transition | deaths=1, injuries=3 |
| `test_transition_followup_incremental_death_only_merge_applies_transition` | Case 2: death only, no injury restatement | deaths=1, injuries=3 (inferred) |
| `test_transition_wins_over_conflicting_restated_injury_count` | Transition vs restated injuries=2 | injuries=3 (transition wins) |
| `test_transition_clamps_at_zero_and_flags_review` | Transition count > stored injuries | injuries=0, deaths=1, `duplicate_flag=True`, provenance recorded |

### `tests/test_casualty_transition_extraction.py` (7 parametrized + unit)

Golden parse tests, legacy default-empty, round-trip, invalid schema rejection, validation report.

### B5 regression: `tests/test_incident_merge_repository.py`

All existing max-wins / `{field}_suppressed` tests pass unchanged (3 tests).

**Total: 14 passed** (`pytest tests/test_casualty_transition_merge.py tests/test_casualty_transition_extraction.py tests/test_incident_merge_repository.py`)

## Commits

1. **Extraction layer** — DTOs, Tier 1 prompt/schema, golden parse tests, validation script
2. **Merge layer** — transition application, provenance, merge tests

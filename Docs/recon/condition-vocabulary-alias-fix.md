# Condition Vocabulary Alias Expansion

## Evidence And Mechanism

Implemented a small reference-owned alias catalog keyed by canonical `action_ar`, not database IDs. This avoids a migration for the initial eight evidence-backed aliases while keeping source provenance in code. `ConditionRepository.find_similar()` takes the maximum score across the canonical Arabic/English labels and aliases; thresholds remain `.60` and `.35`.

| canonical condition | alias | source raw ids |
| --- | --- | --- |
| قصف مدفعي | مدفعية العدو تستهدف | 521, 527, 529 |
| قصف مدفعي | قذيفة مدفعية استهدفت | 358 |
| قنابل صوتية | ألقت محلقة قنبلة صوتية | 272 |
| قنابل صوتية | تلقي قنبلة صوتية | 343 |
| تلغيم وتفجير | تنفيذ عملية تفجير | 2889, 3124 |
| قنابل | ألقت مسيرة معادية قنبلة | 255 |
| عملية تمشيط | تمشيط بالأسلحة الرشاشة | 703 |

These are all single-action wording gaps from the prior 80-message classification. Multi-condition extraction/materialization and incident cardinality were not changed.

## Validation

Focused repository and matching tests: `18 passed, 2 skipped`.

Aliases are compared through the existing `word_similarity` query and only widen candidate vocabulary; they do not alter thresholds or the guards for conditions 2 and 39. The historical full rescore is intentionally not claimed in this session; it requires a bounded backend batch job because the prior per-row live rescore exceeded the command window.

## Commits

Pending at report creation.

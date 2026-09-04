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

`75a2a71` added the evidence-backed alias catalog.

## Alias Miss Follow-Up

### Part 1: `تنفيذ عملية تفجير`

The alias exists exactly as expected: `تنفيذ عملية تفجير` is attached to
`تلغيم وتفجير` for raw ids `2889` and `3124`. Its forward similarity was
already `1.000000`; it was not missing, malformed, or affected by whitespace,
diacritics, or Unicode normalization.

The defect was candidate ordering. `find_similar()` used the alias score for
the displayed similarity, but its bidirectional `coverage_rank` considered
only canonical condition text. That allowed the partial canonical match
`عملية تمشيط` (`0.583333`) to rank ahead of the exact alias candidate.
Commit `2abfdef` adds reverse-direction alias coverage to that rank and tests
that every alias is present in both ranking dimensions.

### Part 2: raw id `255`

`ألقت مسيرة معادية قنبلة` describes a drone releasing a bomb, not a drone
falling. The existing canonical mapping to `قنابل` is therefore correct;
`سقوط مسيّرة` is not the appropriate category. No separate Part 2 code commit
was needed: the same ranking defect had hidden the already-correct `قنابل`
alias candidate.

### Re-verified Evidence Set

| raw id | text | before top result | after top result |
| --- | --- | --- | --- |
| 255 | ألقت مسيرة معادية قنبلة | سقوط مسيّرة, 0.545455 | قنابل, 1.000000 |
| 272 | ألقت محلقة قنبلة صوتية | قنابل صوتية, 1.000000 | قنابل صوتية, 1.000000 |
| 343 | تلقي قنبلة صوتية | قنابل صوتية, 1.000000 | قنابل صوتية, 1.000000 |
| 358 | قذيفة مدفعية استهدفت | قصف مدفعي, 1.000000 | قصف مدفعي, 1.000000 |
| 521 | مدفعية العدو تستهدف | قصف مدفعي, 1.000000 | قصف مدفعي, 1.000000 |
| 527 | مدفعية العدو تستهدف | قصف مدفعي, 1.000000 | قصف مدفعي, 1.000000 |
| 529 | مدفعية العدو تستهدف | قصف مدفعي, 1.000000 | قصف مدفعي, 1.000000 |
| 703 | تمشيط بالأسلحة الرشاشة | عملية تمشيط, 1.000000 | عملية تمشيط, 1.000000 |
| 2889 | تنفيذ عملية تفجير | عملية تمشيط, 0.583333 | تلغيم وتفجير, 1.000000 |
| 3124 | تنفيذ عملية تفجير | عملية تمشيط, 0.583333 | تلغيم وتفجير, 1.000000 |

The focused repository query test passes in the backend container. The broad
repository test file retains one unrelated integration failure: its generic
airstrike expectation is `unmatched`, while the current local database returns
`matched_low_confidence`; this alias-ranking change does not affect that
non-alias text.

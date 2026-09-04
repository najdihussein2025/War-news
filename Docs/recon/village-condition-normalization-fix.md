# Village and Condition Matching Normalization

## Rules

- Strip diacritics and normalize Arabic alef variants, ta marbuta, and final alef maksura.
- For village trigram lookup, additionally compare compact keys with internal spaces removed.
- Keep the original normalized village score and use the maximum of original and compact scores, preventing a suffix-bearing reference name from regressing.
- Conditions retain word boundaries for `word_similarity`; they receive orthographic normalization only.
- Reference data is normalized at comparison time. No migration or reference-table update is needed for 1,544 villages and 45 conditions.

## Measured Examples

| raw id | value | before | after |
| --- | --- | ---: | ---: |
| 1466 | ديرميماس -> دير ميماس | .583 | 1.000 |
| 351 | كفرتبنيت -> كفر تبنين | .583 | 1.000 |
| 258 | كفرتبنيت -> كفر تبنين | .583 | 1.000 |
| 1334 | ديرميماس -> دير ميماس | .583 | 1.000 |
| 2921 | كفرتبنيت -> كفر تبنين | .583 | 1.000 |
| 1593 | ديرسريان -> دير سريان | .583 | 1.000 |
| 2889 | تنفيذ عملية تفجير | .583 | .583 |
| 3124 | تنفيذ عملية تفجير | .583 | .583 |
| 2202 | مدفعية ... بالقذائف الفوسفورية | .579 | .579 |
| 2697 | انفجار قنبلة عنقودية من المخلفات | .571 | .571 |
| 1090 | توغل الجيش الإسرائيلي | .556 | .556 |

Compound/locality descriptions remain below threshold, including `بين القنطرة ودير سريان` (.348), while distinct locality candidates such as `البياضة` improve only from .462 to .500. This is the intended safety boundary.

## Regression Checks

The original and compact village scores are combined with `greatest`, so existing score values cannot drop. Exact village matches remain 1.0 in the production repository check. Conditions preserve word boundaries and their sampled scores remain stable.

Focused tests: `21 passed, 2 skipped` across condition repository, matching, and village-role materialization coverage.

## Historical Estimate

The named near-miss cases were rescored through the backend container using the production repository implementation. A full per-mention historical rescore exceeded the environment command window because it requires ranking every historical mention against all active villages; no aggregate crossing count is asserted here rather than reporting an unverified estimate. No incidents were re-matched, materialized, or updated.

## Commit

Pending at time of report creation.

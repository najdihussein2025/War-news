# Match Confidence Failure Analysis

- Date: `2026-09-03`
- Scope: read-only analysis of the 426 active `needs_verification` incidents.

## Failure Dimension

| failure | incidents | share |
| --- | ---: | ---: |
| village only | 227 | 53.3% |
| condition only | 116 | 27.2% |
| both | 83 | 19.5% |

Village confidence is involved in 310 incidents (72.8%); condition confidence is involved in 199 (46.7%). The counts overlap in the 83 both-failure rows.

## Village Confidence

The 310 incidents contain 752 failing target-village match entries because digest messages commonly name several places.

| stored best-score band | entries | share |
| --- | ---: | ---: |
| 0.50-0.59 near miss | 299 | 39.8% |
| 0.35-0.49 moderate | 330 | 43.9% |
| below 0.35 | 123 | 16.4% |
| no candidate | 0 | 0.0% |

The pipeline stores a best score even below 0.35, but intentionally clears `matched_village_id`; the historical row therefore cannot identify which reference village was best for the far-miss band without recomputing against the current reference table.

Representative near misses, with source-text context:

| raw id | extracted village | stored candidate | score | source excerpt |
| --- | --- | --- | ---: | --- |
| 1466 | ديرميماس | دير ميماس | .583 | إطلاق نار ... في ديرميماس قضاء مرجعيون |
| 351 | كفرتبنيت | كفر تبنين | .583 | تفجير معادٍ لجيش العدو في بلدة كفرتبنيت |
| 258 | كفرتبنيت | كفر تبنين | .583 | ملخص الاعتداءات ... كفرتبنيت |
| 1334 | ديرميماس | دير ميماس | .583 | أطراف ديرميماس |
| 2921 | كفرتبنيت | كفر تبنين | .583 | تفجير نفذه العدو في بلدة كفرتبنيت |

Representative moderate cases:

| raw id | extracted village | stored candidate | score | source excerpt |
| --- | --- | --- | ---: | --- |
| 2276 | وادي العزية | وادي العرايش | .471 | قنبلة صوتية باتجاه وادي العزية |
| 2512 | عدشيت | عدشيت الشقيف | .462 | قصف مدفعي يستهدف محيط عدشيت القصير |
| 2539 | البياضة | البياض صور | .462 | تحرك لآليات العدو في البياضة |
| 2524 | البياضة | البياض صور | .462 | تحرك لآليات العدو في البياضة ومشاع المنصوري |
| 1593 | ديرسريان | دير سريان | .583 | غارة استهدفت محيط ديرسريان |

The final row is included because the historic data demonstrates another formatting variant, although its score is technically in the near-miss band.

Representative far misses (no candidate id is retained):

| raw id | extracted village | score | source excerpt |
| --- | --- | ---: | --- |
| 258 | بين القنطرة ودير سريان | .348 | غارة بين القنطرة ودير سريان |
| 1179 | مشاع المنصوري لجهة مجدل زون | .333 | مشاع المنصوري لجهة مجدل زون |
| 2503 | حدادا | .333 | تفجير بين عيتا الجبل وحداثا |
| 574 | الطيري | .333 | تفجير ... في بلدة الطيري |
| 3143 | الشنديبة | .313 | توغل ... في منطقتي الشنديبة ووادي الجمل |
| 865 | مارج الزين | .313 | ملخص اعتداءات اليوم |
| 540 | الحجير | .308 | قصف ... وادي السلوقي والحجير |
| 637 | التييري | .300 | ملخص اعتداءات اليوم |
| 999 | الطائفية | .286 | آخر الاعتداءات |
| 1584 | الغندورية | .286 | أطراف بلدة الغندورية لجهة وادي الحجير |

## Condition Confidence

| stored best-score band | incidents | share of 199 condition failures |
| --- | ---: | ---: |
| 0.50-0.59 near miss | 107 | 53.8% |
| 0.35-0.49 moderate | 92 | 46.2% |
| below 0.35 / no candidate | 0 | 0.0% |

Representative near misses:

| raw id | extracted action | stored candidate | score | source excerpt |
| --- | --- | --- | ---: | --- |
| 2889 | تنفيذ عملية تفجير | عملية تمشيط | .583 | نفذ العدو عملية تفجير في المنصوري |
| 3124 | تنفيذ عملية تفجير | عملية تمشيط | .583 | تفجير كبير في كفرتبنيت |
| 2202 | مدفعية ... بالقذائف الفوسفورية | قذائف فوسفورية | .579 | استهداف الدوحة بالقذائف الفوسفورية |
| 2697 | انفجار قنبلة عنقودية من المخلفات | قنابل عنقودية | .571 | انفجار قنبلة عنقودية في حبوش |
| 1090 | توغل الجيش الإسرائيلي | توغل بري | .556 | توغل ... من البياضة باتجاه المنصوري |

Representative moderate cases:

| raw id | extracted action | stored candidate | score | source excerpt |
| --- | --- | --- | ---: | --- |
| 337 | دبابات ... استهدفت الخيام | قذائف الدبابات | .467 | دبابة ميركافا استهدفت الخيام |
| 3068 | تحت القصف والغارات | قصف وغارات | .467 | ليلة رعب ... غارات جوية وقصف مدفعي |
| 991 | غارات وتفجيرات ومدفعية وتمشيط | تلغيم وتفجير | .462 | آخر الاعتداءات متعدد الأنواع |
| 1123 | حريق جراء سقوط قذيفة مدفعية | سقوط مسيرة | .455 | حريق بين شقرا وميس الجبل |
| 2324 | تفجير ... وتجدد القصف المدفعي | قصف مدفعي | .429 | تفجير في الدبش وتجدد القصف |

The guarded conditions are not a contributor: ids `2` (`غارة تحذيرية`) and `39` (`غارات وهمية`) appear in zero failed-condition candidates. The issue is broader multi-action and wording coverage, not the special token guards.

## Arabic Fallback

`VillageRepository.find_similar()` always computes `greatest(similarity(normalized acs_name), similarity(normalized ref_name_ar))` for every active village with either name present. It is not a conditional fallback that can be skipped. The Arabic examples above demonstrate that it runs, but current normalization does not collapse all meaningful spelling, word-boundary, or locality variants. The stored output does not indicate which of the two fields won a specific score, so per-row winner attribution is unavailable retrospectively.

## Conclusion

This is a mix, not a single threshold problem:

- About 40% of failing village entries and 54% of failing condition incidents are near misses, so carefully evaluated threshold or normalization improvements may recover a meaningful cohort.
- About 44% of failing village entries are moderate variants, compounds, or ambiguous geography. These point to extraction phrasing and reference alias/coverage work, not a blanket threshold decrease.
- The 16% below 0.35 include neighborhoods, directional/compound locations, and likely spelling variants that do not map safely to a single village without better reference aliases or role-aware extraction.
- Condition failures are largely multi-action descriptions being forced onto one of 45 reference conditions; their candidate scores are not evidence of an ids-2/39 guard problem.

No fix is proposed or implemented by this report.

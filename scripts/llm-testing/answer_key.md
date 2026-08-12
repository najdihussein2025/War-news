# Answer Key

| sample file | expected village | expected action | expected casualties | notes |
|---|---|---|---|---|
| sample_1_relevant.txt | بعيتا الجبل or حداثا | تقدم عسكري إسرائيلي مع تمشيط بالأسلحة الرشاشة | null | Mentions two places; flag as an ambiguity test case. |
| sample_2_irrelevant_shipping.txt | null | null | null | NOT a Lebanon military/security incident. |
| sample_3_irrelevant_taiwan.txt | null | null | null | NOT a Lebanon military/security incident. |
| sample_4_irrelevant_trump.txt | null | null | null | NOT a Lebanon military/security incident. |
| sample_5_relevant_ied_army.txt | TBD - needs manual review | TBD - needs manual review | TBD - needs manual review | Real Lebanon incident: IED/explosion involving the Lebanese Army. |
| sample_6_relevant_car_strike.txt | TBD - needs manual review | TBD - needs manual review | TBD - needs manual review | Real Lebanon incident: car strike in the south. |
| sample_7_hard_negative_gaza_1.txt | TBD - needs manual review | TBD - needs manual review | TBD - needs manual review | Hard negative: Gaza violence, should return null - tests country discrimination, not just topic discrimination. |
| sample_8_hard_negative_gaza_2.txt | TBD - needs manual review | TBD - needs manual review | TBD - needs manual review | Hard negative: Gaza violence, should return null - tests country discrimination, not just topic discrimination. |
| sample_9_hard_negative_earthquake.txt | TBD - needs manual review | TBD - needs manual review | TBD - needs manual review | Hard negative: natural disaster, should return null - tests incident-type discrimination, not just relevance. |

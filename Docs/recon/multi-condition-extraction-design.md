# Multi-Condition Extraction Design

- Date: `2026-09-03`
- Status: `DESIGN ONLY - AWAITING CONFIRMATION`

## Step 1: Pattern Check

The failure-analysis count of 107 condition near-miss incident rows maps to 92 distinct raw messages because multi-village materialization can create more than one incident from one message. A conservative read-only keyword-family classification of those 92 messages found:

| classification | distinct raw messages |
| --- | ---: |
| two or more explicit action families | 12 |
| one explicit action family | 80 |

This is deliberately conservative: it identifies co-occurring artillery/shelling, raids, explosions/mining, sweeping, incursions, bombs/materials, or gunfire. It does not infer separate events from vague prose.

Representative genuinely multi-action examples:

| raw id | extracted action text | observed actions |
| --- | --- | --- |
| 180 | drone incendiary materials, tank shell, drone sound bomb | incendiary materials + tank shelling + sound bomb |
| 254 | sweeping, tank shell, drone sound bomb | sweeping + tank shelling + sound bomb |
| 329 | Israeli incursion and shelling of a house causing fire | ground incursion + shelling |
| 573 | explosions and phosphorus/artillery fire | explosions + phosphorus/artillery shelling |
| 733 | artillery targeting and machine-gun sweeping | artillery shelling + sweeping |

Representative single-action but poorly matched examples:

| raw id | extracted action text | intended/reference concept |
| --- | --- | --- |
| 255 | drone dropped a bomb | bomb/drop, not `سقوط مسيرة` |
| 272 | drone dropped a sound bomb | sound bomb |
| 343 | dropping a sound bomb | sound bomb |
| 358 | artillery shell targeted outskirts | artillery shelling |
| 521 | enemy artillery targets | artillery shelling |
| 527 | artillery targets outskirts | artillery shelling |
| 529 | Israeli artillery targets | artillery shelling |
| 703 | machine-gun sweeping | sweeping |
| 2889 | carrying out an explosion operation | mining/explosion, not sweeping |
| 3124 | carrying out an explosion operation | mining/explosion, not sweeping |

Conclusion: multi-action extraction can help the clear digest subset, but it is not the primary fix for this near-miss cohort. Most records are single-action wording/reference-category alignment problems.

## Step 2: Materialization Decision

### Options

- **A. Multiple incidents per condition.** Accurate for clearly independent events, but combining multi-village and multi-condition output risks a cartesian product (for example, three villages times two actions) that invents event links the source did not state.
- **B. One primary incident plus secondary condition metadata.** Avoids multiplication and preserves mentions, but flattens genuinely distinct incidents and makes the primary-condition selection a high-impact heuristic.
- **C. Defer multi-condition materialization.** Address the dominant single-action phrasing/reference gap first; later introduce a sub-event extraction shape only for messages that explicitly segment independent actions.

### Recommendation: C

Do not add multi-condition extraction or materialization yet. The observed split does not justify changing incident cardinality for the entire cohort. First scope a smaller condition-vocabulary/reference-alias improvement for the 80 single-family messages. Revisit multi-condition extraction for the 12 clear digest messages with an explicit sub-event model, not a flat list of conditions and not a village x condition cartesian product.

If multi-condition work is approved later, the safer shape is an ordered `condition_events` list where each event owns its condition text and explicitly linked target villages. A bare list of condition ids is insufficient because it cannot encode which village belongs to which action.

## Decision Required

Confirm whether to proceed with option C (defer multi-condition implementation and scope single-action condition vocabulary work), or explicitly choose A or B with the accepted cardinality tradeoff. No implementation has been performed.

# Item 4 - Combined Tier-1 Full Evaluation

## Outcome: not viable to enable

The setting remains `false`. The available 43-row workbook is present, but it
cannot support the requested accuracy-versus-ground-truth evaluation for the
Tier-1 input texts: its structured labels are not consistently derivable from
the corresponding `Khabar` snippet.

The existing five-sample paired run is still valid for the direct regression it
measured: baseline added 0 presence categories and the combined call added 4.
It is not valid to convert the workbook's structured fields into a full
per-field accuracy percentage because those fields often contain incident facts
that do not appear in the text sent to either model.

## Corpus audit

| Item | Result |
|---|---:|
| Available sample texts | 43 (`sample_2.txt` through `sample_44.txt`) |
| Category-labelled samples | 8 |
| Ground-truth category instances | 13 |
| Casualty-labelled samples | 2 |
| Ground-truth casualty fields | 4 |
| Explicit labels for Tier-1 relevance, village, action-description text | 0 |

The `Database Sample.xlsx` rows do contain `Action_A`, village reference and
many category-detail columns, but no reviewed Tier-1 target fields that define
how a model should represent relevance, the village array, or action text.
More importantly, sample 2's supplied text is only a raid on Tebnine, while
its structured row labels a hospital, government building and building warning
facts absent from that text. Sample 3 has the same mismatch. Those labels are
valid database facts, but not valid negative/positive labels for a text-only
presence gate.

## Measured paired evidence

The only completed model comparison remains the recorded five-sample pilot
(`tier1_combined_comparison.json`):

| Metric | Baseline (two calls) | Combined (one call) |
|---|---:|---:|
| Messages | 5 | 5 |
| LLM calls/message | 2 | 1 |
| Presence true positives | 0 | 0 |
| Presence false negatives | 6 | 6 |
| Presence false positives | 0 | 4 |
| Casualty exact / mismatch | 0 / 2 | 0 / 2 |

The four combined false positives were `lebanese_army` (sample 3),
`road_bridge` (samples 4 and 5), and `vehicles` (sample 6). The 50% call-count
reduction is real, but cannot outweigh those extra false positives: each can
trigger unnecessary Tier-2 work and create incorrect incident context.

## Why no 43-message model rerun is reported

A full paired run would make 129 remote inference calls (86 baseline plus 43
combined). Recent measured Tier-1 calls average 66.30 seconds in the available
benchmark, making a sequential run roughly 143 minutes before retries. More
importantly, it would still not answer the requested ground-truth question:
35 of 43 samples have no category label, 41 have no casualty label, and none
defines the requested general Tier-1 targets. A larger run against this corpus
would produce a larger, but still invalid, accuracy table.

## Recommendation

**Not viable.** Do not enable `tier1_use_combined_presence_extraction`. Do not
attempt prompt tuning against this workbook: because its labels can include
facts outside the supplied text, a prompt revision could optimize toward
hallucinating database context rather than extracting the message.

To reopen the evaluation, create a text-grounded held-out set with, for every
message: reviewed relevant/not-relevant, exact village list, accepted action
description, root casualty values, and explicit present/absent labels for all
presence categories. Then run the existing paired comparator after extending it
to score those reviewed Tier-1 targets.

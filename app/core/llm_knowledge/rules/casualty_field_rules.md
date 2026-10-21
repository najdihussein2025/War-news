# Casualty field rules

Numberless mentions and shared multi-village tolls use Arabic review messages
built from stored totals and villages. The first-mentioned village is the
temporary owner; linked members name that owner. These messages never infer a
count.

This file is authoritative for incident casualty fields. `null` means unknown
or unstated; `0` is permitted only when the source explicitly states that no
casualties of that type occurred.

- `deaths` and `injuries` are exact counts at this incident's village. Accept
  adjacent Arabic/Western digits, number words, and singular/dual casualty
  nouns. Reject ages, dates, times, strike/house/vehicle counts, links, phone
  numbers, source labels, and approximate quantities.
- `total_deaths = deaths` and `total_injuries = injuries`. If no main count is
  stated but explicitly counted people are listed, the main count is their sum.
  Persisted values, sibling incidents, and bulletin-wide tolls are not inputs.
- `male_*`, `female_*`, and `children_*` require the explicit adult/child nouns
  listed in the final-round specification. Grammatical masculine/feminine
  casualty forms, occupations (`مسعف`), generic people (`مواطن`, `شخص`), verbs,
  adjectives, and names are never demographic evidence. `طفلة` and `فتى` are
  children only and never double-count as female/male.
- An untyped count populates only `deaths`/`injuries` and its corresponding
  total; all demographic fields remain `null`, never `0` or guessed.
- In `بينهم/بينهما/من بينهم/منهم` phrases, the preceding casualty count remains
  the main count and following explicit people only populate demographic
  subsets. An unnumbered plural demographic remains `null`.
- Each total is null iff its main count is null; no demographic may exist
  without a total; totals must cover the sum of non-null demographics; values
  cannot be negative.
- Whole-token, longest-name, clause-owner, line-label, qualifier, hometown, and
  shared-bulletin ownership rules apply before accepting a count.
- Channel/page names are never news content. A registered header (`terminology/source_headers.yaml`,
  e.g. «صفحة الإعلامي الشهيد علي شعيب») is stripped before every stage; its «الشهيد» never produces a
  death, injury, casualty status, gender evidence or evidence span. Only deaths/injuries described as part
  of the reported event in the body count. A span inside a header, or a bare «شهيد»/«الشهيد» with no event
  context in the body, is rejected and the field is null (not 0).
- Enemy/non-Lebanese personnel as victims are excluded from all casualty fields
  and recorded in Arabic in `note_extra` as an uncounted casualty claim.
- Merging (code-enforced, not a prompt rule): a duplicate, revision or recompute
  may adopt casualty values from a linked message only when the evidence is in
  that message's cleaned body, it describes the same event, and it is at the
  same village; otherwise the incident keeps its own values and the rejection
  reason is audited (`casualty_provenance_rejected`).
  Manual duplicate confirmation, the Tier 2 root fill and bulletin reconciliation use the same guard; a
  linked message that cannot be loaded copies no numbers.

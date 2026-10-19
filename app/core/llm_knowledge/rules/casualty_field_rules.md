# Casualty field rules

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
- Enemy/non-Lebanese personnel as victims are excluded from all casualty fields
  and recorded in Arabic in `note_extra` as an uncounted casualty claim.

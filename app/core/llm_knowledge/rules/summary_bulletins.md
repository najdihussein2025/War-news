# Summary bulletins

A summary bulletin is a structured Arabic round-up such as `ملخص الاعتداءات` or
`ملخص حتى الآن`, with action headers followed by locations. Its deterministic
parser resolves its reporting window and strict South/Nabatieh gazetteer matches.
It does not use fuzzy matching. `بين X و Y` is one item with primary X, secondary
Y and modifier `between`; `اطراف X` retains the outskirts modifier.

The parser is authoritative in Phase 1. A later LLM may only add independently
evidenced items; it must never override a parser item. Unknown headers and all
unresolved locations are collected in exactly one review task per summary.

## Reconciliation rules (Phase 2)

These are enforced in code (`reconcile_service.py`), not left to a model.

- **Match** a live incident to a summary item only when the village equals the item's
  primary village (or, for `بين X و Y`, its secondary village), the condition is the
  same or in the same family (`condition_families.yaml`), and the incident's event time
  is inside the summary window widened by `SUMMARY_MATCH_TOLERANCE_MINUTES`. Candidates
  include incidents of every origin, so an `الى الان` summary followed by the full-day one
  never duplicates itself. If several match, link the earliest.
- **Same village, different condition is a different event.** A flare incident does not
  confirm a strike line.
- **`بين X و Y` is one item.** It reconciles as matched when an incident exists on X or Y.
  The 5 October example `بين محيبيب و برعشيت` is one item anchored on محيبيب.
- **A repeat count is not a second incident.** `وادي السلوقي (٢)` is one item with
  `reported_count=2`; the created incident notes `(×2 حسب الملخص)`.
- **Summaries never write casualties.** An item whose text contains casualty words
  (شهيد، شهداء، جريح، جرحى، إصابة، قتيل) creates nothing and joins the bulletin's single
  review task as `casualty_in_summary`.
- **No village, no incident.** That includes air violations.
- **Created incidents** use the window midpoint as event time, carry the evidence span
  and window in the note, set `origin=summary`, keep `raw_message_id` empty (so no later
  stage re-reads the whole bulletin), and are never flagged `needs_verification` by the
  summary flow itself.
- **A later live report wins.** When a live message matches a summary-created incident
  (same village, condition family and day) it enriches that incident: live casualties,
  time and text replace the summary's, `origin` becomes `live`, and
  `source_summary_item_id` is kept.
- **A fully matched summary stays hidden** unless a review task is open.

## LLM cross-check rules (Phase 3)

The cross-check (`crosscheck_service.py`, prompt `summary_crosscheck_prompt.md`) is add-only.

- The model may only list pairs the parser missed. It can never remove or change a parser
  item; the code keeps parser items out of reach of the model response.
- Every proposal is re-verified in code: the evidence must be a verbatim substring of the
  message and must contain the location; the header must resolve through the YAML or the
  learned `summary_header_mappings`; the place must resolve through the same strict
  parser and gazetteer. A header that does not resolve goes to the review task as
  `unknown_header`, a place that does not resolve as `unresolved_location`.
- A proposal that repeats a parser item, or a place already in the review task, is dropped.
- A timeout, bad JSON or connection error skips the cross-check, records the error in
  `summary_bulletins.last_error` and leaves the parser result untouched.
- Accepted items carry `origin=llm_crosscheck` and are appended to
  `eval/summary_parser_misses.jsonl` so each parser gap can become a grammar fix.

## Review rules (Phase 4)

- There is exactly one review task per summary; the Incidents page lists one «Summary review»
  entry per open task, never one per item.
- An admin may resolve an `unresolved_location` with a village (optionally saving the spelling
  as a `village_location_aliases` row), an `unknown_header` with one or more conditions
  (optionally saving a `summary_header_mappings` row), or dismiss any item. A saved header
  never overrides an approved YAML header.
- Resolving an unknown header re-reads the bulletin with the header known, so the places under
  it become items; the header row itself is kept as a record.
- `casualty_in_summary` may be dismissed or turned into an incident; the incident still carries
  no casualty numbers.
- Resolving marks the items pending and queues the summary for reconciliation immediately.

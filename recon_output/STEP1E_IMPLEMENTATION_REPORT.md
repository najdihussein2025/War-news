# Step 1e silent-error report

## Outcome

Manual review of the regenerated fixtures found resolved items with the wrong
condition. The cause was structural: a header the parser did not recognise was
invisible, so the places under it were read under the previous header.

- **Header barrier (28640, 31010).** A header-like line always starts a section.
  If it does not resolve, its places go to residual as
  `place_under_unresolved_header` with that header's text and never inherit an
  earlier one. 28640: `-احراق المنازل:` -> 27, no longer 21. 31010:
  `● قصف بالقذائف الفسفورية` -> 7 for `علي الطاهر`, no longer merged into 5.
- **Residual header (28017, 28089, 28640, 29072, 31010).** Each residual entry
  takes the header of the section its offsets fall in. `صريين` in 28017 is under
  `القصف المدفعي المعادي`.
- **Secondary != primary (28640, 29072).** One item, no secondary, original phrase
  kept in `location_texts`.
- **Stale date (28327).** Compared with the anchor day: 15/9 is one day before the
  anchor 16/9 of a 00:00:51 post on 17/9, so `explicit_date:stale_suspect`, window
  15/9 00:00 -> posting time. 28017 (00:02 on 16/9 for 15/9) stays normal.

## What the invariants are, and what the earlier draft got wrong

A first draft of this step wrote `0` into the coverage report for header
provenance and residual header without computing them. Those numbers are now
computed by `app/news/services/summaries/invariants.py`, which recomputes
header-like lines from the text with the shared predicate and compares them with
where each item/residual was actually attributed. The tests include negative
controls: with the barrier disabled the provenance check reports a violation, and
a deliberately stale residual label is reported.

Over all 221 bulletins: header provenance **0**, residual header **0**,
secondary != primary **0**.

## Behaviour that follows from the spec, worth knowing

- The bullet rule makes any short bullet line without a place a barrier. In
  31010 `○ دوحة كفرمان.` (a typo for كفررمان) is shaped like an unknown header, so
  `حداثا` and `القنطرة لجهة وادي الحجير` under artillery go to residual rather than
  being resolved. Adding the alias restores them; the parser stays fail-closed.
- 35645: `قنابل مضيئة فوق` does not resolve (`فوق` is not a filler), so six places
  that were silently read as تفجيرات/artillery are now residual. Left unfixed on
  purpose; it is a vocabulary candidate.
- A line that names its own action and place inherits nothing, so it still parses
  under an unresolved header and above the first header. Lines above the first
  header used to be dropped silently once any header existed (34606, 36943).

## Coverage v2, before (1d) and after

| metric | before | after |
|---|---:|---:|
| bulletins complete / partial / residual_only | 48 / 166 / 7 | 48 / 166 / 7 |
| aliases simulated: complete | 63 | 63 |
| resolved items / item candidates | 3697 / 4796 | 3721 / 4815 |
| residual entries | 1099 | 1094 |
| S4 workload (bulletins with a place-like residual under an approved header) | 116 | 110 |
| explicit_date / stale_suspect windows | 98 / 4 | 96 / 6 |

## Verification

- Summary tests: 84 passed, including the corpus invariants over all 221 bulletins.
- Approved fixture 40279 unchanged and complete.
- No fuzzy or similarity code in the production summary package; stale-import grep clean.
- Full suite in a scratch container with a dummy database URL: 1727 passed, 3 failed,
  14 skipped. The 3 failures (`test_pipeline_health_route`, two in `test_pipeline_jobs`)
  need a database and fail identically on HEAD. The 1d baseline had 13 environment
  failures from missing `Data/*` assets; this container has those assets, so the
  counts are not directly comparable.

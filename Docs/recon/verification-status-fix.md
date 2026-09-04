# Verification Status Confidence Fix

- Date: `2026-09-03`
- Code commit: `f639e9d` (`Compute verification status from confidence signals`)

## Recon Findings

`incidents.verification_status` is written at creation by the full and fast materialization paths in `IncidentMaterializationService`. The initial helper was not a fixed `needs_verification` default: it auto-processed only when the condition and every target village had status `matched`. The database default is also `auto_processed`.

The merge path did not update `verification_status`; it only changed `duplicate_flag`. Human verification actions can set the status explicitly in `IncidentRepository.update_verification_status`.

The existing helper consulted strict match status only. It ignored materialization-time duplicate state, relevance review, insufficient-score duplicate handling, and the casualty-transition backstop. This is therefore partially implemented confidence logic, not a pure default-value bug.

Read-only database distribution for active incidents:

| verification status | count | fully matched village + condition | duplicate flag | relevance review | insufficient score | casualty backstop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| auto_processed | 236 | 145 | 93 | 0 | 0 | 0 |
| needs_verification | 426 | 0 | 150 | 0 | 0 | 0 |

All currently flagged incidents fail the existing strict exact-match gate. None of the 426 has the additional relevance, insufficient-score, or casualty-backstop signals. The observed high review rate is therefore driven by match ambiguity, not a stale `needs_verification` default.

## Final Rule Set

An incident is `auto_processed` only when all of the following are true:

- The condition and every materialized target village are `matched`, not `matched_low_confidence` or unmatched.
- `duplicate_flag` is false.
- There is no insufficient-score duplicate outcome.
- The source raw message has no relevance `needs_review` / low-confidence flag.
- There is no `possible_missed_casualty_transition` review condition.

Any uncertainty signal produces `needs_verification`. Trusted sources are not an independent bypass: source trust supports relevance filtering, but it cannot make an ambiguous village or condition match safe to auto-clear.

## Changes

- Extended the materialization helper with explicit uncertainty inputs and passed duplicate/relevance signals from both full and fast creation paths.
- Ensured a merge-time casualty-transition review flag also sets the surviving incident to `needs_verification`.
- Added compatibility handling for raw-message-like test inputs without optional relevance fields.
- Did not bulk-update existing incidents.

## Read-Only Backfill Report

Under this strengthened rule, `0` existing `needs_verification` incidents would flip to `auto_processed`: all 426 already fail the strict exact-match condition. No backfill was applied.

## Verification

- Clean exact match: auto-processes.
- Low-confidence match: remains flagged.
- Duplicate flag: remains flagged.
- Insufficient-score condition: remains flagged.
- Relevance review: remains flagged.
- Casualty-transition disagreement/backstop: remains flagged and now updates the merge target's verification status.

Focused verification: `39 passed` across materialization, merge, and casualty-transition tests.

Regression verification: `57 passed` across casualty extraction, matching, materialization, and village-role tests.

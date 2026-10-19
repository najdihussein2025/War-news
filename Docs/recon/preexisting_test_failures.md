# Step 1.5 baseline

`pytest tests -q` at Step 1 completed with 29 failures, 1874 passes and 53 skips.
The backend container cannot execute an arbitrary Git worktree without rebuilding
an image from it, so the requested before-Step-1 worktree comparison was not run.
These are the baseline gate for this phase.

| Group | Cause |
|---|---|
| casualty gender tests (10) | Expectations retain superseded grammatical/occupation gender inference, contrary to the no-guess target rule. |
| extraction/materialization casualty tests | Existing DTO/materialization contract drift around grounded demographics and derived totals. |
| repository/detail, reconciliation, dedup, pipeline, lease tests | Existing persistence/service contract drift unrelated to body evidence. |
| summary routing and village aliases | Existing API/fixture contract drift. |

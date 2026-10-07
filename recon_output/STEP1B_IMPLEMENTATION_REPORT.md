# Step 1b implementation report

## Outcome

- All 221 corpus messages are still detected as summaries.
- Auto-acceptable coverage moved from **19/221 (8.6%)** to **30/221 (13.6%)** before aliases.
- Non-prose/sectioned coverage is **30/138 (21.7%)**; prose/timeline coverage is **0/83**, intentionally fail-closed.
- This is below the non-gating 60% pre-alias target. Remaining blockers overlap: leftover tokens 133 bulletins, unresolved places 127, prose/timeline 83, and unresolved headers 34.
- The 30-row alias proposal sheet is unapproved. Therefore the generated SQL contains only `BEGIN; COMMIT;`, and no DB write was performed.

## Phase 0 root-cause evidence

`بلده` and `منطقه` existed only as leading qualifiers. The old path called `_resolve(part)`, stripped qualifiers only from token 0, then used `_dp_places`; embedded occurrences were returned in `unused` and became leftovers. Examples:

- `بلده`: 27972 `توغل ... في بلدة حلتا`; 27977 the same timeline sentence; 27996 `حي الدير في بلدة النبطية الفوقا`.
- `منطقه`: 28385, 28444 and 28475 each contain `تقدم دبابتي ميركافا الي منطقة مشاع المنصوري`.

`بين` was handled only by the anchored `_BETWEEN.match(part)`. Embedded forms fell through to `_dp_places`, leaving `بين` (or the preceding narrative) unused. Examples include 28514/28746 `مواد حارقه بين الحنيه والقليله`, and 29232 `الحرش بين بيت ياحون وعيتا الجبل`. The earlier reported count was also inflated by the substring in `صربين`.

Step 1b routes long embedded `بلده`/`منطقه` sentences and non-action embedded-`بين` sentences to `out_of_scope_lines`; a complete inline action grammar before `بين` is parsed deterministically. The full top-30/top-30 classification is in `step1b_gap_classification.csv`.

## Implemented

- YAML-backed exact header grammar with action cores, fillers, compound condition unions, and the approved D4 mappings.
- URL/signature/decorative noise removal, qualifiers, count words, inline action lines, embedded pairs, and explicit prose-section routing.
- No similarity/fuzzy code in `app/news/services/summaries`; fuzzy one-edit logic exists only in the human proposal script.
- Read-only alias proposals, an approval-only idempotent SQL generator, fixture review HTML, and correction application tooling.
- Pending fixtures were regenerated. Approved fixture `40279.json` was unchanged.

## Verification

- Focused summary suite: 28 passed.
- Stale-import check: passed.
- Production-package forbidden-term grep is enforced by a test.
- Full suite: **1,675 passed, 13 failed**. Every failure is caused by the
  container's absent `Data/Conditions.json`, `Data/Villages.json`,
  `Data/VillageLocationAliases.json`, or `Data/Database Sample.xlsx`; this is
  the same environment-only failure class as the Step 1 baseline (1,651 passed,
  16 failed), with no summary regression.

## Human workflow

Open `recon_output/fixture_review.html` directly in a browser. Review `recon_output/alias_proposals.csv`, set `approve` to `yes` only for accepted rows, rerun the SQL generator, inspect its output, then execute it manually with:

```powershell
Get-Content -Raw scripts/sql/seed_summary_aliases.sql | docker compose exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Afterward, re-export the gazetteer and run `python scripts/recon/draft_summary_fixtures.py --after-aliases` inside the backend container to place before/after values side by side.

## Specification/data conflicts

- The requested 60% figure was explicitly a target, not a gate; deterministic changes reached 21.7% of non-prose bulletins. Most remaining failures are real alias/data decisions and mixed narrative structures, so promoting them automatically would violate the no-guessing guard.
- The original `بين` frequency treated `صربين` as a match, so it was not a count of standalone `بين` tokens.
- No alias was approved in the supplied CSV, so generating executable inserts would violate the approval-only requirement.

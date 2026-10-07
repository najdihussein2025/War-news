# Step 1d parser closure report

## Regressions fixed

- URLs were removed only after normalization and splitting. They are now removed from original text before any cleanup.
- The old guillemet pass stripped every non-place span. It now removes only true line/message tail signatures and retains header/action syntax such as `قنابل «لانشر»` and prose mentions such as `دبابة «ميركافا»`.
- Article/gender-normalized fillers and the literal `تمشيط بالاسلحهالرشاشه` typo resolve deterministically. Movement headings now begin prose sections.

## Item-level contract

Resolved `ParsedSummaryItem` records have `status="resolved"`. `ParseResult.residual` retains every non-item fragment as `{kind,text,section_header,offsets}` and `disposition` is `complete`, `partial`, or `residual_only`. `auto_acceptable` remains a backward-compatible alias for `complete`.

Resolved items from partial bulletins proceed to reconciliation; residual entries are the bounded S4/review workload. No parser text is silently dropped.

## Coverage v2

| metric | current DB | aliases simulated |
|---|---:|---:|
| bulletins complete | 48 | 63 |
| bulletins partial | 166 | 151 |
| bulletins residual_only | 7 | 7 |
| resolved items / all item candidates | 3697/4796 | 3790/4618 |
| residual entries, median/p90 per bulletin | 1099, 3/10 | 828 |
| timeline events with exact time | 36 | 36 |

S4 workload is **116 bulletins** with a place-like residual under an approved header. There are **22** deduplicated pending fixture families.

## Verification

- Focused summary tests: 39 passed.
- Approved fixture 40279 remains unchanged and complete with the same 18 expected items.
- No fuzzy/similarity code in the production summary package; stale-import check passed.
- Full suite: **1,686 passed, 13 failed**. The 13 failures are unchanged
  environment-only missing `Data/*` assets, matching the Step 1c failure class.

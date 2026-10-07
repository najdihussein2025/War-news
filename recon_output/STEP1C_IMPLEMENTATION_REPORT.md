# Step 1c implementation report

## Root causes

1. In 27996, `غارات من الطيران الحربي` matched an exact `proposed` entry before the approved grammar could run; line headers without a colon were also never section boundaries. Resolver precedence and line-based section discovery now fix both causes.
2. In 27996 and the 9/9 family, bullets, bidi/format marks and punctuation reached lookup inconsistently. Cleanup is now shared before header and place lookup, including Persian `ھ/ک/ی` canonicalisation.
3. In 1115, `القصف المدفعي المعادي` could remain inside the preceding section and enter place parsing when section discovery missed its layout. Any complete header-grammar line is now a boundary, with or without a colon.
4. In 1115/1276, the decorative glyph inside `«جـھ,آد𓂆»` created a newline before the end-only signature regex ran. Non-place guillemet spans are now removed from the original text before normalisation, across glyphs and lines.
5. In 28327, separator handling was path-specific. `/`, en dash and em dash are now accepted consistently; the shared cleanup also strips leading dash bullets.

## Results

See `step1_parser_coverage.md` for the three-column table. Current coverage is **36/221 (16.3%)** and approved aliases simulated in memory reach **48/221 (21.7%)**. Sectioned coverage is **36/140 (25.7%)** current and **48/140 (34.3%)** simulated. Timeline/prose remains **0/81 fully auto-acceptable**; 371 narrative lines remain out of scope. The timeline grammar does extract seven timed events from 28169, but its naval-vessel sentence correctly remains prose, so that bulletin is not fully acceptable.

The non-gating 60% sectioned and 30% fully-parseable timeline targets were not reached. Remaining bulletins combine unresolved place decisions, prose and action vocabularies outside the approved deterministic grammar.

## Gazetteer checks

- No active Hasbaiya `حلتا` exists. The DB has `حلتا` id 675 in Batroun and `زحلتا` id 1528 in Jezzine; neither was approved.
- `الطيبه` maps deterministically to candidate id 1440, `طيبة مرجعيون`. The proposal search missed it because it compared the definite article literally; it now uses the same article/taa-marbuta village key as the gazetteer. It remains pending.
- `كفر شوبا` is id 813. `مزرعه بسطره` remains pending as requested.
- `دوحه كفرمان` was approved to id 851, the same `كفر رمان` parent already used for `دوحه كفررمان`.

## Aliases and review

Eight aliases are approved in the CSV and emitted as idempotent inserts in `scripts/sql/seed_summary_aliases.sql`. The SQL was not executed. Pending fixtures were reduced to 22 normalised-text families, including representatives 2083, 28169 and 28316. Each fixture records identical repost siblings; the review sheet displays its blocker badge, window rule and event times.

After reviewing the SQL, Hussein can run:

```powershell
Get-Content -Raw scripts/sql/seed_summary_aliases.sql | docker compose exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## Compatibility

Approved fixture 40279 remains unchanged. Production summary parsing contains no fuzzy/similarity matching. Fuzzy edit distance remains confined to the read-only alias proposal tool.

Focused summary tests: **35 passed**. Stale-import and forbidden-term checks passed. Full suite: **1,682 passed, 13 failed**; all 13 are the unchanged environment-only failures caused by missing `Data/Conditions.json`, `Data/Villages.json`, `Data/VillageLocationAliases.json`, or `Data/Database Sample.xlsx`.

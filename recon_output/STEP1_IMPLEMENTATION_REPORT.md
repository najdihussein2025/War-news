# Step 1 implementation report

## Outcome

Implemented the DB-free summary detector, Beirut-aware window resolver, exact southern gazetteer snapshot, header dictionary, deterministic parser, fixture drafting tools, approved reference fixture, and tests. No pipeline hook, migration, model, API, frontend, or LLM call was added.

The pure modules do not import SQLAlchemy or `app.core.config`. The DB adapter in `gazetteer.py` imports SQLAlchemy lazily inside `build_gazetteer_snapshot()` and explicitly starts its export transaction with `SET TRANSACTION READ ONLY`.

## Tests

- Focused Step 1 gate: **21 passed**, 0 failed, 1 unrelated Pydantic deprecation warning.
- Full suite with an unreachable dummy `DATABASE_URL`: **1,651 passed, 14 skipped, 16 failed**.
- None of the 16 failures touches the new summary code. Twelve are caused by data files absent from the backend image (`Data/Conditions.json`, `Data/Villages.json`, `Data/Database Sample.xlsx`, `Data/VillageLocationAliases.json`); four require an actual PostgreSQL connection (`pipeline_health_route` and `pipeline_jobs`) and failed against the intentionally unreachable dummy URL.
- Stale service import check: passed.

## Corpus coverage

See `recon_output/step1_parser_coverage.md`.

- Summary detection: **221/221 (100%)**.
- Auto-acceptable parses: **19/221 (8.6%)**.
- Window rules: 103 explicit-date; 18 parsed overnight; 45 overnight with absent/ignored end time; 41 default; 13 default with absent/ignored end time; 1 broad partial.
- The low auto-accept rate is deliberate fail-closed behavior. Unknown D4 headers, timeline prose, signatures/links, and unresolved aliases remain reviewable instead of being guessed.

## Approved fixture

`40279.json` contains the required 18 items and resolves to 2026-10-05 00:00–23:13 Asia/Beirut with `auto_acceptable=true`. Existing aliases resolve:

- وادي الحجير → قبريخا, with place detail preserved.
- وادي السلوقي → تولين, with place detail preserved.
- وادي زبقين → زبقين, with place detail preserved.

No new alias is required for reference 40279. `كفرتبنيت` resolves through the whitespace-insensitive exact comparison to canonical `كفر تبنيت`; this is normalization, not fuzzy matching.

## Pending human review fixtures

The 29 pending fixtures are:

`1115, 1116, 1121, 1239, 1240, 1276, 1277, 1278, 2083, 2187, 2188, 27972, 27977, 27993, 27996, 28010, 28017, 28022, 28038, 28044, 28045, 28089, 28092, 28169, 28316, 28327, 28370, 28385, 28444`.

They remain under `tests/fixtures/summaries/pending/`; the golden test intentionally reads only `approved/`.

## Proposed aliases requiring adjudication

No alias rows were inserted. High-frequency candidates from the coverage report are:

- `عيتا الجبل` / `اطراف عيتا الجبل` / `حرش عيتا الجبل`
- `حلتا` / `مرتفعات حلتا`
- `الطيبه`
- `مزرعه بسطره` and qualified forms near كفرشوبا
- `وادي مظلم`
- `علمان الشومريه`
- `صريين`
- `سدانه`
- `دوحه كفرمان`
- `مجري نهر الخردله`
- `حانين`

These need a human-selected parent village and `place_detail`; the parser deliberately does not infer them. Links, channel signatures, D4 header text, and narrative phrases in the unresolved report are noise/prose candidates, not village aliases.

## Real-code/data conflicts and decisions

- `app/core/text_normalization.py` imports SQLAlchemy at module load, so its small normalization/key behavior was reproduced in the pure package rather than imported.
- The DB has `coord_x`/`coord_y` projected coordinates, not latitude/longitude. The snapshot carries projected coordinates and the optional centroid disambiguator measures them as meters.
- The alias table has `note`, not a `place_detail` column. Snapshot export maps alias `note` to the pure `place_detail` field.
- The existing backend container does not contain the repository `Data/` directory, preventing a clean full-suite run independent of this change.
- The requirement “all 48 headers” was satisfied by including every CSV-normalized corpus header; explicit approved/unknown variants add a small number of additional dictionary entries.

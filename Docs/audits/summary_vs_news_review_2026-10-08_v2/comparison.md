# Audit v2 vs v1 — headline comparison

Read-only audit of the scratch copy (`summary_rehearsal_scratch`, 2026-04-01 through 2026-10-08), run with the fixed
summary windows (end-of-day marker, post-midnight date rule) and the 17 confirmed aliases applied. Numbers are
reported, not judged.

| metric | v1 (old) | v2 (new) | change |
|---|---:|---:|---:|
| Summaries reviewed (distinct bulletins) | 179 | 179 | 0 |
| Reposts grouped | 67 | 67 | 0 |
| Total items | 3231 | 3304 | +73 |
| DUPLICATE_OF_NEWS | 1269 (39.3%) | 1321 (40.0%) | +52 |
| SAME_VILLAGE_OTHER_ACTION | 694 (21.5%) | 720 (21.8%) | +26 |
| NOT_IN_INCIDENTS | 1268 (39.2%) | 1263 (38.2%) | -5 |
| — NEWS_NEVER_ARRIVED | 464 | 404 | -60 |
| — NEWS_FAILED | 540 | 565 | +25 |
| — NEWS_WRONG_VILLAGE | 146 | 160 | +14 |
| — NEWS_REJECTED | 118 | 134 | +16 |
| Incident rows created from summaries | 663 | 673 | +10 |
| DUPLICATE_ROW | 224 | 227 | +3 |
| UNIQUE_CORRECT | 163 | 168 | +5 |
| WRONG_ROW | 276 | 278 | +2 |

Not attributed: the item count and bucket moves have two inputs that changed together (the window fixes and the 17
new aliases), plus whatever changed in the scratch data since v1 ran. This table does not separate them. The brief's
old figures (39.3 / 21.5 / 39.2 %; 224 / 276 / 163) match v1 exactly.

Window quality over the 179 bulletins (in memory): `regex_explicit` 97, `regex_relative` 40, `fallback` 42;
0 zero-length windows, 0 invalid windows.

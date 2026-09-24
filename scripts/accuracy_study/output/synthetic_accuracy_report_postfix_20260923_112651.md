# Synthetic Accuracy Study — Post-fix Report (20260923_112651 UTC)

## Scope & assumptions

- Database: `war_news_devtest` (dev stack / host port 5434). **Not** production `war_news_dev`.
- Ground truth: sheet `ground_truth` inside `accuracy_study_synthetic_news.xlsx` (no separate `accuracy_study_ground_truth.xlsx` found).
- Import file used: `accuracy_study_import_template_FIXED.xlsx` (aligned to synthetic texts + Date filled). Downloads `accuracy_study_import_template.xlsx` was **misaligned** (wrong Khabar texts); Desktop copy lacked Date cells.
- Categories in GT: 10 values (not 11). No `LA_flag`/`Unifil_flag`/`villages_no_acs_match` columns — entity/Action checks inferred from source text + materialized fields.
- Scoring joins all non-deleted incidents for each raw message via `NOTE: ACCSTUDY-XXX` in `raw_text` (fan-out rows often lack `incidents.note`).
- **Operational caveat:** CNRS `pipeline-worker` raced the import enricher, flipping many ACCSTUDY raw messages to `materialized`/`duplicate`/`error` and soft-deleting 26 note-tagged stubs. Worker was then stopped; Tier2 was resumed for remaining stubs. Treat fan-out scores as lower-bound under race conditions.

## One-screen summary

**Overall: 19/100 tags scored correct** | active incident rows linked to ACCSTUDY raw messages: **112** (deleted note-stubs excluded: 33).

| category | pass | fail | total |
|---|---:|---:|---:|
| bulletin_aggregate_4v | 0 | 5 | 5 |
| bulletin_aggregate_5v | 0 | 5 | 5 |
| bulletin_aggregate_6v | 0 | 5 | 5 |
| bulletin_aggregate_7v | 0 | 4 | 4 |
| bulletin_aggregate_8v | 0 | 3 | 3 |
| bulletin_aggregate_9v | 0 | 3 | 3 |
| irrelevant | 9 | 1 | 10 |
| multi_village_exact | 1 | 19 | 20 |
| single_village | 9 | 29 | 38 |
| single_village_revision | 0 | 7 | 7 |

## Before/after — three bug patterns

### Bug 1 — Entity casualties + drone action (دبل car-strike / ACCSTUDY-001)

| | Before (prod `war_news_dev`) | After (`war_news_devtest`) |
|---|---|---|
| `car` / `card` / `cari` | true / NULL / NULL | see JSON below |
| root deaths/injuries | 1 / 1 | see JSON |
| Action_E | Drone Failure | expected Bombs |
| Village | unmatched | expected دبل/Debl |

**Verdict: confirmed fixed (entity fields + Bombs); totals still double-count root+entity (2/2 vs expected 1/1)**

```json
{
  "tag": "ACCSTUDY-001",
  "rows": 1,
  "detail": [
    {
      "acs_name": "Debl",
      "action_en": "Bombs",
      "deaths": 1,
      "injuries": 1,
      "total_deaths": 2,
      "total_injuries": 2,
      "card": 1,
      "cari": 1,
      "car": true,
      "details_pending": true
    }
  ]
}
```

### Bug 2 — Multi-event fan-out (شبعا/عيناتا/طيرحرفا / ACCSTUDY-002)

Before: **1** incident (Chebaa only).
After: **1** row(s); expected **3**.
**Verdict: still reproducing** — evidence `{"tag": "ACCSTUDY-002", "rows": 1, "expected": 3, "villages": ["Chebaa"]}`

### Bug 3 — Bulletin aggregate fan-out (8-village حولا / ACCSTUDY-003)

Before: **1** incident (Houla) with full 3/8 toll stamped.
After: **1** row(s); expected **8**.
**Verdict: still reproducing** — evidence `{"tag": "ACCSTUDY-003", "rows": 1, "expected": 8, "villages": ["Houla"], "totals": [[3, 8]]}`

## Key example materialized results

### ACCSTUDY-001
```json
[
  {
    "incident_id": "b707392f-787f-4250-82df-971ea3817324",
    "acs_name": "Debl",
    "acs_code": 72281,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 1,
    "total_deaths": 2,
    "total_injuries": 2,
    "card": 1,
    "cari": 1,
    "car": true,
    "hosd": 1,
    "hosi": null,
    "la_td": null,
    "la_ti": null,
    "un_td": null,
    "un_ti": null,
    "village_display_name": "دبل",
    "details_pending": true,
    "raw_status": "materialized"
  }
]
```

### ACCSTUDY-002
```json
[
  {
    "incident_id": "5c05e65e-c2bd-4db7-9633-7837749a2372",
    "acs_name": "Chebaa",
    "acs_code": 74130,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "car": null,
    "hosd": null,
    "hosi": null,
    "la_td": null,
    "la_ti": null,
    "un_td": null,
    "un_ti": null,
    "village_display_name": null,
    "details_pending": false,
    "raw_status": "materialized"
  }
]
```

### ACCSTUDY-003
```json
[
  {
    "incident_id": "61cfd98e-5e08-4b0f-9639-dfbc982f5fc8",
    "acs_name": "Houla",
    "acs_code": 73234,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 8,
    "total_deaths": 3,
    "total_injuries": 8,
    "card": null,
    "cari": null,
    "car": null,
    "hosd": null,
    "hosi": null,
    "la_td": null,
    "la_ti": null,
    "un_td": null,
    "un_ti": null,
    "village_display_name": null,
    "details_pending": false,
    "raw_status": "materialized"
  }
]
```

## Action_E / vehicle spot-check

Rows whose source text mentions `سيارة`:
```json
[
  {
    "tag": "ACCSTUDY-001",
    "action_en": "Bombs",
    "card": 1,
    "cari": 1,
    "car": true,
    "entity_fields_populated": true,
    "deaths": 1,
    "total_deaths": 2,
    "village": "Debl"
  },
  {
    "tag": "ACCSTUDY-006",
    "action_en": "Bombs",
    "card": null,
    "cari": null,
    "car": true,
    "entity_fields_populated": true,
    "deaths": null,
    "total_deaths": null,
    "village": "Kfar Kila"
  },
  {
    "tag": "ACCSTUDY-037",
    "action_en": null,
    "card": null,
    "cari": null,
    "car": null,
    "entity_fields_populated": false,
    "deaths": null,
    "total_deaths": null,
    "village": null
  },
  {
    "tag": "ACCSTUDY-061",
    "action_en": null,
    "card": null,
    "cari": null,
    "car": null,
    "entity_fields_populated": false,
    "deaths": null,
    "total_deaths": null,
    "village": null
  },
  {
    "tag": "ACCSTUDY-065",
    "action_en": null,
    "card": null,
    "cari": null,
    "car": null,
    "entity_fields_populated": false,
    "deaths": null,
    "total_deaths": null,
    "village": null
  },
  {
    "tag": "ACCSTUDY-068",
    "action_en": null,
    "card": null,
    "cari": null,
    "car": null,
    "entity_fields_populated": false,
    "deaths": null,
    "total_deaths": null,
    "village": null
  },
  {
    "tag": "ACCSTUDY-070",
    "action_en": "Bombs",
    "card": null,
    "cari": 1,
    "car": true,
    "entity_fields_populated": true,
    "deaths": null,
    "total_deaths": null,
    "village": "Meiss Ej-Jabal"
  },
  {
    "tag": "ACCSTUDY-082",
    "action_en": "Bombs",
    "card": null,
    "cari": null,
    "car": true,
    "entity_fields_populated": true,
    "deaths": null,
    "total_deaths": null,
    "village": "Tayr Harfa"
  }
]
```

Junk hallucination failures: ['ACCSTUDY-057']
Real-village unmatched (single_village*): ['ACCSTUDY-029', 'ACCSTUDY-033', 'ACCSTUDY-035', 'ACCSTUDY-037', 'ACCSTUDY-048', 'ACCSTUDY-061', 'ACCSTUDY-065', 'ACCSTUDY-068', 'ACCSTUDY-079', 'ACCSTUDY-091']

## Failures appendix

Total failing tags: 81

### ACCSTUDY-002 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=7', 'multi_event_fanout_short rows=1 expected=3', 'multi_event_injuries expected=7 best=0 root=0 total=0']
- expected deaths/injuries: 2/7; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "5c05e65e-c2bd-4db7-9633-7837749a2372",
    "village": "Chebaa",
    "acs_code": 74130,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-003 (bulletin_aggregate_8v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=8']
- expected deaths/injuries: 3/8; village_count=8; actual_rows=1
```json
[
  {
    "incident_id": "61cfd98e-5e08-4b0f-9639-dfbc982f5fc8",
    "village": "Houla",
    "acs_code": 73234,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 8,
    "total_deaths": 3,
    "total_injuries": 8,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-004 (single_village)
- reasons: ['single_deaths expected=1 best=6 total=6 root=3 entity=3']
- expected deaths/injuries: 1/0; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "8754a2f9-c117-4398-974b-87376a763aaf",
    "village": "Jibbayn",
    "acs_code": 62292,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 4,
    "total_deaths": 6,
    "total_injuries": 8,
    "card": 3,
    "cari": 4,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": true
  }
]
```

### ACCSTUDY-005 (bulletin_aggregate_6v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=6']
- expected deaths/injuries: 4/10; village_count=6; actual_rows=1
```json
[
  {
    "incident_id": "a200f81c-2fdf-40dc-a448-7add00d5e490",
    "village": "Qlaile Sour",
    "acs_code": 62287,
    "action_en": "Bombs",
    "deaths": 4,
    "injuries": 10,
    "total_deaths": 4,
    "total_injuries": 10,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-006 (single_village_revision)
- reasons: ['injuries_dropped_to_zero expected=2', 'single_injuries expected=2 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 0/2; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "04a92728-b848-47be-9fea-b3bf01198e5b",
    "village": "Kfar Kila",
    "acs_code": 73228,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-007 (bulletin_aggregate_6v)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=10', 'bulletin_fanout_short rows=1 expected_villages=6']
- expected deaths/injuries: 2/10; village_count=6; actual_rows=1
```json
[
  {
    "incident_id": "408972ad-a03c-4398-93b6-51028ee73f54",
    "village": "Kafra Bant Jbayl",
    "acs_code": 72257,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-008 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=6', 'multi_event_fanout_short rows=1 expected=3', 'multi_event_injuries expected=6 best=0 root=0 total=0']
- expected deaths/injuries: 1/6; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "25dffd40-a8f4-4ed6-a851-e5fb552e5683",
    "village": "Kfar Roummane",
    "acs_code": 71133,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-009 (bulletin_aggregate_9v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=9']
- expected deaths/injuries: 3/10; village_count=9; actual_rows=1
```json
[
  {
    "incident_id": "60e4bfe5-f9bb-42f3-8097-ee4f20fd88fe",
    "village": "Kfar Kila",
    "acs_code": 73228,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 10,
    "total_deaths": 3,
    "total_injuries": 10,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-010 (single_village)
- reasons: ['single_injuries expected=1 best=5 total=5 root=5 entity=0']
- expected deaths/injuries: 0/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "0d66a1a4-74a2-44d7-97db-511ec5e1d787",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Artillery Shelling",
    "deaths": 3,
    "injuries": 5,
    "total_deaths": 3,
    "total_injuries": 5,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-011 (bulletin_aggregate_5v)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=4', 'bulletin_fanout_short rows=4 expected_villages=5']
- expected deaths/injuries: 3/4; village_count=5; actual_rows=4
```json
[
  {
    "incident_id": "1118d29e-ddb2-40d7-a1c2-67fadb1ba71b",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "54e274c1-3a77-4d4c-ab59-6288210fcb4d",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "8c228b56-e11a-4aa6-bd20-dd736f98becc",
    "village": "Deir Mimas",
    "acs_code": 73167,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "ea44700c-6da5-40ea-a976-00188bacd472",
    "village": "Baraachit",
    "acs_code": 72227,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-012 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 3/3; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-015 (multi_village_exact)
- reasons: ['multi_event_injuries expected=3 best=6 root=6 total=6']
- expected deaths/injuries: 1/3; village_count=2; actual_rows=2
```json
[
  {
    "incident_id": "2139ee63-4b98-42e8-9fcf-d519d5918e7b",
    "village": "Tayr Falsay",
    "acs_code": 62271,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": 3,
    "total_deaths": null,
    "total_injuries": 3,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": true
  },
  {
    "incident_id": "58a71f84-092b-447e-801b-85e6783bf1fb",
    "village": "Tayr Falsay",
    "acs_code": 62271,
    "action_en": "Artillery Shelling",
    "deaths": 1,
    "injuries": 3,
    "total_deaths": 1,
    "total_injuries": 3,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-016 (bulletin_aggregate_7v)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=6', 'bulletin_fanout_short rows=2 expected_villages=7']
- expected deaths/injuries: 3/6; village_count=7; actual_rows=2
```json
[
  {
    "incident_id": "55d83a7c-57ea-44a4-be37-7974c9fb8793",
    "village": "Chebaa",
    "acs_code": 74130,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "cb6a1b14-5f05-416d-99d6-46295a179c60",
    "village": "Chebaa",
    "acs_code": 74130,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-017 (single_village)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=3 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 3/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "11eb4667-17b0-4437-b71d-a6e5ff765af2",
    "village": "Jouaiya",
    "acs_code": 62211,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "duplicate",
    "details_pending": false
  }
]
```

### ACCSTUDY-018 (bulletin_aggregate_5v)
- reasons: ['deaths_dropped_to_zero expected=4', 'injuries_dropped_to_zero expected=4', 'bulletin_fanout_short rows=2 expected_villages=5']
- expected deaths/injuries: 4/4; village_count=5; actual_rows=2
```json
[
  {
    "incident_id": "5386366f-5b9f-433b-ab5b-809e6c3f7210",
    "village": "Nabatiyeh El-Faouka",
    "acs_code": 71113,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "cb55b2f1-6098-4924-be4e-c5e2e5d54dd3",
    "village": "Rmaich",
    "acs_code": 72167,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-019 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 3/1; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-020 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 2/0; village_count=2; actual_rows=0
```json
[]
```

### ACCSTUDY-021 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/4; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-022 (single_village)
- reasons: ['injuries_dropped_to_zero expected=5', 'single_injuries expected=5 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 0/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "2b5d741f-35b5-4f75-9204-471b041bf7c4",
    "village": "Kfar Chouba",
    "acs_code": 74160,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "duplicate",
    "details_pending": false
  }
]
```

### ACCSTUDY-024 (bulletin_aggregate_7v)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=6', 'bulletin_fanout_short rows=1 expected_villages=7']
- expected deaths/injuries: 1/6; village_count=7; actual_rows=1
```json
[
  {
    "incident_id": "2a0935a2-e19b-46cf-8b38-dff0075afc62",
    "village": "Maarake",
    "acs_code": 62231,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-025 (bulletin_aggregate_5v)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=4', 'bulletin_fanout_short rows=2 expected_villages=5']
- expected deaths/injuries: 2/4; village_count=5; actual_rows=2
```json
[
  {
    "incident_id": "6e5d707d-0836-4149-a119-8c80f363eed8",
    "village": "Rmaich",
    "acs_code": 72167,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "e37d32a0-f710-499a-b9f9-95cb38609a28",
    "village": "Tayr Falsay",
    "acs_code": 62271,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-026 (multi_village_exact)
- reasons: ['injuries_dropped_to_zero expected=4', 'multi_event_fanout_short rows=2 expected=3', 'multi_event_injuries expected=4 best=0 root=0 total=0']
- expected deaths/injuries: 0/4; village_count=3; actual_rows=2
```json
[
  {
    "incident_id": "0e6fa624-324d-45b5-b280-f1fa46d2ff92",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "11d95fd9-bd06-44d5-8904-9ecf2e81faf7",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-028 (multi_village_exact)
- reasons: ['multi_event_fanout_short rows=2 expected=3', 'multi_event_injuries expected=2 best=1 root=1 total=1']
- expected deaths/injuries: 0/2; village_count=3; actual_rows=2
```json
[
  {
    "incident_id": "da75888a-16f8-4869-8960-ff430c40038e",
    "village": "Maroun Er-Ras",
    "acs_code": 72127,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "eb8d2249-9c80-41d8-8fa9-99f20c8c90f1",
    "village": "Maroun Er-Ras",
    "acs_code": 72127,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": 1,
    "total_deaths": null,
    "total_injuries": 1,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-029 (single_village)
- reasons: ['injuries_dropped_to_zero expected=1', 'single_injuries expected=1 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total', 'real_village_unmatched']
- expected deaths/injuries: 0/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "59c40360-dee5-40af-9260-523283cb49fa",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-031 (single_village_revision)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/5; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-032 (bulletin_aggregate_8v)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=4', 'bulletin_fanout_short rows=2 expected_villages=8']
- expected deaths/injuries: 3/4; village_count=8; actual_rows=2
```json
[
  {
    "incident_id": "f1dab056-7389-42c9-b947-0dc19ab62339",
    "village": "Aaynata Bent Jbayl",
    "acs_code": 72119,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "63b18bdb-0474-4447-a922-1f5f90106cdf",
    "village": "Khreibet Aakkar",
    "acs_code": 35330,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-033 (single_village)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=2', 'single_deaths expected=2 best=0 total=0 root=0 entity=0', 'single_injuries expected=2 best=0 total=0 root=0 entity=0', 'real_village_unmatched']
- expected deaths/injuries: 2/2; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "9036b7fe-9318-49bf-8e7f-0ef3986b936c",
    "village": null,
    "acs_code": null,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-034 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=1', 'multi_event_fanout_short rows=1 expected=2']
- expected deaths/injuries: 1/2; village_count=2; actual_rows=1
```json
[
  {
    "incident_id": "dd76980c-57dc-44f8-977a-df6e405f28bf",
    "village": "Qleiaat Aakkar",
    "acs_code": 35243,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": 2,
    "total_deaths": null,
    "total_injuries": 2,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-035 (single_village)
- reasons: ['NOTE_double_count_root_plus_entity_in_total', 'real_village_unmatched']
- expected deaths/injuries: 0/0; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "30bda911-f727-44c4-9a74-65fe7da6e498",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-037 (single_village)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=3 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0', 'real_village_unmatched', 'vehicle_entity_fields_empty']
- expected deaths/injuries: 3/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "0117bc0e-b22d-49ca-8270-b6ee3588c81c",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-039 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=2', 'multi_event_injuries expected=2 best=1 root=1 total=1']
- expected deaths/injuries: 2/2; village_count=2; actual_rows=2
```json
[
  {
    "incident_id": "fb3b1e5a-3b5e-4dad-b76c-b19bd31788cb",
    "village": "Aadchit Ech-Chqif",
    "acs_code": 71347,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "6f911134-d0aa-4b51-a0c2-46e4d5f62e59",
    "village": "Aadchit Ech-Chqif",
    "acs_code": 71347,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": 1,
    "total_deaths": null,
    "total_injuries": 1,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-040 (bulletin_aggregate_5v)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 5/10; village_count=5; actual_rows=0
```json
[]
```

### ACCSTUDY-041 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 0/5; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-042 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 0/3; village_count=3; actual_rows=0
```json
[]
```

### ACCSTUDY-043 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/4; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-044 (bulletin_aggregate_4v)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 5/4; village_count=4; actual_rows=0
```json
[]
```

### ACCSTUDY-045 (single_village_revision)
- reasons: ['single_injuries expected=6 best=4 total=4 root=4 entity=0']
- expected deaths/injuries: 1/6; village_count=1; actual_rows=2
```json
[
  {
    "incident_id": "f01960bb-4e61-4664-8ae4-88b8cfc711c2",
    "village": "Maroun Er-Ras",
    "acs_code": 72127,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "8e67e11f-1838-417c-8341-367408cb6666",
    "village": "Maroun Er-Ras",
    "acs_code": 72127,
    "action_en": "Artillery Shelling",
    "deaths": 1,
    "injuries": 4,
    "total_deaths": 1,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-046 (bulletin_aggregate_4v)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=3', 'bulletin_fanout_short rows=1 expected_villages=4']
- expected deaths/injuries: 3/3; village_count=4; actual_rows=1
```json
[
  {
    "incident_id": "3cdb0bb9-507d-45e6-bd11-341483141745",
    "village": "Khreibet Hasbaiya",
    "acs_code": 74181,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-047 (single_village_revision)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/2; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-048 (single_village)
- reasons: ['injuries_dropped_to_zero expected=5', 'single_injuries expected=5 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total', 'real_village_unmatched']
- expected deaths/injuries: 0/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "8335caa3-a798-4152-aff5-25e8165adc67",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-049 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 4/1; village_count=2; actual_rows=0
```json
[]
```

### ACCSTUDY-051 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 3/4; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-052 (bulletin_aggregate_9v)
- reasons: ['bulletin_fanout_short rows=2 expected_villages=9']
- expected deaths/injuries: 1/8; village_count=9; actual_rows=2
```json
[
  {
    "incident_id": "79bc25b9-1997-4a0d-9a12-5e44ef08b9f3",
    "village": "Nabatiyeh El-Faouka",
    "acs_code": 71113,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "2f0922f0-a1c7-4b9c-9d21-45328670050e",
    "village": "Bent Jbayl",
    "acs_code": 72111,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 4,
    "total_deaths": 3,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-053 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=2', 'multi_event_fanout_short rows=1 expected=3', 'multi_event_injuries expected=3 best=1 root=1 total=1']
- expected deaths/injuries: 2/3; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "0f84c2b1-6d82-4ed6-978d-d93f726d5cb3",
    "village": "Kafra Bant Jbayl",
    "acs_code": 72257,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": 1,
    "total_deaths": null,
    "total_injuries": 1,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-054 (single_village)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 3/4; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-056 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=4', 'injuries_dropped_to_zero expected=5', 'multi_event_fanout_short rows=1 expected=3', 'multi_event_injuries expected=5 best=0 root=0 total=0']
- expected deaths/injuries: 4/5; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "854eb3cc-fb9c-4a94-b0c7-bb2ee0fa861e",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "duplicate",
    "details_pending": false
  }
]
```

### ACCSTUDY-057 (irrelevant)
- reasons: ['junk_hallucination village=True cas=False']
- expected deaths/injuries: None/None; village_count=0; actual_rows=1
```json
[
  {
    "incident_id": "8e421324-2547-4c9b-a15c-80ceeafd67a5",
    "village": "Jezzine",
    "acs_code": 63111,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-058 (single_village)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=4', 'single_deaths expected=2 best=0 total=0 root=0 entity=0', 'single_injuries expected=4 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 2/4; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "cc01adda-c694-4aef-9fc0-589394478e7a",
    "village": "Khreibet Aakkar",
    "acs_code": 35330,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-060 (bulletin_aggregate_6v)
- reasons: ['bulletin_fanout_short rows=4 expected_villages=6']
- expected deaths/injuries: 1/4; village_count=6; actual_rows=4
```json
[
  {
    "incident_id": "bd11fe9b-61e1-4876-8415-26bc743ac7e4",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 4,
    "total_deaths": 1,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "b9e8f6dd-4cd8-4e2a-b909-16f0fc02e168",
    "village": "Aayta Ech-Chaab",
    "acs_code": 72183,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "aff055a6-9c98-4351-9e16-eb28a56ac75e",
    "village": "Chebaa",
    "acs_code": 74130,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "48b77b88-baa4-4d33-ba04-34780079d46b",
    "village": "Aadchit Ech-Chqif",
    "acs_code": 71347,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-061 (single_village)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=1', 'single_deaths expected=2 best=0 total=0 root=0 entity=0', 'single_injuries expected=1 best=0 total=0 root=0 entity=0', 'real_village_unmatched', 'vehicle_entity_fields_empty']
- expected deaths/injuries: 2/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "972d4b30-887e-4d6b-9440-72a6d2322099",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-062 (bulletin_aggregate_6v)
- reasons: ['bulletin_fanout_short rows=4 expected_villages=6']
- expected deaths/injuries: 1/3; village_count=6; actual_rows=4
```json
[
  {
    "incident_id": "2d97839d-e864-4e5d-b339-b625de99cb29",
    "village": "Jouaiya",
    "acs_code": 62211,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 3,
    "total_deaths": 1,
    "total_injuries": 3,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "ff33a9c3-5b89-407b-a283-99f89611a92a",
    "village": "Jouaiya",
    "acs_code": 62211,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 6,
    "total_deaths": 1,
    "total_injuries": 6,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "33c10e78-d3f8-4ab8-adf9-82e268b878fe",
    "village": "Blida",
    "acs_code": 73288,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "c0f2f4e4-40f2-4b1c-bcf4-2fd6bee21dcd",
    "village": "Kfar Chouba",
    "acs_code": 74160,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-063 (bulletin_aggregate_5v)
- reasons: ['bulletin_fanout_short rows=4 expected_villages=5']
- expected deaths/injuries: 3/4; village_count=5; actual_rows=4
```json
[
  {
    "incident_id": "0d47cf1d-0309-41b5-9151-3c766b3970a2",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "339f31e9-f202-442c-80b1-50e469a4d20f",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Bombs",
    "deaths": 5,
    "injuries": 4,
    "total_deaths": 5,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "16eaeb6f-2eb4-42a9-98dd-40140a8ed228",
    "village": "Kfar Roummane",
    "acs_code": 71133,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 8,
    "total_deaths": 1,
    "total_injuries": 8,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "dc9ca900-9248-4213-a47a-1667a15b2d32",
    "village": "Tayr Harfa",
    "acs_code": 62295,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-064 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 2/1; village_count=2; actual_rows=0
```json
[]
```

### ACCSTUDY-065 (single_village)
- reasons: ['injuries_dropped_to_zero expected=1', 'single_injuries expected=1 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total', 'real_village_unmatched', 'vehicle_entity_fields_empty']
- expected deaths/injuries: 0/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "cbcfc87a-d97a-4719-9b53-cad5fa237336",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-066 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=6', 'multi_event_fanout_short rows=1 expected=2', 'multi_event_injuries expected=6 best=0 root=0 total=0']
- expected deaths/injuries: 3/6; village_count=2; actual_rows=1
```json
[
  {
    "incident_id": "ac0f41cf-6299-42b3-a029-eba1dfeb8bf5",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-067 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 4/7; village_count=3; actual_rows=0
```json
[]
```

### ACCSTUDY-068 (single_village)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=1', 'single_deaths expected=1 best=0 total=0 root=0 entity=0', 'single_injuries expected=1 best=0 total=0 root=0 entity=0', 'real_village_unmatched', 'vehicle_entity_fields_empty']
- expected deaths/injuries: 1/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "5dc189e7-3a38-49ec-a65c-e855f44a0180",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-071 (single_village_revision)
- reasons: ['single_injuries expected=5 best=4 total=4 root=4 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 2/5; village_count=1; actual_rows=2
```json
[
  {
    "incident_id": "94aa92d4-960a-4463-89dd-1ec4e6de1dd6",
    "village": "Tayr Harfa",
    "acs_code": 62295,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": null,
    "total_deaths": 2,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": 2,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  },
  {
    "incident_id": "687931ad-05d0-460e-825d-10b0dd90ce7e",
    "village": "Tayr Harfa",
    "acs_code": 62295,
    "action_en": "Artillery Shelling",
    "deaths": 2,
    "injuries": 4,
    "total_deaths": 2,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-073 (single_village)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=2', 'single_deaths expected=3 best=0 total=0 root=0 entity=0', 'single_injuries expected=2 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 3/2; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "453692b2-0789-41a1-be1b-c379e46aede5",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "duplicate",
    "details_pending": false
  }
]
```

### ACCSTUDY-075 (single_village)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=1 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 1/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "a06dcd36-bf67-4628-a6f4-dc9d20fbe401",
    "village": "Hasbaiya",
    "acs_code": 74111,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-076 (single_village)
- reasons: ['injuries_dropped_to_zero expected=3', 'single_injuries expected=3 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 0/3; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "d05a76e8-8b1b-411f-acbc-06cbfd8b3a30",
    "village": "Marjaayoun",
    "acs_code": 73111,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-078 (single_village_revision)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/5; village_count=1; actual_rows=0
```json
[]
```

### ACCSTUDY-079 (single_village)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=1 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0', 'real_village_unmatched']
- expected deaths/injuries: 1/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "f90d8fa7-f9b9-4c1f-ab48-5cf5e56dbf89",
    "village": null,
    "acs_code": null,
    "action_en": null,
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "error",
    "details_pending": true
  }
]
```

### ACCSTUDY-080 (bulletin_aggregate_8v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=8']
- expected deaths/injuries: 3/6; village_count=8; actual_rows=1
```json
[
  {
    "incident_id": "0166c380-3949-45ed-894b-bd901fec87db",
    "village": "Debl",
    "acs_code": 72281,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 6,
    "total_deaths": 3,
    "total_injuries": 6,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-083 (single_village)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=2 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 2/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "8573bf54-a677-468c-ae8c-f5f77605a299",
    "village": "Hasbaiya",
    "acs_code": 74111,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-084 (multi_village_exact)
- reasons: ['multi_event_fanout_short rows=1 expected=3']
- expected deaths/injuries: 0/1; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "f14bce83-a4f1-44e2-83d0-288969d9b8ed",
    "village": "Bent Jbayl",
    "acs_code": 72111,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": 1,
    "total_deaths": null,
    "total_injuries": 1,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-085 (bulletin_aggregate_4v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=4']
- expected deaths/injuries: 3/4; village_count=4; actual_rows=1
```json
[
  {
    "incident_id": "2dc66bc3-a33a-4292-bde7-6538645c27d9",
    "village": "Qleiaat Aakkar",
    "acs_code": 35243,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 4,
    "total_deaths": 3,
    "total_injuries": 4,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-086 (single_village)
- reasons: ['deaths_dropped_to_zero expected=1', 'injuries_dropped_to_zero expected=1', 'single_deaths expected=1 best=0 total=0 root=0 entity=0', 'single_injuries expected=1 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 1/1; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "586be62a-83d9-48db-93f6-1fcc127e0c4a",
    "village": "Qleiaat Aakkar",
    "acs_code": 35243,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-087 (bulletin_aggregate_7v)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=5', 'bulletin_fanout_short rows=1 expected_villages=7']
- expected deaths/injuries: 2/5; village_count=7; actual_rows=1
```json
[
  {
    "incident_id": "70d3548d-7ff1-4a68-b41a-86e91c380ef4",
    "village": "Tayr Falsay",
    "acs_code": 62271,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-088 (bulletin_aggregate_9v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=9']
- expected deaths/injuries: 2/6; village_count=9; actual_rows=1
```json
[
  {
    "incident_id": "57bea7e7-56a4-4fbe-af94-0d229cdc220f",
    "village": "Marjaayoun",
    "acs_code": 73111,
    "action_en": "Bombs",
    "deaths": 2,
    "injuries": 6,
    "total_deaths": 2,
    "total_injuries": 6,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-089 (multi_village_exact)
- reasons: ['deaths_dropped_to_zero expected=2', 'injuries_dropped_to_zero expected=1', 'multi_event_fanout_short rows=1 expected=3', 'multi_event_injuries expected=1 best=0 root=0 total=0']
- expected deaths/injuries: 2/1; village_count=3; actual_rows=1
```json
[
  {
    "incident_id": "8419ecf4-a571-4e62-8691-ae79543a37cd",
    "village": "Blida",
    "acs_code": 73288,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-090 (multi_village_exact)
- reasons: ['no_active_incident_rows']
- expected deaths/injuries: 1/0; village_count=2; actual_rows=0
```json
[]
```

### ACCSTUDY-091 (single_village_revision)
- reasons: ['deaths_dropped_to_zero expected=2', 'single_deaths expected=2 best=0 total=0 root=0 entity=0', 'real_village_unmatched']
- expected deaths/injuries: 2/0; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "637a5650-ce5f-4af0-b959-1d5454b594b9",
    "village": null,
    "acs_code": null,
    "action_en": "Artillery Shelling",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-092 (bulletin_aggregate_7v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=7']
- expected deaths/injuries: 1/5; village_count=7; actual_rows=1
```json
[
  {
    "incident_id": "b7b54565-f6b5-41a6-9ba1-c7d43df85821",
    "village": "Meiss Ej-Jabal",
    "acs_code": 73250,
    "action_en": "Bombs",
    "deaths": 1,
    "injuries": 5,
    "total_deaths": 1,
    "total_injuries": 5,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-093 (bulletin_aggregate_4v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=4']
- expected deaths/injuries: 5/6; village_count=4; actual_rows=1
```json
[
  {
    "incident_id": "0e563c30-6084-4a98-bcc8-de30269ffd53",
    "village": "Kfar Kila",
    "acs_code": 73228,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 10,
    "total_deaths": 3,
    "total_injuries": 10,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-094 (bulletin_aggregate_4v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=4']
- expected deaths/injuries: 5/3; village_count=4; actual_rows=1
```json
[
  {
    "incident_id": "d2f94b92-37ec-482b-993f-a6515af451ef",
    "village": "Maroun Er-Ras",
    "acs_code": 72127,
    "action_en": "Bombs",
    "deaths": 5,
    "injuries": 3,
    "total_deaths": 5,
    "total_injuries": 3,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-095 (multi_village_exact)
- reasons: ['injuries_dropped_to_zero expected=5', 'multi_event_fanout_short rows=1 expected=2', 'multi_event_injuries expected=5 best=0 root=0 total=0']
- expected deaths/injuries: 0/5; village_count=2; actual_rows=1
```json
[
  {
    "incident_id": "7e7b6651-e76b-489f-b60c-966fbe79c073",
    "village": "Tayr Harfa",
    "acs_code": 62295,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-096 (single_village)
- reasons: ['injuries_dropped_to_zero expected=4', 'single_injuries expected=4 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 0/4; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "93a58928-884a-443c-a54d-d1a777008119",
    "village": "Khiyam Marjaayoun",
    "acs_code": 73159,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-097 (single_village)
- reasons: ['deaths_dropped_to_zero expected=3', 'injuries_dropped_to_zero expected=5', 'single_deaths expected=3 best=0 total=0 root=0 entity=0', 'single_injuries expected=5 best=0 total=0 root=0 entity=0']
- expected deaths/injuries: 3/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "cf9c0586-af25-4795-85b0-75436d2e1d94",
    "village": "Jibbayn",
    "acs_code": 62292,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-099 (single_village)
- reasons: ['injuries_dropped_to_zero expected=5', 'single_injuries expected=5 best=0 total=0 root=0 entity=0', 'NOTE_double_count_root_plus_entity_in_total']
- expected deaths/injuries: 0/5; village_count=1; actual_rows=1
```json
[
  {
    "incident_id": "e90b9c70-d4fc-4480-80fd-16f28bc6d39d",
    "village": "Hasbaiya",
    "acs_code": 74111,
    "action_en": "Bombs",
    "deaths": null,
    "injuries": null,
    "total_deaths": null,
    "total_injuries": null,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

### ACCSTUDY-100 (bulletin_aggregate_6v)
- reasons: ['bulletin_fanout_short rows=1 expected_villages=6']
- expected deaths/injuries: 3/3; village_count=6; actual_rows=1
```json
[
  {
    "incident_id": "b7e81943-dcbe-4d8f-afee-ec813f5c2e74",
    "village": "Chebaa Farms",
    "acs_code": 74183,
    "action_en": "Bombs",
    "deaths": 3,
    "injuries": 3,
    "total_deaths": 3,
    "total_injuries": 3,
    "card": null,
    "cari": null,
    "hosd": null,
    "hosi": null,
    "raw_status": "materialized",
    "details_pending": false
  }
]
```

## New bugs / follow-ups (do not fix in this task)

1. **Total_D/Total_Inj double-count** when entity casualties are also copied into root `Death`/`Injuries` (ACCSTUDY-001 → totals 2/2). Likely rollup stage after category_mapper fix.
2. **Workbook import path does not reliably fan out** multi-village/multi-event rows to N incidents; depends on later materialization sweep, which raced CNRS traffic and often left 1 row (ACCSTUDY-002/003).
3. **`casualty_count_backstop`** nulls LLM counts for `missing_evidence_span` / `digit_not_in_source` partly because import raw_text prefixes `NOTE: ACCSTUDY-XXX`, shifting evidence spans. Top failure modes this run: `injuries_dropped_to_zero` (36), `deaths_dropped_to_zero` (30).
4. **Tier2 dedup backstop** can fail with `A duplicate incident must have a raw message and village` leaving `details_pending=true`.
5. **Cross-entity leakage on ACCSTUDY-001:** car-strike also set `hosd=1` (hospital deaths) despite text only mentioning a vehicle — category_mapper / Tier2 category bleed. Tracking: `ACCSTUDY-001`, expected HosD empty, actual `hosd=1`.
6. **18 tags** had no active incident rows after soft-delete/duplicate race (`no_active_incident_rows`) — re-run with `pipeline-worker` stopped for a clean measurement.

## Clean re-run recipe

1. Manually execute `scripts/accuracy_study/sql/delete_accstudy_batch_war_news_devtest.sql` against `war_news_devtest`.
2. Keep `pipeline-worker` (and CNRS poll) **stopped** on the dev stack.
3. Import `accuracy_study_import_template_FIXED.xlsx` via `POST http://localhost:8001/api/incidents/import`.
4. Wait for enrichment (or run `scripts/accuracy_study/resume_enrichment.py` / `resume_tier2_only.py`).
5. Optionally trigger a **single** materialization sweep with worker still isolated from CNRS inserts.
6. Re-run `python scripts/accuracy_study/score_postfix.py`.

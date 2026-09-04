# Casualty Transition Live Validation

- Model: `qwen2.5:7b`
- Cases: `10`
- Overall: `7 passed / 3 failed`
- Verdict: Needs targeted prompt revision. The model missed at least one explicit injury-to-death follow-up with a restated casualty tally.

## Evaluation Set

### real_transition_restate_mifdoun_425
- Category: `transition_plus_restated`
- Origin: `real`
- Raw message id: `425`
- Source: `alakhbar_news`
- Received at: `2026-08-26T09:07:23.741025+03:00`
- Notes: Real follow-up with both transition wording and a restated remaining-injured count.
- Raw text:

```text
«الوكالة الوطنية»: استشهاد أحد جريحي انفجار تشريكة العبوات الناسفة التي وضعها العدو الإسرائيلي قرب الساتر الترابي بين ميفدون وزوطر الشرقية لتصبح الحصيلة 3 شهداء وجريح واحد
```

### supp_transition_restate_ainata
- Category: `transition_plus_restated`
- Origin: `supplemented`
- Notes: Supplemented realistic follow-up in ministry/register style: death from prior injuries plus explicit remaining count.
- Raw text:

```text
أفادت وزارة الصحة أن أحد الجرحى في غارة عيناثا فارق الحياة ليرتفع عدد الشهداء إلى 2 ويبقى 4 جرحى في المستشفيات.
```

### supp_transition_restate_khiam
- Category: `transition_plus_restated`
- Origin: `supplemented`
- Notes: Supplemented realistic newsroom follow-up with updated total and restated remaining injured.
- Raw text:

```text
متابعة لغارة الخيام: توفي جريح ثانٍ متأثراً بإصابته، وباتت الحصيلة 3 شهداء وجرحان.
```

### supp_transition_death_only_aaita
- Category: `transition_only_death_followup`
- Origin: `supplemented`
- Notes: Supplemented pure death-only follow-up with no restated remaining injuries.
- Raw text:

```text
توفي أحد الجرحى جراء إصابته في الغارة على عيتا الشعب.
```

### supp_transition_death_only_houla
- Category: `transition_only_death_followup`
- Origin: `supplemented`
- Notes: Supplemented ministry-style death-only follow-up; no refreshed injury total is stated.
- Raw text:

```text
أعلنت وزارة الصحة وفاة أحد المصابين في قصف حولا متأثراً بجراحه.
```

### supp_transition_death_only_bintjbeil
- Category: `transition_only_death_followup`
- Origin: `supplemented`
- Notes: Supplemented concise channel-style death-only follow-up.
- Raw text:

```text
فارق أحد الجرحى الحياة بعد ساعات من الغارة على بنت جبيل.
```

### real_additive_arabsalim_2413
- Category: `additive_no_transition`
- Origin: `real`
- Raw message id: `2413`
- Source: `mehwaralmokawma`
- Received at: `2026-08-28T09:26:50.278811+03:00`
- Notes: Real casualty report with a final tally, but no injury-to-death follow-up wording.
- Raw text:

```text
شهيدة و6 جرحى من بينهم طفلة في عربصاليم

صدر عن مركز عمليات طوارئ الصحة التابع لوزارة الصحة العامة بيان أعلن أن الحصيلة النهائية لغارة العدو الإسرائيلي على بلدة عربصاليم قضاء النبطية أدت إلى شهيدة و6 جرجى من بينهم طفلة وسيدة ومسنان.
```

### real_additive_roueiss_3077
- Category: `additive_no_transition`
- Origin: `real`
- Raw message id: `3077`
- Source: `nabatiehchannel`
- Received at: `2026-09-03T09:13:41.833083+03:00`
- Notes: Real initial casualty mention: one dead and one injured in the same report, not a follow-up transition.
- Raw text:

```text
شهيد و جريح جراء غارة من مسيره استهدفت فجراً حي الرويس في النبطيه
```

### real_additive_shebaa_791
- Category: `additive_no_transition`
- Origin: `real`
- Raw message id: `791`
- Source: `bintjbeilnews`
- Received at: `2026-08-26T09:07:28.434424+03:00`
- Notes: Real plain injury report with no death and no follow-up wording.
- Raw text:

```text
وقوع إصابة بعدما ألقت محلقة قنبلة صوتية باتجاه أحد رعاة المواشي في بلدة شبعا

An injury occurred after a drone dropped a sound bomb towards a livestock herder in the town of Shebaa.
```

### real_ambiguous_habboush_2698
- Category: `ambiguous_borderline`
- Origin: `real`
- Raw message id: `2698`
- Source: `ALJADEED_NEWS`
- Received at: `2026-09-02T13:58:45.587367+03:00`
- Notes: Real borderline case: the text says the child died of wounds sustained earlier the same day, which semantically implies an injury-to-death transition but not with the canonical phrase.
- Raw text:

```text
مأساة في حبوش.. شهيد وفتى جريحأفاد مراسل "الجديد" باستشهاد الطفل محمد علي إبراهيم متأثرًا بجراحه التي أُصيب بها عصر اليوم، إثر انفجار قنبلة من مخلفات العدوان الإسرائيلي في حي العريض في بلدة حبوش كما أُصيب فتى آخر في الحادثة#اخبار_الجديد #لبنان #جنوب_لبنان https://t.co/99n1tgyxgP
 https://x.com/ALJADEEDNEWS/status/2094470871679123674
August 31, 2026 at 07:02PM
```

## Per-Message Results

### real_transition_restate_mifdoun_425
- Category: `transition_plus_restated`
- Result: `FAIL`
- Elapsed seconds: `65.48`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": null,
  "action_description": "انفجار تشريكة العبوات الناسفة",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 3,
        "total_injuries": 1,
        "deaths": 3,
        "injuries": 1,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 3,
    "total_injuries": 1,
    "deaths": 3,
    "injuries": 1,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:20:39.956283Z"
}
```

### supp_transition_restate_ainata
- Category: `transition_plus_restated`
- Result: `PASS`
- Elapsed seconds: `69.18`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "عيناثا"
  ],
  "action_description": "غارة",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 2,
        "total_injuries": 4,
        "deaths": 1,
        "injuries": 4,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 2,
    "total_injuries": 4,
    "deaths": 1,
    "injuries": 4,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [
    {
      "from_status": "injured",
      "to_status": "deceased",
      "count": 1
    }
  ],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:21:49.134511Z"
}
```

### supp_transition_restate_khiam
- Category: `transition_plus_restated`
- Result: `PASS`
- Elapsed seconds: `57.78`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": null,
  "action_description": "غارة",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 3,
        "total_injuries": 2,
        "deaths": 3,
        "injuries": 2,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 3,
    "total_injuries": 2,
    "deaths": 3,
    "injuries": 2,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [
    {
      "from_status": "injured",
      "to_status": "deceased",
      "count": 1
    }
  ],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:22:46.912593Z"
}
```

### supp_transition_death_only_aaita
- Category: `transition_only_death_followup`
- Result: `PASS`
- Elapsed seconds: `55.87`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "عيتا الشعب"
  ],
  "action_description": null,
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 1,
        "total_injuries": null,
        "deaths": 1,
        "injuries": null,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 1,
    "total_injuries": null,
    "deaths": 1,
    "injuries": null,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [
    {
      "from_status": "injured",
      "to_status": "deceased",
      "count": 1
    }
  ],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:23:42.780122Z"
}
```

### supp_transition_death_only_houla
- Category: `transition_only_death_followup`
- Result: `FAIL`
- Elapsed seconds: `33.03`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "حولا"
  ],
  "action_description": "قصف",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 1,
        "total_injuries": null,
        "deaths": 1,
        "injuries": null,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 1,
    "total_injuries": null,
    "deaths": 1,
    "injuries": null,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:24:15.810258Z"
}
```

### supp_transition_death_only_bintjbeil
- Category: `transition_only_death_followup`
- Result: `PASS`
- Elapsed seconds: `39.48`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "بنت جبيل"
  ],
  "action_description": null,
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": null,
        "total_injuries": null,
        "deaths": 1,
        "injuries": null,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": null,
    "total_injuries": null,
    "deaths": 1,
    "injuries": null,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [
    {
      "from_status": "injured",
      "to_status": "deceased",
      "count": 1
    }
  ],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:24:55.293014Z"
}
```

### real_additive_arabsalim_2413
- Category: `additive_no_transition`
- Result: `PASS`
- Elapsed seconds: `45.29`
- Expected:

```json
[]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "عربصاليم"
  ],
  "action_description": "غارة عدوان إسرائيلي",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 1,
        "total_injuries": 6,
        "deaths": 1,
        "injuries": 6,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": 1
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 1,
    "total_injuries": 6,
    "deaths": 1,
    "injuries": 6,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": 1
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:25:40.583689Z"
}
```

### real_additive_roueiss_3077
- Category: `additive_no_transition`
- Result: `PASS`
- Elapsed seconds: `30.59`
- Expected:

```json
[]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "النبطية"
  ],
  "action_description": "غارة من مسيره استهدفت فجراً حي الرويس",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 1,
        "total_injuries": 1,
        "deaths": 1,
        "injuries": 1,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 1,
    "total_injuries": 1,
    "deaths": 1,
    "injuries": 1,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:26:11.176276Z"
}
```

### real_additive_shebaa_791
- Category: `additive_no_transition`
- Result: `PASS`
- Elapsed seconds: `39.01`
- Expected:

```json
[]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "شبعا"
  ],
  "action_description": "ألقت محلقة قنبلة صوتية باتجاه أحد رعاة المواشي",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": null,
        "total_injuries": 1,
        "deaths": null,
        "injuries": 1,
        "male_deaths": null,
        "male_injuries": 1,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": null,
    "total_injuries": 1,
    "deaths": null,
    "injuries": 1,
    "male_deaths": null,
    "male_injuries": 1,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:26:50.187647Z"
}
```

### real_ambiguous_habboush_2698
- Category: `ambiguous_borderline`
- Result: `FAIL`
- Elapsed seconds: `36.02`
- Expected:

```json
[
  {
    "from_status": "injured",
    "to_status": "deceased",
    "count": 1
  }
]
```

- Actual:

```json
[]
```

- Full extraction:

```json
{
  "is_relevant": true,
  "village": [
    "حبوش"
  ],
  "action_description": "انفجار قنبلة من مخلفات العدوان الإسرائيلي",
  "categories": {
    "casualty_demographics": {
      "did": null,
      "name": null,
      "casualties": {
        "total_deaths": 1,
        "total_injuries": 1,
        "deaths": 1,
        "injuries": 1,
        "male_deaths": null,
        "male_injuries": null,
        "female_deaths": null,
        "female_injuries": null,
        "children_deaths": null,
        "children_injuries": null
      },
      "vehicles": null
    }
  },
  "casualties": {
    "total_deaths": 1,
    "total_injuries": 1,
    "deaths": 1,
    "injuries": 1,
    "male_deaths": null,
    "male_injuries": null,
    "female_deaths": null,
    "female_injuries": null,
    "children_deaths": null,
    "children_injuries": null
  },
  "casualty_transitions": [],
  "presence_category_keys": [
    "casualty_demographics"
  ],
  "extraction_tier": 1,
  "model": "qwen2.5:7b",
  "extracted_at": "2026-09-03T07:27:26.212013Z"
}
```

## Category Breakdown

- `transition_plus_restated`: `2 passed / 1 failed`
- `transition_only_death_followup`: `2 passed / 1 failed`
- `additive_no_transition`: `3 passed / 0 failed`
- `ambiguous_borderline`: `0 passed / 1 failed`

## Final Verdict

Needs targeted prompt revision. The model missed at least one explicit injury-to-death follow-up with a restated casualty tally.

## Proposed Prompt Revision (Not Applied)

Add one mandatory rule to the `casualty_transitions` instruction: when the text explicitly says that a previously injured person died, including `استشهاد أحد جريحي/الجرحى`, `وفاة أحد المصابين متأثراً بجراحه`, or `فارق أحد الجرحى الحياة`, always emit `[{"from_status":"injured","to_status":"deceased","count":1}]`. This remains required even when the message restates a new total or does not state a remaining-injury count.

## Revision + Backstop Results

### Updated Prompt Text

Applied to both `GENERAL_EXTRACTION_PROMPT` and the combined Tier-1 prompt:

- Mandatory rule: when the text explicitly says a previously injured person died, emit `[{"from_status":"injured","to_status":"deceased","count":1}]` even if the same message also restates a new total or remaining-injured count.
- Explicitly named forms: `استشهاد أحد جريحي/الجرحى`, `وفاة أحد المصابين متأثراً بجراحه`, and `فارق أحد الجرحى الحياة`.
- Multi-clause rule: the transition trigger and the refreshed tally may appear in different clauses of the same long sentence and still describe one follow-up update.

### Deterministic Keyword Backstop

Implemented a cheap normalized-text scan with these trigger families:

- `استشهاد أحد جريحي/الجرحى`
- `وفاة أحد المصابين متأثراً بجراحه`
- `فارق أحد الجرحى الحياة`
- `توفي أحد الجرحى/المصابين`
- `وفاة/توفي جريح متأثراً بإصابته أو بجراحه`
- `استشهاد/وفاة متأثراً بجراحه التي أصيب بها`
- `فارق الحياة بعد إصابة سابقة`

Reconciliation now reuses the existing review-flag path in merge:

- LLM transition present + keyword hit: proceed normally.
- LLM transition empty + no keyword hit: proceed normally.
- LLM transition empty + keyword hit: set the existing review flag and record `possible_missed_casualty_transition` in merge audit data with matched keywords and note `possible casualty transition detected in text but not extracted - needs verification`.
- The inverse case (`LLM transition` with no keyword support) was left as a future hardening option to avoid adding review noise before seeing broader real-data patterns.

### Local Verification

- `python -m pytest tests\test_casualty_transition_extraction.py tests\test_casualty_transition_merge.py tests\test_casualty_transition_backstop.py`
- Result on September 3, 2026: `14 passed`
- The backstop positively matches the three named missed-transition texts: `real_transition_restate_mifdoun_425`, `supp_transition_death_only_houla`, and `real_ambiguous_habboush_2698`.
- The backstop stays clean on the three `additive_no_transition` cases: `real_additive_arabsalim_2413`, `real_additive_roueiss_3077`, and `real_additive_shebaa_791`.
- Merge regression coverage confirms that when extraction returns `casualty_transitions=[]` but the text matches the backstop, the incident is flagged for review and the audit trail records the backstop evidence.

### Step 3 Re-Validation Status

The live 10-case revalidation script was updated and rerun on September 3, 2026, but the actual extractor call was blocked in this environment before model evaluation:

- Error: `ConnectError: [WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions`
- Cause: sandboxed execution could not reach the local/LAN Ollama endpoint configured for extraction.

Because of that block, fresh post-revision LLM outcomes for Houla and Mifdoun are still unavailable from this run. What is verified end to end is the deterministic fallback behavior:

- If Houla, Mifdoun, or Habboush still miss at the LLM layer after the prompt revision, the new keyword backstop catches them and routes the merge to review instead of silently trusting `casualty_transitions=[]`.
- On the three `additive_no_transition` controls, the backstop produces no false positives in local tests.

To complete the remaining Step 3 named-case check, rerun `scripts/phase2-extraction-live-check/validate_casualty_transition_live.py` from an environment allowed to reach the configured Ollama service, then append the resulting Houla/Mifdoun pass/fail statuses here.

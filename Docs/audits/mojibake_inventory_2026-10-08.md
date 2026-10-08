# Mojibake inventory (read-only)

| file | affected lines | sample | introduced by |
|---|---:|---|---|
| `app/core/llm_knowledge/CHANGELOG.md` | 1 | `carried double-encoded text (`ØªÙ…Ø´ÙŠØ·`).` → `carried double-encoded text (`تمشيط`).` | git unavailable in scan runtime |
| `tests/test_llm_knowledge_rule_integrity.py` | 1 | `    assert MOJIBAKE.search("described `ØªÙ…Ø´ÙŠØ·` / sweeping")` → `    assert MOJIBAKE.search("described `تمشيط` / sweeping")` | git unavailable in scan runtime |
| `tests/test_red_alert_collector.py` | 1 | `    arnoun = _village(15, "Ø£Ø±Ù†ÙˆÙ†", caza_en="Nabatiye")` → `    arnoun = _village(15, "أرنون", caza_en="Nabatiye")` | git unavailable in scan runtime |
| `tests/news/test_incident_detail.py` | 1 | `            action_ar=f"Ø­Ø§Ù„Ø© {marker}",` → `            action_ar=f"حالة {marker}",` | git unavailable in scan runtime |
| `Data/VillageLocationAliases.json` | 30 | `        "alias_text": "Ø§Ù„Ù†Ø¨Ø·ÙŠØ©",` → `        "alias_text": "النبطية",` | git unavailable in scan runtime |

Affected files: 5.

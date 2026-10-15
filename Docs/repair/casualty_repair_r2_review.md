# Casualty repair dry-run

Generated: 20261014_111747Z

## Summary

- corrected: 1
- unchanged: 0
- needs_reextraction: 0
- source_missing: 0
- village_mismatch: 5
- conflict_flagged: 0
- skipped_admin_edited: 0
- failed: 0

## Incidents

| Incident | Village | Date | Current | Proposed | Class | Reason | Attributed villages | Sources | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 4dab80b0-55d2-4f22-a7e1-04df1c4a15da | Chaqra | 2026-10-13 | {"deaths": 1, "injuries": null, "total_deaths": 1, "total_injuries": null, "detail.male_d": 1, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | village_mismatch | casualty numbers in the source belong to: Maad — not this village | Maad | 42520:raw_messages | Maad: شهيد |
| af927dd4-7328-4e90-b941-4e395d5287f3 | Nabatiyeh El-Faouka | 2026-09-09 | {"deaths": 11, "injuries": null, "total_deaths": 11, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | corrected | stored values positively disproved by deterministic count/evidence validation |  | 32708:raw_messages; 32548:raw_messages; 28588:raw_messages; 9182:merged_from_snapshot; 8986:merged_from_snapshot |  |
| a876b81c-b70e-4b20-a14a-84c7557d3c78 | Douair En-Nabatiyeh | 2026-09-07 | {"deaths": 1, "injuries": 9, "total_deaths": 1, "total_injuries": 9, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | village_mismatch | casualty numbers in the source belong to: Nabatieh Et-Tahta, Riha — not this village | Nabatieh Et-Tahta; Riha | 32756:raw_messages; 32767:raw_messages; 8957:merged_from_snapshot | Riha: الريحان قضاء جزين: شهيد \| Nabatieh Et-Tahta: النبطية حي المسلخ: 9 جرحى من بينهم طفلان و3 سيدات \| Nabatieh Et-Tahta: النبطية الفوقا: جريح \| Riha: شهيد \| Nabatieh Et-Tahta: 9 جرحى |
| 711adf5b-5d46-4a5c-8e21-1554c7d975b1 | Kfar Roummane | 2026-09-07 | {"deaths": 12, "injuries": 10, "total_deaths": 12, "total_injuries": 10, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | village_mismatch | casualty numbers in the source belong to: Nabatieh Et-Tahta, Riha, kafr — not this village | Nabatieh Et-Tahta; Riha; kafr | 30033:raw_messages; 4369:merged_from_snapshot; 4309:merged_from_snapshot; 4310:merged_from_snapshot; 4311:merged_from_snapshot; 4313:merged_from_snapshot; 28801:raw_messages; 29620:raw_messages; 29631:raw_messages; 5050:merged_from_snapshot; 5052:merged_from_snapshot; 5046:merged_from_snapshot; 4020:merged_from_snapshot; 5310:merged_from_snapshot | kafr: 9 شهداء \| kafr: 5 جرحى \| Nabatieh Et-Tahta: 8 شهداء \| kafr: 13 جرحى \| Riha: جريحا من بينهم 4 \| Riha: 8 شه \| Riha: 11 جريحا \| Riha: جريحاً من بينهم 4 |
| cbb16d56-f0f9-456c-9547-39945de9ff96 | Aarab Salim | 2026-09-06 | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": 2, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | village_mismatch | casualty numbers in the source belong to: Nabatieh Et-Tahta, kafr — not this village | Nabatieh Et-Tahta; kafr | 31308:raw_messages | Nabatieh Et-Tahta: وشهيدان \| kafr: إصابة 5 |
| f88a14c9-3d3e-4a40-ad4e-64705cd0eb6e | Kfar Roummane | 2026-09-06 | {"deaths": null, "injuries": 5, "total_deaths": null, "total_injuries": 5, "detail.male_d": 2, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | {"deaths": null, "injuries": null, "total_deaths": null, "total_injuries": null, "detail.male_d": null, "detail.male_i": null, "detail.female_d": null, "detail.female_i": null, "detail.children_d": null, "detail.children_i": null} | village_mismatch | casualty numbers in the source belong to: Nabatieh Et-Tahta, kafr — not this village | Nabatieh Et-Tahta; kafr | 31308:raw_messages; 31922:raw_messages; 4040:merged_from_snapshot | Nabatieh Et-Tahta: وشهيدان \| kafr: إصابة 5 |

## Fixed-seed sample of unchanged incidents

| Incident | Village | Sources | Evidence |
|---|---|---|---|

## Corrected rows with increases

| Incident | Current | Proposed | Evidence |
|---|---|---|---|

## Corrected reason breakdown

- stored values positively disproved by deterministic count/evidence validation: 1

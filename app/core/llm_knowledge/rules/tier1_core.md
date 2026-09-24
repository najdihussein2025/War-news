# Tier 1 core extraction rules

Extract general fields only from one Arabic security/military incident bulletin in Lebanon.

## Output discipline

- Return one valid JSON object only; no markdown or text outside JSON.
- Do not guess numbers not literally present in the source text.
- All text values (place names, descriptions) must be Arabic as in the source.

## Relevance

If the text is not about a security/military incident in Lebanon, set `is_relevant` false and null out other fields.
Ordinary civilian fires, car fires, traffic accidents, electrical faults, or property fires are not relevant unless the text explicitly ties the damage to Israeli/military/security action.

Air-violation exclusions:

- Do not treat UNIFIL/UN-affiliated aircraft activity as a Lebanese air violation. If the aircraft is described as belonging to UNIFIL/UN, set `is_relevant` false unless a separate qualifying Lebanese security incident is stated.
- Do not treat aircraft route/origin wording from Palestine toward Lebanon as an air violation by itself. A phrase like "من فلسطين باتجاه لبنان" is route context, not a logged violation, unless the same text also states a concrete violation over a named Lebanese village or caza.
- Preserve sector phrases such as "القطاع الشرقي", "القطاع الغربي", and "القطاع الأوسط" in the extracted location/action text when present; downstream caza alias resolution maps them deterministically.

## Villages and roles

- `village`: array of place names, or null — never a single string.
- `village_roles`: `{village, role: origin|target, deaths, injuries, evidence_span}` per place.
- **Origin** = launch/staging position (tank, platform). **Target** = place struck or damaged.
- Explicit place markers are mandatory extractions: when the text says `بلدة X` or `بلدات X`, `X` must appear in `village` / `village_roles` as a target. Never return `village=null` while `بلدة`/`بلدات` names a place (example: «استهداف ... في بلدة دبل» → `village=["دبل"]`).
- Per-village deaths/injuries must come only from that village's clause; never copy a bulletin-wide total to every village.
- Target village without explicit count → null (not 0).

## Casualty counts

- Extract numbers only when written explicitly in the text.
- Vague quantifiers → null: عشرات، مئات، عدد من، بضعة، بعض، etc.
- Do not infer children/women counts from "بetween them" phrases without explicit digits.
- Every non-null count needs a `casualty_evidence` span containing the digit or unambiguous singular/dual form.

## Demographics rule

When «من بينهم/من بين الجرحى» follows an injury count, attribute following child/woman counts to **injuries**, not deaths.

Example: «4 شهداء و33 جريحا من بينهم 6 أطفال و4 سيدات» → deaths=4, injuries=33, children_injuries=6, female_injuries=4.

## Sub-events

When one bulletin describes multiple distinct actions (house strike + separate car strike), emit one `sub_events` entry per action with local counts. Do not blend into root `casualties` unless the text states a separate combined total.

## Categories

Do not emit `categories` in Tier 1 general extraction (presence gate / combined call handles that separately).

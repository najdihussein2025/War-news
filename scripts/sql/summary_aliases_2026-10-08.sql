-- Summary bulletin aliases. Review then execute manually; this script is never run by intake.
INSERT INTO village_location_aliases (alias_text, alias_normalized, village_id, note, is_active)
SELECT 'عيتا الجبل', 'عيتا الجبل', id, 'Summary bulletin alias -> Aita al Jabal al Zot (ACS 72224).', true FROM villages WHERE acs_code = 72224
ON CONFLICT DO NOTHING;
INSERT INTO village_location_aliases (alias_text, alias_normalized, village_id, note, is_active)
SELECT 'الطيبة', 'الطيبة', id, 'Summary bulletin alias -> Taybeh Marjaayoun (ACS 73232); Baalbek homonym excluded by scope.', true FROM villages WHERE acs_code = 73232
ON CONFLICT DO NOTHING;
INSERT INTO village_location_aliases (alias_text, alias_normalized, village_id, note, is_active)
SELECT 'يحمر الشقيف', 'يحمر الشقيف', id, 'Summary bulletin alias -> Yahmor Nabatieh (ACS 71394).', true FROM villages WHERE acs_code = 71394
ON CONFLICT DO NOTHING;
INSERT INTO village_location_aliases (alias_text, alias_normalized, village_id, note, is_active)
SELECT 'دوحه كفرمان', 'دوحه كفرمان', id, 'Summary bulletin typo/variant -> Kfar Roummane (ACS 71133).', true FROM villages WHERE acs_code = 71133
ON CONFLICT DO NOTHING;

-- NEEDS CONFIRMATION: no unambiguous South/Nabatieh candidate found in 2026-10-08 SELECT.
-- مزرعة بسطرة: none
-- سدانة: none
-- علمان الشومرية: candidates include علمانة/Marjaayoun 73293 and علمان الشوف 23311; neither is an exact confirmation.
-- صريين: possible spelling relation to صريفا/Sour 62266, but not inserted without confirmation.

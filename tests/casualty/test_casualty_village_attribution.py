from app.news.services.incident_details.incident_casualty_recompute import (
    CasualtyValidationResult,
    ConnectedCasualtySource,
    ValidatedCasualtyClaim,
    _attributed_village,
    _clean_evidence,
    _is_subset_breakdown,
    resolved_casualty_values,
    village_mentions,
)
from app.news.services.incident_details.casualty_text import find_count_mentions


ALIASES = [
    ("عربصاليم", 1, "Aarab Salim"),
    ("بصاليم", 2, "Bsalim"),
    ("الريحان", 3, "Rihane Jezzine"),
    ("ريحا", 4, "Riha"),
    ("جزين", 5, "Jezzine"),
    ("النبطية الفوقا", 6, "Nabatiyeh El-Faouka"),
    ("النبطية", 7, "Nabatieh Et-Tahta"),
    ("لالا", 8, "Lala"),
    ("معاد", 9, "Maad"),
    ("برسا", 10, "Barsa"),
    ("شقرا", 11, "Shaqra"),
    ("نحلة", 12, "Nahle baalbek"),
]


def test_village_names_are_whole_tokens_and_longest_name_wins():
    assert [(item[2], item[3]) for item in village_mentions("عربصاليم", ALIASES)] == [(1, "Aarab Salim")]
    assert [(item[2], item[3]) for item in village_mentions("الريحان", ALIASES)] == [(3, "Rihane Jezzine")]
    assert [(item[2], item[3]) for item in village_mentions("النبطية الفوقا", ALIASES)] == [(6, "Nabatiyeh El-Faouka")]
    assert [(item[2], item[3]) for item in village_mentions("عربصاليم", [("عرب الصاليم", 1, "Aarab Salim")])] == [(1, "Aarab Salim")]


def test_gazetteer_names_never_match_inside_casualty_words():
    words = "جريح جريحا جرحى شهيد شهداء إصابة مصابين"
    assert village_mentions(words, ALIASES) == []


def test_short_suspicious_names_only_match_as_tokens():
    assert village_mentions("لالا معاد برسا", ALIASES)
    assert village_mentions("دلالات ومعادلة وبرسام", ALIASES) == []


def test_village_name_used_as_a_time_word_is_not_a_location():
    aliases = [("صباح", 14, "Sabbah")]
    assert village_mentions("حصيلة أولية هذا الصباح اليوم", aliases) == []


def test_district_name_is_context_not_a_village():
    text = "الريحان قضاء جزين: شهيد"
    assert _attributed_village(text, "شهيد", ALIASES) == (3, "Rihane Jezzine")
    assert {item[3] for item in village_mentions(text, ALIASES)} == {"Rihane Jezzine"}


def test_caza_inserted_between_village_and_gazetteer_suffix():
    aliases = [("ريحانة جزين", 13, "Rihane Jezzine"), ("جزين", 5, "Jezzine")]
    assert _attributed_village("الريحان قضاء جزين: شهيد", "شهيد", aliases) == (13, "Rihane Jezzine")


def test_claim_uses_location_in_its_own_clause():
    text = "النبطية حي المسلخ: 9 جرحى من بينهم طفلان و3 سيدات\nالنبطية الفوقا: جريح"
    assert _attributed_village(text, "جريح", ALIASES) == (6, "Nabatiyeh El-Faouka")
    assert _attributed_village(text, "9 جرحى", ALIASES) == (7, "Nabatieh Et-Tahta")


def test_source_target_does_not_pull_a_count_across_a_clause_boundary():
    text = "تقرير عن دير الزهراني في النبطية بعد غارات كثيرة، مع دمار واسع و40 ضحية"
    aliases = [("دير الزهراني", 15, "Deir Ez-Zahrani"), ("النبطية", 7, "Nabatieh Et-Tahta")]
    source = ConnectedCasualtySource(1, text, None, None, "raw_messages", match_result={"village_matches": [{"matched_village_id": 15, "village_role": "target"}]})
    assert _attributed_village(text, "40 ضحية", aliases, source) is None


def test_shared_toll_before_several_places_is_not_assigned_to_one():
    text = "4 شهداء و20 جريحا في غارات على عربصاليم والنبطية والنبطية الفوقا"
    assert _attributed_village(text, "4 شهداء", ALIASES) is None


def test_wadi_name_is_not_mistaken_for_the_baalbek_village():
    text = "جريحان جراء القصف على وادي نحلة - شقرا"
    assert _attributed_village(text, "جريحان", ALIASES) == (11, "Shaqra")


def test_subset_number_is_not_a_total():
    assert _is_subset_breakdown("12 جريحا من بينهم 4 أطفال", 4)
    assert _is_subset_breakdown("جرحى بينهم 3 سيدات", 3)
    assert not _is_subset_breakdown("4 جرحى", 4)


def test_resolved_values_obey_local_total_and_demographic_invariants():
    fields = {name: None for name in ("deaths", "injuries", "total_deaths", "total_injuries", "male_d", "male_i", "female_d", "female_i", "children_d", "children_i")}
    orphan = ValidatedCasualtyClaim(1, "raw_messages", 1, "Aarab Salim", {**fields, "children_i": 4}, {"children_i": "4 أطفال"})
    values, _ = resolved_casualty_values(CasualtyValidationResult((orphan,), (1,), 1, 1, 0, ("Aarab Salim",)), 1)
    assert values["injuries"] == 4 and values["total_injuries"] == 4 and values["children_i"] == 4

    grounded = ValidatedCasualtyClaim(1, "raw_messages", 1, "Aarab Salim", {**fields, "injuries": 12, "children_i": 4}, {"injuries": "12 جريحا", "children_i": "4 أطفال"})
    values, _ = resolved_casualty_values(CasualtyValidationResult((grounded,), (1,), 1, 1, 0, ("Aarab Salim",)), 1)
    assert values["injuries"] == 12
    assert values["total_injuries"] >= values["children_i"]


def test_evidence_is_full_clean_clause_with_casualty_word():
    text = "جريحان جراء القصف على وادي نحلة - شقرا\nقناة إخبارية\nhttps://example.test/x"
    evidence = _clean_evidence(text, "injuries", 2, "ي")
    assert evidence and "جريحان" in evidence and "https://" not in evidence and len(evidence) <= 200


def test_round4_g1_location_after_casualty_phrase_in_comma_clause():
    text = "إصابة 5 أشخاص في بلدة كفررمان، وشهيدان في اعتداء استهدف بلدة عربصاليم في القضاء نفسه"
    aliases = [("كفررمان", 20, "Kfar Roummane"), ("عرب صاليم", 1, "Aarab Salim")]
    assert _attributed_village(text, "شهيدان", aliases) == (1, "Aarab Salim")  # cbb16d56


def test_round4_g2_caza_and_region_are_qualifiers():
    aliases = [("حداثا", 21, "Haddatha"), ("بنت جبيل", 22, "Bint Jbeil"), ("جبيل", 30, "Jbayl"), ("عمرة", 31, "Aamra"), ("ياطر", 23, "Yater")]
    qualifiers = frozenset({"بنت جبيل", "جنوب لبنان"})
    assert _attributed_village("جريحان في غارة على بلدة حداثا في قضاء بنت جبيل", "جريحان", aliases, qualifier_names=qualifiers) == (21, "Haddatha")  # 12bb4e8d
    assert _attributed_village("غارة على بلدة حداثا قضاء بنت جبيل أدت إلى جريحين", "جريحين", aliases, qualifier_names=qualifiers) == (21, "Haddatha")  # 9fb9f022
    assert _attributed_village("سحب جثمان بعد استهدافه في ياطر – بنت جبيل", "جثمان", aliases, qualifier_names=qualifiers) == (23, "Yater")  # 73ff98a1
    assert village_mentions("جريحان بينهما طفل عمره 4 سنوات في حداثا", aliases, qualifiers)[0][3] == "Haddatha"


def test_round4_g3_longest_real_gazetteer_form_wins():
    aliases = [("نبطية الفوقا", 24, "Nabatiyeh El-Faouka"), ("النبطية", 7, "Nabatieh Et-Tahta")]
    assert _attributed_village("النبطية الفوقا: شهيدان وجريحان", "شهيدان", aliases) == (24, "Nabatiyeh El-Faouka")  # 11624631
    assert _attributed_village("غارة تستهدف النبطية الفوقا وسقوط شهيدين", "شهيدين", aliases) == (24, "Nabatiyeh El-Faouka")  # 636e9cec
    long_clause = "ة للغارات الإسرائيليّة على الجنوب صدر عن مركز عمليات طوارئ الصحة التابع لوزارة الصحة العامة بيان أعلن الحصيلة الأولية للغارات التي شنها الجيش الإسرائيلي هذا الصباح وفق التالي:- النبطية الفوقا: شهيدان"
    assert _attributed_village(long_clause, "شهيدان", aliases) == (24, "Nabatiyeh El-Faouka")
    source = "عنوان Link الحصيلة الأوليّة للغارات الإسرائيليّة على الجنوب صدر عن مركز عمليات طوارئ الصحة التابع لوزارة الصحة العامة بيان أعلن الحصيلة الأولية للغارات التي شنها الجيش الإسرائيلي هذا الصباح وفق التالي:- النبطية الفوقا: شهيدان وجريحان - النبطية"
    evidence = _clean_evidence(source, "deaths", 2)
    assert evidence and _attributed_village(source, evidence, aliases) == (24, "Nabatiyeh El-Faouka")
    matched = ConnectedCasualtySource(1, "غارة تستهدف النبطية الفوقا، ومعلومات أولية عن سقوط شهيدين", None, None, "raw_messages", match_result={"village_matches": [{"raw_village_text": "النبطية الفوقا", "matched_village_id": 24, "village_role": "target"}]})
    assert _attributed_village(matched.text, "شهيدين", aliases, matched) == (24, "Nabatiyeh El-Faouka")


def test_round4_g4_main_count_survives_later_subset():
    mentions = find_count_mentions("8 شهداء من بينهم طفل وسيدتان، و11 جريحا من بينهم 4 أطفال")
    totals = {(item.kind, item.value) for item in mentions if item.kind and item.counts_total}
    assert ("injuries", 11) in totals
    assert ("injuries", 4) not in totals  # 1a5b73de and 711adf5b


def test_round4_g5_road_between_places_uses_incident_endpoint():
    aliases = [("حاروف", 25, "Harouf En-Nabatiyeh"), ("زبدين", 26, "Zibdine")]
    text = "شهيد جراء غارة على طريق مرج حاروف - زبدين"
    source = ConnectedCasualtySource(1, text, None, None, "raw_messages", match_result={"village_matches": [{"matched_village_id": 25, "village_role": "target"}]})
    assert _attributed_village(text, "شهيد", aliases, source, incident_village_id=25) == (25, "Harouf En-Nabatiyeh")  # ae3efd5c


def test_round4_g6_hometown_is_not_event_location():
    aliases = [("جبشيت", 27, "Jibchit"), ("عرب صاليم", 1, "Aarab Salim")]
    text = "الشهيدة إسراء بهجة من بلدة جبشيت إرتقت في غارة عربصاليم الأولى"
    assert _attributed_village(text, "الشهيدة", aliases) == (1, "Aarab Salim")  # 5105bf71, ae6e8ddb


def test_round4_g7_common_word_village_requires_location_context():
    aliases = [("حدث", 28, "Hadath Beyrouth"), ("مجدل زون", 29, "Majdelzoun")]
    text = "وقع حدث عملياتي في بلدة مجدل زون ونقل 5 إصابات إلى مستشفى رامبام"
    assert {item[3] for item in village_mentions(text, aliases)} == {"Majdelzoun"}  # b8702f96
    assert village_mentions("وقع حدث عملياتي", aliases) == []
    assert village_mentions("في حدث غارة", aliases)[0][3] == "Hadath Beyrouth"

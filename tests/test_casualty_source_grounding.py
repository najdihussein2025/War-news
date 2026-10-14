from app.core.llm_knowledge.message_text import clean_message_text
from app.llm.dtos import ExtractionCasualties
from app.news.services.incident_details.casualty_gender_evidence import reject_unproven_demographics


def test_clean_message_text_removes_known_page_header_and_normalizes_digits():
    assert clean_message_text("صفحة الإعلامي الشهيد علي شعيب:\nغارة على شقرا ١١") == "غارة على شقرا 11"


def test_grammatical_dual_does_not_prove_male_demographic():
    value = ExtractionCasualties(deaths=2, total_deaths=2, male_deaths=2)
    assert reject_unproven_demographics("استشهد شهيدان في عربصاليم", value).male_deaths is None


def test_explicit_woman_is_retained():
    value = ExtractionCasualties(deaths=1, total_deaths=1, female_deaths=1)
    assert reject_unproven_demographics("استشهاد سيدة", value).female_deaths == 1

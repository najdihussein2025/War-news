import pytest
from app.news.services.summaries.intake_service import _original_evidence


def test_unresolved_arabic_place_preserves_original_spelling():
    raw = "القصف المدفعي: وادي نحلة(أطراف شقرا)"
    assert _original_evidence(raw, "وادي نحله(اطراف شقرا)") == "وادي نحلة(أطراف شقرا)"


def test_missing_evidence_is_rejected():
    with pytest.raises(ValueError):
        _original_evidence("القصف المدفعي: حاريص", "مكان غير موجود")

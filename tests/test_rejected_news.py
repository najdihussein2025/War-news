from types import SimpleNamespace

from app.api.rejected_news_router import _news_summary, _reason
from app.news.models import MessageStatus


def test_rejection_reason_reports_duplicate_target() -> None:
    message = SimpleNamespace(status=MessageStatus.duplicate, duplicate_of_id=42)
    assert _reason(message) == ("duplicate", "الخبر مكرر ومطابق للخبر الخام #42.")


def test_rejection_reason_reports_not_relevant_explanation() -> None:
    message = SimpleNamespace(
        status=MessageStatus.rejected,
        duplicate_of_id=None,
        filter_result={"verdict": "not_relevant", "reasoning": "Not related to Lebanon."},
        cnrs_classification=None,
        error_message=None,
        low_confidence_relevance=False,
    )
    assert _reason(message) == ("not_relevant", "الخبر غير مرتبط بلبنان.")


def test_rejection_reason_reports_uncertain_review() -> None:
    message = SimpleNamespace(
        status=MessageStatus.rejected,
        duplicate_of_id=None,
        filter_result={"verdict": "uncertain", "reason": "Location is unclear."},
        cnrs_classification=None,
        error_message=None,
        low_confidence_relevance=True,
    )
    assert _reason(message) == ("uncertain", "موقع الحدث غير واضح.")


def test_rejection_reason_translates_missing_canonical_village() -> None:
    message = SimpleNamespace(
        status=MessageStatus.rejected,
        duplicate_of_id=None,
        filter_result={"verdict": "not_relevant", "reasoning": "No canonical village matched"},
        cnrs_classification=None,
        error_message=None,
        low_confidence_relevance=False,
    )
    assert _reason(message) == (
        "not_relevant",
        "لم يتم العثور على بلدة معتمدة مطابقة للخبر.",
    )


def test_news_summary_removes_hashtag_and_writes_complete_fighter_sentence() -> None:
    message = SimpleNamespace(raw_text="🔴 ✈️ #مقاتلات_حربية اتجاه لبنان الخريطة المباشرة <O>")
    assert _news_summary(message) == "رُصدت مقاتلات حربية متجهة نحو لبنان."


def test_news_summary_replaces_noisy_drone_ocr_with_complete_sentence() -> None:
    message = SimpleNamespace(raw_text="redalert.com.lb __RED_ZONE_TEXT__ مسيرة SSS OOS")
    assert _news_summary(message) == "رُصدت طائرة مسيّرة. تعذّر تحديد المنطقة بدقة من الصورة."


def test_news_summary_rewrites_red_alert_update_as_short_complete_news() -> None:
    message = SimpleNamespace(
        raw_text=(
            "آخر تحديث للمناطق المتأثرة بنشاط #المسير المعادي في أجواء #لبنان "
            "يُرجى أخذ الحيطة والحذر. ملاحظة: عدد الدوائر الحمراء يدل على عدد المناطق المتأثرة."
        )
    )

    assert _news_summary(message) == (
        "تحديث: نشاط طائرات مسيّرة معادية في أجواء لبنان. يُرجى الحيطة والحذر."
    )

    message.raw_text = message.raw_text.replace("آخر تحديث", "اخر تحديث")
    assert _news_summary(message) == (
        "تحديث: نشاط طائرات مسيّرة معادية في أجواء لبنان. يُرجى الحيطة والحذر."
    )


def test_news_summary_never_exposes_unreadable_red_alert_ocr() -> None:
    message = SimpleNamespace(
        raw_text="RED IALERT redalert.com.lb Nabatieh oe ae SSS __RED_ZONE_TEXT__ 4 عن"
    )

    summary = _news_summary(message)

    assert summary == "رُصدت طائرة مسيّرة. تعذّر تحديد المنطقة بدقة من الصورة."
    assert "SSS" not in summary

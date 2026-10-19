from app.news.services.materialization.verification_signals import count_missing_reason, natural_casualty_total, shared_toll_member_reason, shared_toll_owner_reason


def test_natural_arabic_casualty_totals() -> None:
    assert natural_casualty_total(10, None) == "10 شهداء"
    assert natural_casualty_total(None, 5) == "5 جرحى"
    assert natural_casualty_total(10, 5) == "10 شهداء و5 جرحى"


def test_shared_toll_messages_use_real_values() -> None:
    owner = shared_toll_owner_reason("10 شهداء و5 جرحى", "صور، النبطية، بيروت")
    member = shared_toll_member_reason("10 شهداء و5 جرحى", "صور")
    assert "صور، النبطية، بيروت" in owner and "توزيع الأعداد" in owner
    assert "مسجلة على سجل صور" in member


def test_count_missing_message_is_actionable_arabic() -> None:
    assert count_missing_reason() == "الخبر ذكر وقوع إصابات دون تحديد العدد. يرجى التحقق وإدخال الأعداد يدوياً."

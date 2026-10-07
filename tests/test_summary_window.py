from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from app.news.services.summaries.window import resolve_window

TZ=ZoneInfo('Asia/Beirut')
def d(day,h,m=0): return datetime(2026,10,day,h,m,tzinfo=TZ)

def test_reference_numeric_night():
    w=resolve_window('منذ ليل امس بعد الساعة ١٢ ليلاً وحتى الساعة ١١:١٣ ليلاً',d(5,23,36))
    assert (w.start.hour,w.end.hour,w.end.minute)==(0,23,13)
def test_early_morning_previous_anchor():
    w=resolve_window('من منتصف الليل حتى الساعة',d(3,0,3))
    assert w.anchor_date.isoformat()=='2026-10-02' and w.start.day==2
def test_hour_word():
    w=resolve_window('من منتصف الليل حتى الساعة الثامنة صباحاً',d(5,10))
    assert (w.end.hour,w.end.minute)==(8,0)
def test_incremental_previous_end():
    prior=d(5,9); w=resolve_window('ملخص حتى الآن',d(5,14),prior)
    assert w.start==prior and w.end==d(5,14)
def test_explicit_missing_year_rolls_back():
    w=resolve_window('ملخص بتاريخ 31/12',datetime(2026,1,2,12,tzinfo=TZ))
    assert w.anchor_date.isoformat()=='2025-12-31'
def test_last_24_hours():
    w=resolve_window('خلال الـ24 ساعة الماضية',d(5,12)); assert (w.end-w.start).total_seconds()==86400
def test_dst_local_boundaries():
    w=resolve_window('ملخص بتاريخ 24/10/2026',datetime(2026,10,25,12,tzinfo=TZ))
    assert w.start.tzinfo.key=='Asia/Beirut' and w.start.utcoffset()!=w.end.utcoffset()
def test_naive_rejected():
    with pytest.raises(ValueError): resolve_window('ملخص',datetime(2026,1,1))

def test_stale_explicit_date_real_late_post_and_early_post():
    late=resolve_window('ملخص بتاريخ ١٥/٩/٢٠٢٦',datetime(2026,9,16,23,58,tzinfo=TZ))
    early=resolve_window('ملخص بتاريخ ١٥/٩/٢٠٢٦',datetime(2026,9,16,0,2,tzinfo=TZ))
    assert late.rule=='explicit_date:stale_suspect' and late.end.day==16 and late.note=='stale_explicit_date'
    assert early.rule=='explicit_date' and early.end.day==16 and early.note is None

def test_old_and_future_explicit_date_notes():
    old=resolve_window('ملخص بتاريخ ١٣/٩/٢٠٢٦',datetime(2026,9,16,12,tzinfo=TZ))
    future=resolve_window('ملخص بتاريخ ١٧/٩/٢٠٢٦',datetime(2026,9,16,12,tzinfo=TZ))
    assert old.note=='old_summary_reshared'
    assert future.note=='future_date_ignored' and future.start.day==16


# Stale-date rule is measured against the anchor day, not the posting date.
def test_28327_posted_00_00_51_with_previous_days_date_is_stale_against_anchor():
    posted = datetime(2026, 9, 17, 0, 0, 51, tzinfo=TZ)
    w = resolve_window('ملخص بتاريخ ١٥/٩', posted)
    assert w.rule == 'explicit_date:stale_suspect' and w.note == 'stale_explicit_date'
    assert w.start == datetime(2026, 9, 15, tzinfo=TZ) and w.end == posted
    assert w.anchor_date.isoformat() == '2026-09-16'  # timed events belong to the 16th

def test_28316_family_posted_23_58_is_stale_suspect():
    posted = datetime(2026, 9, 16, 23, 58, 12, tzinfo=TZ)
    w = resolve_window('ملخص بتاريخ ١٥/٩/٢٠٢٦', posted)
    assert w.rule == 'explicit_date:stale_suspect' and w.end == posted and w.anchor_date.isoformat() == '2026-09-16'

def test_28017_posted_00_02_for_previous_day_is_normal():
    w = resolve_window('ملخص بتاريخ ١٥/٩/٢٠٢٦', datetime(2026, 9, 16, 0, 2, 54, tzinfo=TZ))
    assert w.rule == 'explicit_date' and w.note is None
    assert (w.start, w.end) == (datetime(2026, 9, 15, tzinfo=TZ), datetime(2026, 9, 16, tzinfo=TZ))

def test_explicit_date_equal_to_anchor_is_normal_and_older_is_reshared():
    posted = datetime(2026, 9, 16, 12, tzinfo=TZ)
    assert resolve_window('ملخص بتاريخ ١٦/٩/٢٠٢٦', posted).note is None
    assert resolve_window('ملخص بتاريخ ١٤/٩/٢٠٢٦', posted).note == 'old_summary_reshared'
    # Early morning: anchor is the 16th, so the 14th is two days stale, not one.
    assert resolve_window('ملخص بتاريخ ١٤/٩/٢٠٢٦', datetime(2026, 9, 17, 0, 30, tzinfo=TZ)).note == 'old_summary_reshared'
    assert resolve_window('ملخص بتاريخ ١٥/٩/٢٠٢٦', datetime(2026, 9, 17, 0, 30, tzinfo=TZ)).note == 'stale_explicit_date'

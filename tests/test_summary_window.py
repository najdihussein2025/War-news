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

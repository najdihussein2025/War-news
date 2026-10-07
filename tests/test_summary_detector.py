import json
from pathlib import Path
from app.news.services.summaries.detection import detect_summary

def test_all_recon_bulletins_detected():
    rows=[json.loads(x) for x in Path('recon_output/summary_bulletins.jsonl').open(encoding='utf-8')]
    missed=[r['message_id'] for r in rows if not detect_summary(r['text']).is_summary]
    assert missed == []

def test_live_news_negatives():
    samples=[
      "غارة إسرائيلية استهدفت بلدة الخيام", "قصف مدفعي على المنصوري", "شهيدان وثلاثة جرحى في النبطية",
      "تحليق طيران مسير فوق صور", "انفجار في منزل في حولا", "الملخص التنفيذي للتقرير السياسي",
      "نقلت الوكالة ملخص كلام الوزير", "غارتان على بلدتي الخيام وكفركلا", "قصف على أطراف ميفدون",
      "إطلاق قنابل مضيئة فوق الحدود", "تحركات آليات قرب الوزاني", "خبر عاجل من بنت جبيل",
      "سلسلة غارات استهدفت الجنوب", "إصابة مدني في بلدة شقرا", "طيران حربي في أجواء صيدا",
    ]
    assert all(not detect_summary(x).is_summary for x in samples)

def test_structural_detection():
    text="القصف المدفعي: الخيام، المنصوري، شقرا\nالتفجيرات: حولا، ميفدون، ارنون"
    result=detect_summary(text)
    assert result.is_summary and result.header_count >= 2 and result.segment_count >= 6

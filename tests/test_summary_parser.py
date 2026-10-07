import json, sys
from pathlib import Path
import yaml
from app.news.services.summaries.dtos import HeaderEntry, VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import HeaderDictionarySnapshot, default_header_dictionary
from app.news.services.summaries.parser import parse_summary

LEX=yaml.safe_load(Path('app/core/llm_knowledge/terminology/summary_location_lexicon.yaml').read_text(encoding='utf-8'))
def gaz():
    names={n:[VillageRef(i,n,'Nabatiye',i*1000.0,0)] for i,n in enumerate(['الخيام','المنصوري','ميفدون','حداثا','حاريص','شقرا','كفرتبنيت'],1)}
    return GazetteerSnapshot(names,LEX['qualifiers'])
def parse(text,g=None,h=None): return parse_summary(text,g or gaz(),h or default_header_dictionary(),LEX)

def test_inline_multiple_headers_and_counts():
    p=parse('ملخص الاعتداءات: القصف المدفعي: الخيام المنصوري التفجيرات: ميفدون (٢) الخيام القنابل المضيئة: شقرا المنصوري')
    assert {i.condition_id for i in p.items}=={5,21,9} and any(i.reported_count==2 for i in p.items)
def test_between_attached_w_and_dash_are_one_item():
    a=parse('القصف المدفعي: بين حداثا وحاريص'); b=parse('القصف المدفعي: حداثا-حاريص')
    assert len(a.items)==len(b.items)==1 and a.items[0].secondary_village.name_ar=='حاريص'
def test_compound_header_two_items_per_place():
    p=parse('القصف المدفعي و الفوسفوري: الخيام')
    assert [i.condition_id for i in p.items]==[5,7]
def test_prefix_and_suffix_qualifiers():
    p=parse('القصف المدفعي: اطراف ميفدون، الخيام لجهة حاريص')
    assert 'اطراف' in p.items[0].qualifiers and any('لجهه' in q for q in p.items[1].qualifiers)
def test_dynamic_segmentation_and_conjunction():
    p=parse('القصف المدفعي: الخيام المنصوري ميفدون، حداثا و حاريص')
    assert {i.primary_village.name_ar for i in p.items}=={'الخيام','المنصوري','ميفدون','حداثا','حاريص'}
def test_ambiguous_and_out_of_scope_and_leftover():
    g=gaz(); g.names['عين']=(VillageRef(20,'عين','Sour'),VillageRef(21,'عين','Nabatiye'))
    p=parse_summary('القصف المدفعي: عين، كلمةغريبة\nتحركات واليات العدو في المنطقة الحدودية',g,default_header_dictionary(),LEX)
    assert p.ambiguous_places and p.leftover_tokens and not p.auto_acceptable
def test_out_of_south_absent():
    assert parse('القصف المدفعي: جبيل').unresolved_places==('جبيل',)
def test_d2_merge_and_deterministic_key():
    text='القصف المدفعي: ميفدون، اطراف ميفدون'
    a=parse(text); b=parse(text)
    assert len(a.items)==1 and len(a.items[0].location_texts)==2 and a.items[0].item_key==b.items[0].item_key
def test_pure_imports_do_not_load_sqlalchemy_or_settings():
    files=['normalize.py','detection.py','window.py','parser.py','headers.py']
    source='\n'.join((Path('app/news/services/summaries')/name).read_text(encoding='utf-8') for name in files)
    assert 'sqlalchemy' not in source.lower() and 'app.core.config' not in source
